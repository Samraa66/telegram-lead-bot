"""
FastAPI application: lead tracking + signal mirroring.

- POST /webhook: receives Telegram updates; validates secret; routes message → leads,
  channel_post → signals.
- GET /stats/*: analytics for leads.
- GET /health: health check for monitoring.
"""

import asyncio
import json
import logging
import os
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager

from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, conint
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.auth import authenticate_user, create_access_token, get_current_user, get_workspace_id, get_org_id, require_roles, require_affiliate, require_org_owner, require_workspace_owner
from app.config import WEBHOOK_SECRET
from app.database import get_db, init_db, SessionLocal
from app.database.models import User, PendingChannel
from app.handlers.outbound import handle_outbound
from app.handlers.leads import process_lead_update
from app.handlers.signals import process_signal_update
from app.bot import send_message
from app.services.analytics import (
    get_today_stats, get_stats_by_source, get_messages_per_day,
    get_overview, get_conversion_metrics, get_stage_distribution,
    get_hourly_heatmap, get_day_of_week, get_leads_over_time,
    get_campaign_performance, get_underperforming_campaigns,
    get_campaign_alerts, get_best_performing_creatives,
    get_affiliate_performance,
)
from app.services.crm_queries import get_contacts, get_contact_messages
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.pipeline import set_stage_manual

GRAPH_API_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

_WORKSPACE_ID = 1  # single-tenant; becomes dynamic in Phase 8

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup and log server start."""
    init_db()
    start_scheduler()
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
    from app.services.telethon_client import start_all_telethon_clients, stop_all_telethon_clients
    try:
        await start_all_telethon_clients(TELEGRAM_API_ID, TELEGRAM_API_HASH)
    except Exception:
        logger.exception("Telethon failed to start — server will run without it.")
    logger.info("Server starting; database initialized")
    yield
    await stop_all_telethon_clients()
    stop_scheduler()
    logger.info("Server shutting down")


limiter = Limiter(key_func=get_remote_address)

# Resolve frontend dist path once at startup — used by the SPA middleware below
_FRONTEND_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)
_SPA_INDEX = os.path.join(_FRONTEND_DIST, "index.html")

app = FastAPI(
    title="Lead Tracking & Signal Mirroring Bot API",
    description="Webhook for leads and signal mirroring; analytics for leads.",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# SPA fallback — must be added BEFORE security-headers middleware so it runs first.
# When a browser navigates to a frontend route (e.g. /affiliates after a hard refresh),
# it sends Accept: text/html and no Authorization header.  API calls from JavaScript
# always include Authorization.  We intercept browser navigations and serve index.html
# so the React router can handle the path instead of letting the API route return 401.
_API_PASS_THROUGH = ("/assets/", "/webhook", "/auth/", "/health", "/api/")

@app.middleware("http")
async def spa_browser_nav_middleware(request: Request, call_next):
    if (
        os.path.isfile(_SPA_INDEX)
        and "text/html" in request.headers.get("Accept", "")
        and "Authorization" not in request.headers
        and not any(request.url.path.startswith(p) for p in _API_PASS_THROUGH)
    ):
        return FileResponse(_SPA_INDEX)
    return await call_next(request)


# Security headers on every response
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response

# CORS: production domain + localhost for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://telelytics.org",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _validate_webhook_secret(request: Request, expected_secret: Optional[str] = None) -> bool:
    """Return True if no secret is configured or the header matches."""
    if not expected_secret:
        return True
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
    return header_secret == expected_secret


async def _handle_webhook(request: Request, db: Session, workspace_id: int, secret: Optional[str] = None) -> dict:
    """Shared webhook logic for both legacy /webhook and /webhook/{workspace_id}."""
    if not _validate_webhook_secret(request, secret):
        logger.warning("Webhook rejected: invalid or missing secret (ws=%s)", workspace_id)
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        body = await request.json()
    except Exception as e:
        logger.warning("Webhook invalid JSON: %s", e)
        return {"ok": False, "error": "invalid json"}

    update_id = body.get("update_id", "?")
    logger.info("Webhook received (update_id=%s, ws=%s)", update_id, workspace_id)

    try:
        if body.get("message") is not None:
            reply_text, chat_id = process_lead_update(body, db, workspace_id)
            if reply_text and chat_id is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, send_message, chat_id, reply_text, workspace_id)
            return {"ok": True}

        if body.get("channel_post") is not None or body.get("edited_channel_post") is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, process_signal_update, body)
            return {"ok": True}

        if body.get("my_chat_member") is not None:
            mcm = body["my_chat_member"]
            new_status = mcm.get("new_chat_member", {}).get("status", "")
            chat = mcm.get("chat", {})
            chat_id = str(chat.get("id", ""))
            chat_title = chat.get("title") or chat.get("username") or chat_id
            chat_type = chat.get("type", "")

            if new_status in ("administrator", "member") and chat_type in ("channel", "supergroup", "group") and chat_id:
                existing = db.query(PendingChannel).filter(PendingChannel.chat_id == chat_id).first()
                if not existing:
                    from app.database.models import Affiliate
                    already_linked = db.query(Affiliate).filter(
                        (Affiliate.free_channel_id == chat_id) |
                        (Affiliate.vip_channel_id == chat_id) |
                        (Affiliate.tutorial_channel_id == chat_id)
                    ).first()
                    if not already_linked:
                        db.add(PendingChannel(chat_id=chat_id, title=chat_title))
                        db.commit()
                        logger.info("Bot added to channel %s (%s) — stored as pending", chat_title, chat_id)
            elif new_status in ("left", "kicked") and chat_id:
                db.query(PendingChannel).filter(PendingChannel.chat_id == chat_id).delete()
                db.commit()
            return {"ok": True}

        logger.debug("Webhook update type not handled (update_id=%s); ignoring", update_id)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Webhook handler error (update_id=%s): %s", update_id, e)
        return {"ok": True}


@app.post("/webhook")
async def webhook_legacy(request: Request, db: Session = Depends(get_db)):
    """Legacy single-workspace webhook (workspace 1). Kept for backward compatibility."""
    return await _handle_webhook(request, db, workspace_id=1)


@app.post("/webhook/{workspace_id}")
async def webhook(request: Request, workspace_id: int, db: Session = Depends(get_db)):
    """
    Per-workspace webhook. Telegram sends updates here.
    Validates the workspace-specific webhook_secret (or env WEBHOOK_SECRET for ws 1).
    Always returns 200 on valid JSON so Telegram does not retry.
    """
    from app.database.models import Workspace
    if workspace_id == 1:
        secret = WEBHOOK_SECRET or None  # workspace 1 uses .env secret
    else:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="workspace not found")
        secret = ws.webhook_secret or None  # other workspaces use their own secret only

    return await _handle_webhook(request, db, workspace_id=workspace_id, secret=secret)


# ---------------------------------------------------------------------------
# Workspace management
# ---------------------------------------------------------------------------

class WorkspaceCreateRequest(BaseModel):
    name: str


@app.get("/workspaces")
def list_workspaces(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer")),
):
    """List all workspaces (developer only)."""
    from app.database.models import Workspace
    from app.services.telethon_client import get_client
    rows = db.query(Workspace).order_by(Workspace.id).all()
    return [
        {
            "id": ws.id,
            "name": ws.name,
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
            "has_telethon": get_client(ws.id) is not None,
            "has_meta": bool(ws.meta_access_token),
            "has_bot_token": bool(ws.bot_token),
        }
        for ws in rows
    ]


@app.post("/workspaces", status_code=201)
def create_workspace(
    req: WorkspaceCreateRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer")),
):
    """Create a new workspace and seed it with default pipeline settings (developer only)."""
    from app.database.models import Workspace
    from app.database import seed_workspace_defaults

    ws = Workspace(name=req.name.strip())
    db.add(ws)
    db.commit()
    db.refresh(ws)

    seed_workspace_defaults(ws.id, db)

    return {
        "id": ws.id,
        "name": ws.name,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


@app.post("/auth/switch-workspace/{workspace_id}")
def switch_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """Issue a new JWT scoped to a different workspace."""
    from app.database.models import Workspace
    caller_org_id = current_user.get("org_id", 1)
    caller_ws_id = current_user.get("workspace_id", 1)
    org_role = current_user.get("org_role", "member")

    if current_user["role"] == "developer":
        # Developer can switch to any workspace
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    elif org_role == "org_owner":
        # Org owner can switch to any workspace in their org
        ws = db.query(Workspace).filter(
            Workspace.id == workspace_id,
            Workspace.org_id == caller_org_id,
        ).first()
    else:
        # Workspace owner can only switch within their subtree
        all_ws = db.query(Workspace).filter(Workspace.org_id == caller_org_id).all()
        subtree = _ws_subtree(all_ws, caller_ws_id)
        ws = next((w for w in subtree if w.id == workspace_id), None)

    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    token = create_access_token(
        current_user["username"], current_user["role"],
        workspace_id=workspace_id,
        org_id=ws.org_id or caller_org_id,
        org_role=current_user.get("org_role", "org_owner"),
    )
    return {
        "access_token": token,
        "workspace_id": workspace_id,
        "workspace_name": ws.name,
        "org_id": ws.org_id or caller_org_id,
    }


# ---------------------------------------------------------------------------
# Org workspace management (tree-scoped)
# ---------------------------------------------------------------------------

class OrgWorkspaceCreateRequest(BaseModel):
    name: str
    parent_workspace_id: Optional[int] = None


def _ws_subtree(all_ws: list, root_id: int) -> list:
    """Return all workspaces in the subtree rooted at root_id (BFS, no SQL recursion)."""
    children_map: dict[int, list] = {}
    ws_map = {ws.id: ws for ws in all_ws}
    for ws in all_ws:
        if ws.parent_workspace_id:
            children_map.setdefault(ws.parent_workspace_id, []).append(ws.id)
    result, queue = [], [root_id]
    while queue:
        cid = queue.pop(0)
        if cid in ws_map:
            result.append(ws_map[cid])
            queue.extend(children_map.get(cid, []))
    return result


@app.get("/org/workspaces")
def list_org_workspaces(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """
    Return workspaces visible to the caller:
    - org_owner / developer / admin → all workspaces in the org
    - workspace_owner (affiliate)   → their own workspace + their subtree only
    """
    from app.database.models import Workspace
    from app.services.telethon_client import get_client
    org_id = current_user.get("org_id", 1)
    org_role = current_user.get("org_role", "member")
    caller_ws_id = current_user.get("workspace_id", 1)

    all_ws = db.query(Workspace).filter(Workspace.org_id == org_id).order_by(Workspace.id).all()

    if org_role == "org_owner" or current_user.get("role") in ("developer", "admin"):
        rows = all_ws
    else:
        rows = _ws_subtree(all_ws, caller_ws_id)

    def _fmt(ws):
        return {
            "id": ws.id,
            "name": ws.name,
            "org_id": ws.org_id,
            "parent_workspace_id": ws.parent_workspace_id,
            "root_workspace_id": ws.root_workspace_id,
            "workspace_role": ws.workspace_role or "owner",
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
            "has_telethon": get_client(ws.id) is not None,
            "has_meta": bool(ws.meta_access_token),
            "has_bot_token": bool(ws.bot_token),
        }
    return [_fmt(ws) for ws in rows]


@app.post("/org/workspaces", status_code=201)
def create_org_workspace(
    req: OrgWorkspaceCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """
    Create a child workspace under the caller's org.
    parent_workspace_id defaults to the caller's own workspace (one level down).
    """
    from app.database.models import Workspace
    from app.database import seed_workspace_defaults

    org_id = current_user.get("org_id", 1)
    caller_ws_id = current_user.get("workspace_id", 1)
    parent_id = req.parent_workspace_id or caller_ws_id

    # Verify parent belongs to caller's org
    parent = db.query(Workspace).filter(
        Workspace.id == parent_id,
        Workspace.org_id == org_id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent workspace not found in your org")

    root_id = parent.root_workspace_id or parent.id

    ws = Workspace(
        name=req.name.strip(),
        org_id=org_id,
        parent_workspace_id=parent_id,
        root_workspace_id=root_id,
        workspace_role="affiliate",
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)

    seed_workspace_defaults(ws.id, db)

    from app.services.telethon_client import get_client
    return {
        "id": ws.id,
        "name": ws.name,
        "org_id": ws.org_id,
        "parent_workspace_id": ws.parent_workspace_id,
        "root_workspace_id": ws.root_workspace_id,
        "workspace_role": ws.workspace_role,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
        "has_telethon": get_client(ws.id) is not None,
        "has_meta": bool(ws.meta_access_token),
        "has_bot_token": bool(ws.bot_token),
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
@limiter.limit("5/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token. Checks env-based roles and DB affiliates."""
    user = authenticate_user(req.username, req.password, db=db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    ws_id = user.get("workspace_id", 1)

    # Resolve org context from the workspace the user belongs to
    from app.database.models import Workspace as WsModel, Affiliate as AffModel
    org_id = 1
    org_role = "member"

    if user["role"] in ("developer", "admin"):
        org_role = "org_owner"

    # For affiliates: scope to their own provisioned workspace, not the parent's
    if user["role"] == "affiliate" and user.get("affiliate_id"):
        aff = db.query(AffModel).filter(AffModel.id == user["affiliate_id"]).first()
        if aff:
            # affiliate_workspace_id = their own CRM workspace
            # workspace_id = their parent's workspace (fallback for legacy affiliates)
            ws_id = aff.affiliate_workspace_id or aff.workspace_id or ws_id
            org_role = "workspace_owner"

    ws = db.query(WsModel).filter(WsModel.id == ws_id).first()
    if ws and ws.org_id:
        org_id = ws.org_id

    token = create_access_token(
        user["username"], user["role"],
        workspace_id=ws_id,
        org_id=org_id,
        org_role=org_role,
        affiliate_id=user.get("affiliate_id"),
    )
    return {
        "access_token": token,
        "role": user["role"],
        "username": user["username"],
        "workspace_id": ws_id,
        "org_id": org_id,
        "org_role": org_role,
        "onboarding_complete": (bool(ws.onboarding_complete) if ws else True) if user["role"] == "affiliate" else True,
    }


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    """Return the current user's info."""
    return current_user


@app.get("/auth/config")
def auth_config():
    """Public endpoint — returns the bot username needed by the Telegram Login Widget."""
    from app.config import BOT_USERNAME, META_APP_ID
    return {"bot_username": BOT_USERNAME, "meta_app_id": META_APP_ID}


# ---------------------------------------------------------------------------
# Meta OAuth
# ---------------------------------------------------------------------------

@app.get("/auth/meta/connect")
def meta_oauth_connect(_=Depends(require_roles("developer", "admin"))):
    """Return the Meta OAuth URL for the admin to redirect to."""
    from app.config import META_APP_ID, APP_BASE_URL
    if not META_APP_ID:
        raise HTTPException(status_code=503, detail="META_APP_ID not configured on server")
    redirect_uri = urllib.parse.quote(f"{APP_BASE_URL}/auth/meta/callback", safe="")
    url = (
        f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=ads_read,ads_management"
        f"&state={_WORKSPACE_ID}"
    )
    return {"url": url}


@app.get("/auth/meta/callback")
def meta_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """
    Meta redirects here after the user approves.
    Exchanges the code for a token, saves it to the workspace, then redirects to the frontend.
    """
    from app.config import META_APP_ID, META_APP_SECRET, APP_BASE_URL
    from fastapi.responses import RedirectResponse

    if error:
        return RedirectResponse(f"{APP_BASE_URL}/settings?meta_error={urllib.parse.quote(error)}")

    workspace_id = int(state) if state.isdigit() else _WORKSPACE_ID

    # Exchange code for token
    params = urllib.parse.urlencode({
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "redirect_uri": f"{APP_BASE_URL}/auth/meta/callback",
        "code": code,
    })
    token_url = f"{GRAPH_BASE}/oauth/access_token?{params}"
    try:
        with urllib.request.urlopen(token_url, timeout=15) as r:
            token_data = json.loads(r.read())
    except Exception as e:
        logger.error("Meta token exchange failed: %s", e)
        return RedirectResponse(f"{APP_BASE_URL}/settings?meta_error=token_exchange_failed")

    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse(f"{APP_BASE_URL}/settings?meta_error=no_token")

    # Save token to workspace (account + pixel set separately via the picker)
    db_session = next(get_db())
    try:
        from app.database.models import Workspace
        ws = db_session.query(Workspace).filter(Workspace.id == workspace_id).first()
        if ws:
            ws.meta_access_token = access_token
            db_session.commit()
    finally:
        db_session.close()

    return RedirectResponse(f"{APP_BASE_URL}/settings?meta_connected=1#meta")


class MetaCredentialsRequest(BaseModel):
    access_token: Optional[str] = None
    ad_account_id: Optional[str] = None
    pixel_id: Optional[str] = None
    landing_page_url: Optional[str] = None


@app.patch("/settings/meta/credentials")
def meta_save_credentials(
    req: MetaCredentialsRequest,
    _=Depends(require_roles("developer", "admin")),
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
):
    """Save Meta credentials (access token, ad account, pixel) to the workspace."""
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if req.access_token and req.access_token.strip():
        ws.meta_access_token = req.access_token.strip()
    if req.ad_account_id and req.ad_account_id.strip():
        account_id = req.ad_account_id.strip()
        if not account_id.startswith("act_"):
            account_id = f"act_{account_id}"
        ws.meta_ad_account_id = account_id
    if req.pixel_id and req.pixel_id.strip():
        ws.meta_pixel_id = req.pixel_id.strip()
    if req.landing_page_url is not None:
        ws.landing_page_url = req.landing_page_url.strip() or None
    db.commit()
    return {"ok": True}


@app.get("/settings/meta/accounts")
def meta_list_accounts(
    _=Depends(require_roles("developer", "admin")),
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
):
    """Fetch the Meta ad accounts accessible with the saved token."""
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws or not ws.meta_access_token:
        raise HTTPException(status_code=400, detail="Meta credentials not saved yet.")
    params = urllib.parse.urlencode({"fields": "id,name,account_id", "access_token": ws.meta_access_token})
    url = f"{GRAPH_BASE}/me/adaccounts?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Meta API error: {e}")
    return {"accounts": data.get("data", [])}


@app.get("/settings/meta/status")
def meta_connection_status(
    _=Depends(require_roles("developer", "admin")),
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
):
    """Return current Meta connection status for the workspace."""
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    return {
        "connected": bool(ws and ws.meta_access_token),
        "ad_account_id": ws.meta_ad_account_id if ws else None,
        "pixel_id": ws.meta_pixel_id if ws else None,
        "landing_page_url": ws.landing_page_url if ws else None,
    }


# ---------------------------------------------------------------------------
# Telethon setup (phone OTP flow — no SSH required)
# ---------------------------------------------------------------------------

# In-progress auth sessions (workspace_id → TelegramClient mid-login)
_telethon_auth_sessions: dict[int, object] = {}


class TelethonConnectRequest(BaseModel):
    phone: str


class TelethonVerifyRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: str


@app.get("/settings/telethon/status")
def telethon_status(
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    from app.services.telethon_client import get_client
    return {"connected": get_client(workspace_id) is not None}


@app.get("/settings/forwarding/status")
def forwarding_status(
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
    db: Session = Depends(get_db),
):
    """Return signal forwarding health: operator running, source set, destinations configured."""
    from app.services.forwarding import get_all_destination_channels
    from app.config import SOURCE_CHANNEL_ID, BOT_TOKEN
    from app.database.models import Workspace

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    bot_token = (ws.bot_token if ws else None) or (BOT_TOKEN if workspace_id == 1 else None)

    source_configured = bool(SOURCE_CHANNEL_ID)
    destinations = get_all_destination_channels()
    destination_count = len(destinations)
    bot_configured = bool(bot_token)

    return {
        "bot_configured": bot_configured,
        "source_configured": source_configured,
        "destination_count": destination_count,
        "active": bot_configured and source_configured and destination_count > 0,
    }


@app.post("/settings/telethon/connect")
async def telethon_connect(
    req: TelethonConnectRequest,
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """Send OTP to the operator's phone to begin Telethon session setup."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise HTTPException(status_code=503, detail="TELEGRAM_API_ID/HASH not configured on server")

    # Clean up any stale pending session
    old = _telethon_auth_sessions.pop(workspace_id, None)
    if old:
        try:
            await old.disconnect()
        except Exception:
            pass

    client = TelegramClient(StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()
    result = await client.send_code_request(req.phone)
    _telethon_auth_sessions[workspace_id] = client
    return {"phone_code_hash": result.phone_code_hash}


@app.post("/settings/telethon/verify")
async def telethon_verify(
    req: TelethonVerifyRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """Submit OTP code, save StringSession to DB, and start the client."""
    from telethon.errors import SessionPasswordNeededError
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
    from app.database.models import Workspace

    client = _telethon_auth_sessions.get(workspace_id)
    if not client:
        raise HTTPException(status_code=400, detail="No pending session — call /connect first")

    try:
        await client.sign_in(req.phone, req.code, phone_code_hash=req.phone_code_hash)
    except SessionPasswordNeededError:
        raise HTTPException(status_code=422, detail="2FA password required — not yet supported via UI")

    session_str = client.session.save()
    await client.disconnect()
    _telethon_auth_sessions.pop(workspace_id, None)

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws.telethon_session = session_str
    db.commit()

    from app.services.telethon_client import start_workspace_client
    started = await start_workspace_client(workspace_id, session_str, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    return {"ok": started}


@app.post("/settings/telethon/disconnect")
async def telethon_disconnect(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """Stop the Telethon client and clear the saved session."""
    from app.database.models import Workspace
    from app.services.telethon_client import stop_workspace_client

    await stop_workspace_client(workspace_id)
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws:
        ws.telethon_session = None
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Bot token + webhook registration
# ---------------------------------------------------------------------------

class BotCredentialsRequest(BaseModel):
    bot_token: str
    webhook_secret: Optional[str] = None


@app.get("/settings/bot/status")
def bot_status(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """Return current bot token status and Telegram webhook info."""
    from app.database.models import Workspace
    from app.config import BOT_TOKEN, APP_BASE_URL

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    token = (ws.bot_token if ws and ws.bot_token else None) or (BOT_TOKEN if workspace_id == 1 else None)
    if not token:
        return {"has_token": False, "webhook_url": None, "webhook_active": False}

    webhook_url = None
    webhook_active = False
    try:
        url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
        with urllib.request.urlopen(url, timeout=5) as r:
            info = json.loads(r.read()).get("result", {})
        webhook_url = info.get("url") or None
        webhook_active = bool(webhook_url)
    except Exception:
        pass

    expected = f"{APP_BASE_URL}/webhook/{workspace_id}" if APP_BASE_URL else None
    return {
        "has_token": True,
        "webhook_url": webhook_url,
        "webhook_active": webhook_active,
        "webhook_correct": webhook_url == expected if expected and webhook_url else None,
        "expected_url": expected,
    }


@app.patch("/settings/bot/credentials")
def bot_save_credentials(
    req: BotCredentialsRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """Save bot token (and optional webhook secret) to the workspace."""
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws.bot_token = req.bot_token.strip()
    if req.webhook_secret is not None:
        ws.webhook_secret = req.webhook_secret.strip() or None
    db.commit()
    return {"ok": True}


@app.post("/settings/bot/register-webhook")
def bot_register_webhook(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """Call Telegram's setWebhook to point at /webhook/{workspace_id}."""
    from app.database.models import Workspace
    from app.config import BOT_TOKEN, APP_BASE_URL

    if not APP_BASE_URL:
        raise HTTPException(status_code=503, detail="APP_BASE_URL not set on server")

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    token = (ws.bot_token if ws and ws.bot_token else None) or (BOT_TOKEN if workspace_id == 1 else None)
    if not token:
        raise HTTPException(status_code=400, detail="No bot token configured for this workspace")

    webhook_url = f"{APP_BASE_URL}/webhook/{workspace_id}"
    payload: dict = {"url": webhook_url}
    effective_secret = (ws.webhook_secret if ws else None) or (WEBHOOK_SECRET if workspace_id == 1 else None)
    if effective_secret:
        payload["secret_token"] = effective_secret

    try:
        data = json.dumps(payload).encode()
        req_obj = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/setWebhook",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_obj, timeout=10) as r:
            result = json.loads(r.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Telegram API error: {e}")

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("description", "setWebhook failed"))

    return {"ok": True, "webhook_url": webhook_url}


@app.post("/settings/onboarding/complete")
def complete_onboarding(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("affiliate", "developer", "admin")),
):
    """Mark the affiliate workspace onboarding as complete."""
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws:
        ws.onboarding_complete = True
        db.commit()
    return {"ok": True}


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


@app.post("/auth/telegram")
@limiter.limit("10/minute")
def telegram_login(request: Request, req: TelegramAuthRequest, db: Session = Depends(get_db)):
    """Authenticate via Telegram Login Widget and return a JWT."""
    from app.config import BOT_TOKEN
    from app.database.models import TeamMember
    from app.auth import verify_telegram_auth, create_access_token

    if not verify_telegram_auth(req.dict(), BOT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid Telegram auth data")

    # Match by telegram_id (returning user) or by stored username (first login)
    # Login endpoints use workspace 1; workspace scoping in JWT comes from the member's workspace_id
    member = db.query(TeamMember).filter(
        TeamMember.telegram_id == req.id,
        TeamMember.is_active.is_(True),
    ).first()

    if not member and req.username:
        member = db.query(TeamMember).filter(
            TeamMember.username == req.username.lower(),
            TeamMember.auth_type == "telegram",
            TeamMember.is_active.is_(True),
        ).first()
        if member:
            member.telegram_id = req.id
            db.commit()

    if not member:
        raise HTTPException(status_code=403, detail="Not authorized. Ask your admin to add your Telegram account.")

    token = create_access_token(member.username, member.role, workspace_id=member.workspace_id)
    return {"access_token": token, "role": member.role, "username": member.display_name, "workspace_id": member.workspace_id}


@app.get("/stats/today")
def stats_today(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    return get_today_stats(db, workspace_id)


@app.get("/stats/by-source")
def stats_by_source(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    return get_stats_by_source(db, workspace_id)


@app.get("/stats/messages-per-day")
def stats_messages_per_day(db: Session = Depends(get_db), days: int = 30, workspace_id: int = Depends(get_workspace_id)):
    return get_messages_per_day(db, workspace_id, days=min(days, 365))


def _parse_date_range(from_date: Optional[str], to_date: Optional[str]):
    """Parse ISO date strings (YYYY-MM-DD) into UTC datetimes. Returns (from_dt, to_dt)."""
    from datetime import datetime as dt
    from_dt = dt.strptime(from_date, "%Y-%m-%d") if from_date else None
    to_dt = dt.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if to_date else None
    return from_dt, to_dt


@app.get("/analytics/overview")
def analytics_overview(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_overview(db, workspace_id, from_dt, to_dt)


@app.get("/analytics/conversions")
def analytics_conversions(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_conversion_metrics(db, workspace_id, from_dt, to_dt)


@app.get("/analytics/stage-distribution")
def analytics_stage_distribution(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    return get_stage_distribution(db, workspace_id)


@app.get("/analytics/hourly-heatmap")
def analytics_hourly_heatmap(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_hourly_heatmap(db, workspace_id, from_dt, to_dt)


@app.get("/analytics/day-of-week")
def analytics_day_of_week(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_day_of_week(db, workspace_id, from_dt, to_dt)


@app.get("/analytics/leads-over-time")
def analytics_leads_over_time(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    days: int = 30, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_leads_over_time(db, workspace_id, from_dt, to_dt, days=min(days, 365))


@app.get("/analytics/campaigns")
def analytics_campaigns(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_campaign_performance(db, workspace_id, from_dt, to_dt)


@app.get("/analytics/campaigns/flags")
def analytics_campaign_flags(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    return get_underperforming_campaigns(db, workspace_id)


@app.get("/analytics/campaigns/creatives")
def analytics_creatives(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_best_performing_creatives(db, workspace_id, from_dt, to_dt)


@app.get("/analytics/alerts")
def analytics_alerts(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    return get_campaign_alerts(db, workspace_id)


@app.post("/analytics/campaigns/pull")
def trigger_meta_pull(
    for_date: Optional[str] = None,
    days: int = 1,
    _=Depends(require_roles("developer", "admin")),
):
    """
    Manually trigger a Meta Marketing API pull.
    - ?for_date=YYYY-MM-DD  pull a specific date
    - ?days=14              backfill last N days (max 90)
    """
    from datetime import date as date_type, timedelta
    from app.services.meta_api import pull_campaign_insights

    days = min(days, 90)

    if for_date:
        try:
            start = date_type.fromisoformat(for_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="for_date must be YYYY-MM-DD")
        dates = [start]
    else:
        today = date_type.today()
        dates = [today - timedelta(days=i) for i in range(1, days + 1)]

    results = []
    for d in dates:
        result = pull_campaign_insights(for_date=d)
        results.append(result)
        if result and not result.get("ok"):
            break

    total_upserted = sum(r.get("rows_upserted", 0) for r in results if r)
    errors = [r for r in results if r and not r.get("ok")]
    return {
        "ok": len(errors) == 0,
        "dates_pulled": len(results),
        "total_rows_upserted": total_upserted,
        "errors": errors or None,
        "detail": results,
    }


# ---------------------------------------------------------------------------
# Campaign registry — tracked URL generator
# ---------------------------------------------------------------------------

class CreateCampaignRequest(BaseModel):
    name: str
    meta_campaign_id: Optional[str] = None


@app.post("/campaigns")
def create_campaign(
    req: CreateCampaignRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """Create a tracked campaign and return the Telegram deep link."""
    import uuid
    from app.database.models import Campaign, Workspace
    from app.config import BOT_USERNAME

    source_tag = "cmp_" + uuid.uuid4().hex[:8]
    campaign = Campaign(
        source_tag=source_tag,
        name=req.name.strip(),
        meta_campaign_id=req.meta_campaign_id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    landing_base = (ws.landing_page_url or "").strip().rstrip("/") if ws else ""

    link = f"https://t.me/{BOT_USERNAME}?start={source_tag}" if BOT_USERNAME else None
    landing_url = f"{landing_base}?src={source_tag}" if landing_base else None
    return {
        "id": campaign.id,
        "source_tag": source_tag,
        "name": campaign.name,
        "meta_campaign_id": campaign.meta_campaign_id,
        "link": link,
        "landing_url": landing_url,
        "leads": 0,
        "deposits": 0,
        "created_at": campaign.created_at.isoformat(),
    }


@app.get("/campaigns")
def list_campaigns(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """List all tracked campaigns with their attribution stats."""
    from app.database.models import Campaign, Contact, StageHistory, Workspace
    from app.config import BOT_USERNAME

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    landing_base = (ws.landing_page_url or "").strip().rstrip("/") if ws else ""

    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    result = []
    for c in campaigns:
        leads = db.query(Contact).filter(Contact.source == c.source_tag).count()
        deposits = (
            db.query(StageHistory)
            .join(Contact, Contact.id == StageHistory.contact_id)
            .filter(Contact.source == c.source_tag, StageHistory.to_stage == 7)
            .count()
        )
        link = f"https://t.me/{BOT_USERNAME}?start={c.source_tag}" if BOT_USERNAME else None
        landing_url = f"{landing_base}?src={c.source_tag}" if landing_base else None
        result.append({
            "id": c.id,
            "source_tag": c.source_tag,
            "name": c.name,
            "meta_campaign_id": c.meta_campaign_id,
            "link": link,
            "landing_url": landing_url,
            "leads": leads,
            "deposits": deposits,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat(),
        })
    return result


@app.get("/health")
def health():
    """Health check for deployment."""
    return {"status": "ok"}


# -----------------------------
# CRM Phase 1 API endpoints
# -----------------------------


class SendMessageRequest(BaseModel):
    contact_id: conint(ge=1)
    message: str


class ManualStageRequest(BaseModel):
    stage: conint(ge=1, le=8)


class NotesRequest(BaseModel):
    notes: str


@app.get("/contacts")
def contacts_list(include_noise: bool = False, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    """List contacts. Noise contacts are excluded by default; pass ?include_noise=true to include them."""
    return get_contacts(db, workspace_id=workspace_id, include_noise=include_noise)


@app.get("/contacts/{contact_id}/messages")
def contacts_messages(contact_id: int, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    """Return full chat history (inbound + outbound) for a contact."""
    if not db.query(User).filter(User.id == contact_id, User.workspace_id == workspace_id).first():
        raise HTTPException(status_code=404, detail="contact not found")
    return get_contact_messages(db, contact_id)


@app.post("/send-message")
def send_message_to_contact(
    req: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Used exclusively for quick-reply template sends from the dashboard.
    Operator's day-to-day conversations happen natively in Telegram; the Telethon
    outgoing listener detects those messages and advances stages automatically.

    - Telethon path: listener fires after send and calls handle_outbound there.
    - Bot API fallback: listener won't fire, so handle_outbound is called here.
    """
    workspace_id: int = current_user.get("workspace_id", 1)
    contact = db.query(User).filter(User.id == req.contact_id, User.workspace_id == workspace_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")

    from app.services.telethon_client import send_as_operator_sync, get_client
    used_telethon = False
    if get_client(workspace_id):
        ok = send_as_operator_sync(contact.id, req.message, workspace_id)
        used_telethon = ok
    else:
        ok = send_message(contact.id, req.message, workspace_id)
    if not ok:
        raise HTTPException(status_code=502, detail="telegram send failed")

    # Only call handle_outbound directly when using the bot API fallback.
    # When Telethon sent the message, the outgoing listener handles it instead
    # (avoids double stage detection).
    if not used_telethon:
        handle_outbound(db, req.contact_id, req.message)

    return {"ok": True}


@app.post("/contacts/{contact_id}/stage")
def set_contact_stage(contact_id: int, req: ManualStageRequest, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    """Manually override a contact stage."""
    contact = db.query(User).filter(User.id == contact_id, User.workspace_id == workspace_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")

    # Initialize missing defaults (for old DB rows)
    if contact.current_stage is None or contact.stage_entered_at is None:
        from datetime import datetime

        now = datetime.utcnow()
        if contact.current_stage is None:
            contact.current_stage = 1
        if contact.stage_entered_at is None:
            contact.stage_entered_at = now
        db.commit()

    set_stage_manual(contact, req.stage)

    # Cancel stale follow-ups and schedule new ones for the new stage
    from app.services.scheduler import schedule_follow_ups
    schedule_follow_ups(contact_id, req.stage, contact.stage_entered_at)

    return {"ok": True}


@app.post("/contacts/{contact_id}/notes")
def update_contact_notes(contact_id: int, req: NotesRequest, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    """Save free-text notes for a contact."""
    contact = db.query(User).filter(User.id == contact_id, User.workspace_id == workspace_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.notes = req.notes
    db.commit()
    return {"ok": True}


@app.post("/contacts/{contact_id}/escalate")
def escalate_contact(contact_id: int, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    """Flag a contact as escalated."""
    from datetime import datetime
    contact = db.query(User).filter(User.id == contact_id, User.workspace_id == workspace_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.escalated = True
    contact.escalated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.post("/contacts/{contact_id}/deposit-confirm")
def confirm_deposit(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin", "operator", "vip_manager")),
):
    """Mark deposit as confirmed and auto-promote contact to stage 8."""
    from datetime import datetime, date
    workspace_id: int = current_user.get("workspace_id", 1)
    contact = db.query(User).filter(User.id == contact_id, User.workspace_id == workspace_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.deposit_confirmed = True
    contact.deposit_date = date.today()
    if (contact.current_stage or 1) < 8:
        set_stage_manual(contact, 8, moved_by="system", db=db)
        from app.services.scheduler import schedule_follow_ups
        schedule_follow_ups(contact_id, 8, datetime.utcnow())
    else:
        db.commit()
    return {"ok": True}


@app.post("/contacts/{contact_id}/noise")
def mark_as_noise(contact_id: int, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    """Mark a contact as noise (spam/unrelated). Removes them from the lead pipeline."""
    contact = db.query(User).filter(User.id == contact_id, User.workspace_id == workspace_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.classification = "noise"
    contact.current_stage = None
    contact.stage_entered_at = None
    db.commit()
    from app.services.scheduler import cancel_follow_ups
    cancel_follow_ups(contact_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Phase 5: Member Activity Monitor
# ---------------------------------------------------------------------------

class ReengageRequest(BaseModel):
    message: Optional[str] = None


@app.get("/members")
def list_members(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin", "vip_manager")),
):
    """VIP member list (Stage 7/8) with activity status. Accessible to vip_manager, admin, developer."""
    from app.services.member_activity import get_vip_members
    workspace_id: int = current_user.get("workspace_id", 1)
    return get_vip_members(db, workspace_id)


@app.post("/members/{contact_id}/reengage")
def reengage_member(
    contact_id: int,
    req: ReengageRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin", "vip_manager")),
):
    """Send a one-tap re-engagement message to a VIP member."""
    workspace_id: int = current_user.get("workspace_id", 1)
    contact = db.query(User).filter(User.id == contact_id, User.workspace_id == workspace_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    if contact.current_stage not in (7, 8):
        raise HTTPException(status_code=400, detail="contact is not a VIP member")

    from app.services.member_activity import send_reengage_message
    ok = send_reengage_message(contact_id, req.message)
    if not ok:
        raise HTTPException(status_code=502, detail="telegram send failed")
    return {"ok": True}


@app.post("/members/refresh-activity")
def trigger_activity_refresh(
    _=Depends(require_roles("developer", "admin")),
):
    """Manually trigger member activity status refresh (developer/admin only)."""
    from app.services.member_activity import refresh_activity_statuses
    refresh_activity_statuses()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Phase 6: Affiliate Dashboard
# ---------------------------------------------------------------------------

class CreateAffiliateRequest(BaseModel):
    name: str
    username: Optional[str] = None
    commission_rate: float = 15.0


class UpdateLotsRequest(BaseModel):
    lots_traded: float


class UpdateChecklistRequest(BaseModel):
    esim_done: Optional[bool] = None
    free_channel_id: Optional[str] = None
    free_channel_members: Optional[int] = None
    bot_setup_done: Optional[bool] = None
    vip_channel_id: Optional[str] = None
    vip_channel_members: Optional[int] = None
    tutorial_channel_id: Optional[str] = None
    tutorial_channel_members: Optional[int] = None
    sales_scripts_done: Optional[bool] = None
    ib_profile_id: Optional[str] = None
    ads_live: Optional[bool] = None
    pixel_setup_done: Optional[bool] = None


@app.get("/affiliates/performance")
def affiliate_performance(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """Affiliate leaderboard with attributed leads, deposits, and commission earned."""
    return get_affiliate_performance(db)


@app.get("/affiliates")
def list_affiliates(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """List all affiliates (active and inactive)."""
    from app.database.models import Affiliate
    from app.config import BOT_USERNAME
    affiliates = db.query(Affiliate).order_by(Affiliate.created_at.desc()).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "username": a.username,
            "referral_tag": a.referral_tag,
            "referral_link": f"https://t.me/{BOT_USERNAME}?start={a.referral_tag}" if BOT_USERNAME else None,
            "commission_rate": a.commission_rate,
            "lots_traded": a.lots_traded,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "affiliate_workspace_id": a.affiliate_workspace_id,
        }
        for a in affiliates
    ]


@app.post("/affiliates")
def create_affiliate(
    req: CreateAffiliateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """
    Register a new affiliate, generate their credentials, and auto-provision
    a child CRM workspace for them within the caller's org.
    Callable by org_owner (Walid creating affiliates) and workspace_owner
    (affiliate creating their own sub-affiliates).
    """
    import uuid
    from app.database.models import Affiliate, Workspace
    from app.database import seed_workspace_defaults
    from app.config import BOT_USERNAME
    from app.auth import generate_password, hash_password

    referral_tag = "ref_" + uuid.uuid4().hex[:8]
    login_username = "aff_" + uuid.uuid4().hex[:8]
    plain_password = generate_password()

    # Provision a child workspace in the caller's org
    caller_org_id = current_user.get("org_id", 1)
    caller_ws_id = current_user.get("workspace_id", 1)
    parent_ws = db.query(Workspace).filter(Workspace.id == caller_ws_id).first()
    root_ws_id = (parent_ws.root_workspace_id or caller_ws_id) if parent_ws else caller_ws_id

    aff_workspace = Workspace(
        name=req.name.strip(),
        org_id=caller_org_id,
        parent_workspace_id=caller_ws_id,
        root_workspace_id=root_ws_id,
        workspace_role="affiliate",
    )
    db.add(aff_workspace)
    db.flush()  # get aff_workspace.id without committing yet

    affiliate = Affiliate(
        workspace_id=caller_ws_id,  # the parent (Walid's) workspace
        name=req.name.strip(),
        username=req.username.strip() if req.username else None,
        referral_tag=referral_tag,
        commission_rate=req.commission_rate,
        login_username=login_username,
        login_password_hash=hash_password(plain_password),
        affiliate_workspace_id=aff_workspace.id,
    )
    db.add(affiliate)
    db.commit()
    db.refresh(affiliate)
    db.refresh(aff_workspace)

    seed_workspace_defaults(aff_workspace.id, db)

    # Fire welcome DM in background — non-blocking
    affiliate_id = affiliate.id
    import threading
    threading.Thread(
        target=lambda: __import__(
            "app.services.affiliate_automation", fromlist=["send_affiliate_welcome"]
        ).send_affiliate_welcome(affiliate_id),
        daemon=True,
    ).start()

    link = f"https://t.me/{BOT_USERNAME}?start={referral_tag}" if BOT_USERNAME else None
    return {
        "id": affiliate.id,
        "name": affiliate.name,
        "username": affiliate.username,
        "referral_tag": referral_tag,
        "referral_link": link,
        "commission_rate": affiliate.commission_rate,
        "lots_traded": affiliate.lots_traded,
        "is_active": affiliate.is_active,
        "created_at": affiliate.created_at.isoformat(),
        "affiliate_workspace_id": aff_workspace.id,
        # Credentials — shown once at creation
        "login_username": login_username,
        "login_password": plain_password,
        # Stats defaults (no activity yet)
        "leads": 0, "deposits": 0, "conversion_rate": 0, "commission_earned": 0,
        # Checklist defaults
        "esim_done": False, "free_channel_id": None, "free_channel_members": 0,
        "bot_setup_done": False, "vip_channel_id": None, "vip_channel_members": 0,
        "tutorial_channel_id": None, "tutorial_channel_members": 0,
        "sales_scripts_done": False, "ib_profile_id": None,
        "ads_live": False, "pixel_setup_done": False,
    }


@app.patch("/affiliates/{affiliate_id}/lots")
def update_affiliate_lots(
    affiliate_id: int,
    req: UpdateLotsRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """Update the manually-tracked lots traded for an affiliate (triggers commission recalc)."""
    from app.database.models import Affiliate
    affiliate = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
    if not affiliate:
        raise HTTPException(status_code=404, detail="affiliate not found")
    affiliate.lots_traded = req.lots_traded
    db.commit()
    return {"ok": True, "lots_traded": affiliate.lots_traded, "commission_earned": round(affiliate.lots_traded * affiliate.commission_rate, 2)}


@app.delete("/affiliates/{affiliate_id}")
def delete_affiliate(
    affiliate_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """Permanently delete an affiliate and their login credentials."""
    from app.database.models import Affiliate
    affiliate = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
    if not affiliate:
        raise HTTPException(status_code=404, detail="affiliate not found")
    db.delete(affiliate)
    db.commit()
    return {"ok": True}


@app.patch("/affiliates/{affiliate_id}/checklist")
def update_affiliate_checklist(
    affiliate_id: int,
    req: UpdateChecklistRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """Update onboarding checklist fields for an affiliate."""
    from app.database.models import Affiliate
    affiliate = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
    if not affiliate:
        raise HTTPException(status_code=404, detail="affiliate not found")
    for field, value in req.dict(exclude_none=True).items():
        setattr(affiliate, field, value)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Affiliate self-service endpoints (role: affiliate)
# ---------------------------------------------------------------------------

@app.get("/affiliate/me")
def affiliate_me(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_affiliate),
):
    """Return the authenticated affiliate's full profile, stats, and checklist."""
    from app.database.models import Affiliate, Contact, StageHistory
    from app.config import BOT_USERNAME
    from sqlalchemy import func

    affiliate_id = current_user["affiliate_id"]
    aff = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
    if not aff:
        raise HTTPException(status_code=404, detail="affiliate not found")

    leads = (
        db.query(func.count(Contact.id))
        .filter(Contact.source == aff.referral_tag, Contact.classification != "noise")
        .scalar() or 0
    )
    deposits = (
        db.query(func.count(func.distinct(StageHistory.contact_id)))
        .join(Contact, Contact.id == StageHistory.contact_id)
        .filter(Contact.source == aff.referral_tag, StageHistory.to_stage == 7)
        .scalar() or 0
    )
    conversion_rate = round(deposits / leads * 100, 1) if leads > 0 else 0.0
    commission_earned = round(aff.lots_traded * aff.commission_rate, 2)
    referral_link = (
        f"https://t.me/{BOT_USERNAME}?start={aff.referral_tag}" if BOT_USERNAME else None
    )

    return {
        "id": aff.id,
        "name": aff.name,
        "username": aff.username,
        "referral_tag": aff.referral_tag,
        "referral_link": referral_link,
        "leads": leads,
        "deposits": deposits,
        "conversion_rate": conversion_rate,
        "lots_traded": aff.lots_traded,
        "commission_rate": aff.commission_rate,
        "commission_earned": commission_earned,
        # Checklist
        "esim_done": bool(aff.esim_done),
        "free_channel_id": aff.free_channel_id,
        "free_channel_members": aff.free_channel_members or 0,
        "bot_setup_done": bool(aff.bot_setup_done),
        "vip_channel_id": aff.vip_channel_id,
        "vip_channel_members": aff.vip_channel_members or 0,
        "tutorial_channel_id": aff.tutorial_channel_id,
        "tutorial_channel_members": aff.tutorial_channel_members or 0,
        "sales_scripts_done": bool(aff.sales_scripts_done),
        "ib_profile_id": aff.ib_profile_id,
        "ads_live": bool(aff.ads_live),
        "pixel_setup_done": bool(aff.pixel_setup_done),
    }


@app.patch("/affiliate/me/checklist")
def affiliate_update_checklist(
    req: UpdateChecklistRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_affiliate),
):
    """Affiliate updates their own onboarding checklist."""
    from app.database.models import Affiliate
    aff = db.query(Affiliate).filter(Affiliate.id == current_user["affiliate_id"]).first()
    if not aff:
        raise HTTPException(status_code=404, detail="affiliate not found")
    for field, value in req.dict(exclude_none=True).items():
        setattr(aff, field, value)
    db.commit()
    return {"ok": True}


@app.get("/affiliates/pending-channels")
def list_pending_channels(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """List Telegram channels the bot was added to but not yet linked to any affiliate."""
    rows = db.query(PendingChannel).order_by(PendingChannel.detected_at.desc()).all()
    return [
        {
            "id": r.id,
            "chat_id": r.chat_id,
            "title": r.title,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        }
        for r in rows
    ]


class LinkChannelRequest(BaseModel):
    chat_id: str
    channel_type: str   # "free" | "vip" | "tutorial"


@app.post("/affiliates/{affiliate_id}/link-channel")
def link_channel_to_affiliate(
    affiliate_id: int,
    req: LinkChannelRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """
    Link a pending channel to an affiliate as free/vip/tutorial.
    Removes it from the pending list and sets the channel ID + marks bot_setup_done.
    """
    from app.database.models import Affiliate
    if req.channel_type not in ("free", "vip", "tutorial"):
        raise HTTPException(status_code=400, detail="channel_type must be free, vip, or tutorial")

    affiliate = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
    if not affiliate:
        raise HTTPException(status_code=404, detail="affiliate not found")

    field_map = {
        "free": "free_channel_id",
        "vip": "vip_channel_id",
        "tutorial": "tutorial_channel_id",
    }
    setattr(affiliate, field_map[req.channel_type], req.chat_id)

    # Remove from pending list
    db.query(PendingChannel).filter(PendingChannel.chat_id == req.chat_id).delete()

    # Kick off a member count fetch for the newly linked channel
    db.commit()

    loop = asyncio.get_running_loop()
    chat_id_str = req.chat_id
    channel_type = req.channel_type
    aff_id = affiliate_id
    loop.run_in_executor(None, lambda: _sync_single_channel(aff_id, channel_type, chat_id_str))

    return {"ok": True, "channel_type": req.channel_type, "chat_id": req.chat_id}


def _sync_single_channel(affiliate_id: int, channel_type: str, chat_id: str) -> None:
    """Fetch member count for a single just-linked channel and persist it."""
    from app.services.affiliate_automation import get_chat_member_count
    from app.database.models import Affiliate
    count = get_chat_member_count(chat_id)
    if count is None:
        return
    db = SessionLocal()
    try:
        aff = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
        if aff:
            field = f"{channel_type}_channel_members"
            setattr(aff, field, count)
            db.commit()
    finally:
        db.close()


@app.delete("/affiliates/pending-channels/{pending_id}")
def dismiss_pending_channel(
    pending_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """Dismiss a pending channel without linking it to any affiliate."""
    row = db.query(PendingChannel).filter(PendingChannel.id == pending_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="pending channel not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.post("/affiliates/sync-channels")
def trigger_channel_sync(
    _=Depends(require_roles("developer", "admin")),
):
    """Manually trigger a channel member count sync (runs in background)."""
    import threading
    from app.services.affiliate_automation import sync_channel_member_counts
    threading.Thread(target=sync_channel_member_counts, daemon=True).start()
    return {"ok": True, "message": "channel sync started"}


@app.post("/contacts/{contact_id}/affiliate")
def toggle_affiliate(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin")),
):
    """Toggle affiliate status — developer and admin only."""
    from app.services.classifier import classify_contact
    contact = db.query(User).filter(User.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.is_affiliate = not contact.is_affiliate
    contact.classification = classify_contact(db, contact_id, contact.source, existing=contact)
    db.commit()
    return {"ok": True, "is_affiliate": contact.is_affiliate}


# ---------------------------------------------------------------------------
# Settings — Team management
# ---------------------------------------------------------------------------

_ASSIGNABLE_ROLES = {"operator", "vip_manager", "admin"}


class CreateTeamMemberRequest(BaseModel):
    display_name: str
    username: str
    role: str
    auth_type: str = "telegram"  # "telegram" | "password"


class UpdateTeamMemberRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@app.get("/settings/team")
def settings_list_team(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import TeamMember
    rows = (
        db.query(TeamMember)
        .filter(TeamMember.workspace_id == workspace_id)
        .order_by(TeamMember.created_at)
        .all()
    )
    return [
        {
            "id": r.id,
            "display_name": r.display_name,
            "username": r.username,
            "role": r.role,
            "is_active": r.is_active,
            "auth_type": r.auth_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@app.post("/settings/team", status_code=201)
def settings_create_team_member(
    req: CreateTeamMemberRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import TeamMember
    from app.auth import generate_password, hash_password

    if req.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of: {', '.join(sorted(_ASSIGNABLE_ROLES))}")
    if req.auth_type not in ("telegram", "password"):
        raise HTTPException(status_code=400, detail="auth_type must be 'telegram' or 'password'")

    username = req.username.strip().lstrip("@").lower()
    existing = db.query(TeamMember).filter(TeamMember.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="username already taken")

    plain_password = None
    if req.auth_type == "telegram":
        pw_hash = hash_password(secrets.token_hex(32))
    else:
        plain_password = generate_password()
        pw_hash = hash_password(plain_password)

    member = TeamMember(
        workspace_id=workspace_id,
        display_name=req.display_name.strip(),
        username=username,
        password_hash=pw_hash,
        role=req.role,
        auth_type=req.auth_type,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    result = {
        "id": member.id,
        "display_name": member.display_name,
        "username": member.username,
        "role": member.role,
        "is_active": member.is_active,
        "auth_type": member.auth_type,
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }
    if plain_password:
        result["password"] = plain_password
    return result


@app.patch("/settings/team/{member_id}")
def settings_update_team_member(
    member_id: int,
    req: UpdateTeamMemberRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import TeamMember
    member = db.query(TeamMember).filter(
        TeamMember.id == member_id, TeamMember.workspace_id == workspace_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="team member not found")
    if req.role is not None and req.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of: {', '.join(sorted(_ASSIGNABLE_ROLES))}")
    if req.display_name is not None:
        member.display_name = req.display_name.strip()
    if req.role is not None:
        member.role = req.role
    if req.is_active is not None:
        member.is_active = req.is_active
    db.commit()
    return {
        "id": member.id,
        "display_name": member.display_name,
        "username": member.username,
        "role": member.role,
        "is_active": member.is_active,
    }


@app.post("/settings/team/{member_id}/reset-password")
def settings_reset_team_password(
    member_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import TeamMember
    from app.auth import generate_password, hash_password
    member = db.query(TeamMember).filter(
        TeamMember.id == member_id, TeamMember.workspace_id == workspace_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="team member not found")
    plain_password = generate_password()
    member.password_hash = hash_password(plain_password)
    db.commit()
    return {"ok": True, "password": plain_password}


@app.delete("/settings/team/{member_id}")
def settings_delete_team_member(
    member_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import TeamMember
    member = db.query(TeamMember).filter(
        TeamMember.id == member_id, TeamMember.workspace_id == workspace_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="team member not found")
    db.delete(member)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings — keywords, follow-up templates, quick replies, stage labels
# ---------------------------------------------------------------------------

SETTINGS_ROLES = Depends(require_roles("developer", "admin"))


class KeywordCreateRequest(BaseModel):
    keyword: str
    target_stage: conint(ge=1, le=8)


class KeywordUpdateRequest(BaseModel):
    keyword: Optional[str] = None
    target_stage: Optional[conint(ge=1, le=8)] = None
    is_active: Optional[bool] = None


class FollowUpUpdateRequest(BaseModel):
    message_text: str


class QuickReplyCreateRequest(BaseModel):
    stage_num: conint(ge=1, le=8)
    label: str
    text: str
    sort_order: int = 0


class QuickReplyUpdateRequest(BaseModel):
    label: Optional[str] = None
    text: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class StageLabelUpdateRequest(BaseModel):
    label: str


# --- Keywords ---

@app.get("/settings/keywords")
def settings_list_keywords(db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageKeyword
    rows = (
        db.query(StageKeyword)
        .filter(StageKeyword.workspace_id == workspace_id)
        .order_by(StageKeyword.target_stage, StageKeyword.id)
        .all()
    )
    return [
        {"id": r.id, "keyword": r.keyword, "target_stage": r.target_stage, "is_active": r.is_active}
        for r in rows
    ]


@app.post("/settings/keywords", status_code=201)
def settings_create_keyword(req: KeywordCreateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageKeyword
    kw = StageKeyword(workspace_id=workspace_id, keyword=req.keyword.strip(), target_stage=req.target_stage)
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return {"id": kw.id, "keyword": kw.keyword, "target_stage": kw.target_stage, "is_active": kw.is_active}


@app.patch("/settings/keywords/{kw_id}")
def settings_update_keyword(kw_id: int, req: KeywordUpdateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageKeyword
    kw = db.query(StageKeyword).filter(StageKeyword.id == kw_id, StageKeyword.workspace_id == workspace_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="keyword not found")
    if req.keyword is not None:
        kw.keyword = req.keyword.strip()
    if req.target_stage is not None:
        kw.target_stage = req.target_stage
    if req.is_active is not None:
        kw.is_active = req.is_active
    db.commit()
    return {"id": kw.id, "keyword": kw.keyword, "target_stage": kw.target_stage, "is_active": kw.is_active}


@app.delete("/settings/keywords/{kw_id}")
def settings_delete_keyword(kw_id: int, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageKeyword
    kw = db.query(StageKeyword).filter(StageKeyword.id == kw_id, StageKeyword.workspace_id == workspace_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="keyword not found")
    db.delete(kw)
    db.commit()
    return {"ok": True}


# --- Follow-up Templates ---

@app.get("/settings/follow-up-templates")
def settings_list_templates(db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import FollowUpTemplate
    rows = (
        db.query(FollowUpTemplate)
        .filter(FollowUpTemplate.workspace_id == workspace_id)
        .order_by(FollowUpTemplate.stage, FollowUpTemplate.sequence_num)
        .all()
    )
    return [
        {"id": r.id, "stage": r.stage, "sequence_num": r.sequence_num, "message_text": r.message_text}
        for r in rows
    ]


@app.patch("/settings/follow-up-templates/{tmpl_id}")
def settings_update_template(tmpl_id: int, req: FollowUpUpdateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import FollowUpTemplate
    tmpl = db.query(FollowUpTemplate).filter(FollowUpTemplate.id == tmpl_id, FollowUpTemplate.workspace_id == workspace_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="template not found")
    tmpl.message_text = req.message_text.strip()
    db.commit()
    return {"id": tmpl.id, "stage": tmpl.stage, "sequence_num": tmpl.sequence_num, "message_text": tmpl.message_text}


# --- Quick Replies ---

@app.get("/settings/quick-replies")
def settings_list_quick_replies(db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import QuickReply
    rows = (
        db.query(QuickReply)
        .filter(QuickReply.workspace_id == workspace_id)
        .order_by(QuickReply.stage_num, QuickReply.sort_order, QuickReply.id)
        .all()
    )
    return [
        {"id": r.id, "stage_num": r.stage_num, "label": r.label, "text": r.text, "sort_order": r.sort_order, "is_active": r.is_active}
        for r in rows
    ]


@app.post("/settings/quick-replies", status_code=201)
def settings_create_quick_reply(req: QuickReplyCreateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import QuickReply
    qr = QuickReply(workspace_id=workspace_id, stage_num=req.stage_num, label=req.label.strip(), text=req.text.strip(), sort_order=req.sort_order)
    db.add(qr)
    db.commit()
    db.refresh(qr)
    return {"id": qr.id, "stage_num": qr.stage_num, "label": qr.label, "text": qr.text, "sort_order": qr.sort_order, "is_active": qr.is_active}


@app.patch("/settings/quick-replies/{qr_id}")
def settings_update_quick_reply(qr_id: int, req: QuickReplyUpdateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import QuickReply
    qr = db.query(QuickReply).filter(QuickReply.id == qr_id, QuickReply.workspace_id == workspace_id).first()
    if not qr:
        raise HTTPException(status_code=404, detail="quick reply not found")
    if req.label is not None:
        qr.label = req.label.strip()
    if req.text is not None:
        qr.text = req.text.strip()
    if req.sort_order is not None:
        qr.sort_order = req.sort_order
    if req.is_active is not None:
        qr.is_active = req.is_active
    db.commit()
    return {"id": qr.id, "stage_num": qr.stage_num, "label": qr.label, "text": qr.text, "sort_order": qr.sort_order, "is_active": qr.is_active}


@app.delete("/settings/quick-replies/{qr_id}")
def settings_delete_quick_reply(qr_id: int, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import QuickReply
    qr = db.query(QuickReply).filter(QuickReply.id == qr_id, QuickReply.workspace_id == workspace_id).first()
    if not qr:
        raise HTTPException(status_code=404, detail="quick reply not found")
    db.delete(qr)
    db.commit()
    return {"ok": True}


# --- Stage Labels ---

@app.get("/settings/stage-labels")
def settings_list_stage_labels(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageLabel
    rows = (
        db.query(StageLabel)
        .filter(StageLabel.workspace_id == workspace_id)
        .order_by(StageLabel.stage_num)
        .all()
    )
    return [{"id": r.id, "stage_num": r.stage_num, "label": r.label} for r in rows]


@app.patch("/settings/stage-labels/{label_id}")
def settings_update_stage_label(label_id: int, req: StageLabelUpdateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageLabel
    lbl = db.query(StageLabel).filter(StageLabel.id == label_id, StageLabel.workspace_id == workspace_id).first()
    if not lbl:
        raise HTTPException(status_code=404, detail="stage label not found")
    lbl.label = req.label.strip()
    db.commit()
    return {"id": lbl.id, "stage_num": lbl.stage_num, "label": lbl.label}


# ---------------------------------------------------------------------------
# Frontend static files (React dashboard)
# ---------------------------------------------------------------------------

if os.path.isdir(_FRONTEND_DIST):
    _assets_dir = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        """Serve the React SPA for any route not matched by the API."""
        return FileResponse(_SPA_INDEX)
