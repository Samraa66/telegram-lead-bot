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
from fastapi.responses import FileResponse, JSONResponse as _JSONResponse
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


# SlowAPI per-route limiter. key_func reads CF-Connecting-IP / X-Forwarded-For
# first so per-IP buckets reflect the real client when we're behind Cloudflare.
def _slowapi_key(request: Request) -> str:
    from app.services.net import client_ip as _client_ip
    return _client_ip(request) or get_remote_address(request) or "unknown"

limiter = Limiter(key_func=_slowapi_key)

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
_API_PASS_THROUGH = ("/assets/", "/webhook", "/auth/", "/health", "/api/", "/.well-known/")

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


# Content Security Policy — strict-ish, allowing Telegram login widget + Recharts inline styles.
# 'unsafe-inline' on style-src is required by recharts/Tailwind runtime; script-src stays tight.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://telegram.org https://oauth.telegram.org; "
    "frame-src https://oauth.telegram.org https://telegram.org; "
    "img-src 'self' data: https://t.me https://*.telegram.org; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "connect-src 'self' https://telelytics.org https://api.telegram.org https://graph.facebook.com; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# ---------------------------------------------------------------------------
# Global per-IP rate limit — catches scrapers and anything not explicitly limited.
# Per-route @limiter.limit decorators stay tighter for sensitive endpoints.
# ---------------------------------------------------------------------------
from collections import deque
import time as _time
from threading import Lock as _Lock

_GLOBAL_RPM_CAP = 240             # requests per minute per IP
_GLOBAL_WINDOW = 60.0             # seconds
_global_buckets: dict[str, deque] = {}
_global_buckets_lock = _Lock()
# Don't gate the webhook (Telegram itself bursts) or static assets
_GLOBAL_LIMIT_SKIP_PREFIXES = ("/webhook", "/assets/")


@app.middleware("http")
async def global_rate_limit(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in _GLOBAL_LIMIT_SKIP_PREFIXES):
        return await call_next(request)

    from app.services.net import client_ip as _client_ip
    ip = _client_ip(request) or "unknown"
    now = _time.monotonic()
    cutoff = now - _GLOBAL_WINDOW
    with _global_buckets_lock:
        bucket = _global_buckets.setdefault(ip, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _GLOBAL_RPM_CAP:
            return _JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Slow down."},
                headers={"Retry-After": "60"},
            )
        bucket.append(now)
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
    # HSTS — only over HTTPS. 1 year + subdomains. Skip "preload" until we're sure.
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = _CSP
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
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Telegram-Bot-Api-Secret-Token"],
    max_age=600,
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
                        db.add(PendingChannel(chat_id=chat_id, title=chat_title, workspace_id=workspace_id))
                        db.commit()
                        logger.info("Bot added to channel %s (%s) for ws=%s — stored as pending", chat_title, chat_id, workspace_id)
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
    """
    Legacy single-workspace webhook (workspace 1). Kept for backward compatibility,
    but now hard-requires WEBHOOK_SECRET to be set in env so this route can never
    be open. New deployments should register the per-workspace /webhook/{ws_id} route.
    """
    if not WEBHOOK_SECRET:
        logger.warning("Legacy /webhook hit but WEBHOOK_SECRET is not set — refusing.")
        raise HTTPException(status_code=503, detail="Legacy webhook disabled: WEBHOOK_SECRET not configured")
    return await _handle_webhook(request, db, workspace_id=1, secret=WEBHOOK_SECRET)


class DepositWebhookPayload(BaseModel):
    workspace_id: int
    provider: str
    client_id: Optional[str] = None
    contact_id: Optional[int] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    timestamp: Optional[str] = None
    source: Optional[str] = "email_parser"
    idempotency_key: Optional[str] = None


def _verify_deposit_signature(secret: str, body_bytes: bytes, signature: str) -> bool:
    import hashlib
    import hmac as _hmac
    if not secret or not signature:
        return False
    digest = _hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return _hmac.compare_digest(digest, signature.lower())


@app.post("/webhook/deposit-events")
@limiter.limit("60/minute")
async def deposit_event_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Provider-agnostic deposit webhook. Authenticated via HMAC-SHA256 over the
    raw body using the workspace's deposit_webhook_secret.
    Header: X-Deposit-Signature: <hex digest>
    """
    from datetime import datetime as _dt
    from app.database.models import Workspace
    from app.services.deposit import process_deposit_event, find_contact_for_deposit

    body_bytes = await request.body()
    try:
        data = json.loads(body_bytes or b"{}")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    payload = DepositWebhookPayload(**data)
    ws = db.query(Workspace).filter(Workspace.id == payload.workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="workspace not found")

    sig = request.headers.get("X-Deposit-Signature", "")
    if not ws.deposit_webhook_secret or not _verify_deposit_signature(
        ws.deposit_webhook_secret, body_bytes, sig,
    ):
        raise HTTPException(status_code=401, detail="bad signature")

    contact = find_contact_for_deposit(
        db, payload.workspace_id,
        contact_id=payload.contact_id, puprime_client_id=payload.client_id,
    )
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found for client_id")

    occurred = _dt.fromisoformat(payload.timestamp) if payload.timestamp else _dt.utcnow()
    idem = payload.idempotency_key or (
        f"{payload.provider}:{payload.client_id or contact.id}:{occurred.isoformat()}:{payload.amount or 0}"
    )
    result = process_deposit_event(
        db,
        workspace_id=payload.workspace_id,
        contact=contact,
        provider=payload.provider,
        source=payload.source or "email_parser",
        idempotency_key=idem,
        amount=payload.amount,
        currency=payload.currency,
        occurred_at=occurred,
        provider_client_id=payload.client_id,
        raw_payload=body_bytes.decode("utf-8", errors="replace"),
    )
    return {
        "ok": True, "deposit_event_id": result.deposit_event_id, "deduped": result.dedup,
    }


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
    """List all workspaces (developer only). Includes owner email so the
    developer's workspace switcher can show 'Org Name — owner@email'."""
    from app.database.models import Account, Organization, Workspace
    from app.services.telethon_client import get_client

    rows = db.query(Workspace).order_by(Workspace.id).all()
    out = []
    for ws in rows:
        owner = (
            db.query(Account)
              .filter(Account.workspace_id == ws.id, Account.is_active.is_(True))
              .order_by(Account.id.asc())
              .first()
        )
        org = db.query(Organization).filter(Organization.id == ws.org_id).first() if ws.org_id else None
        out.append({
            "id": ws.id,
            "name": ws.name,
            "org_id": ws.org_id,
            "org_name": org.name if org else None,
            "owner_email": owner.email if owner else None,
            "owner_account_id": owner.id if owner else None,
            "onboarding_complete": bool(ws.onboarding_complete),
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
            "has_telethon": get_client(ws.id) is not None,
            "has_meta": bool(ws.meta_access_token),
            "has_bot_token": bool(ws.bot_token),
        })
    return out


@app.post("/admin/impersonate/{workspace_id}")
def admin_impersonate(
    workspace_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer")),
):
    """
    Developer-only impersonation. Mints a JWT for the org-owner Account of the
    target workspace so the developer can see exactly what that customer sees.
    Audit-logged. Caller must already be authenticated as developer.
    """
    from app.database.models import Account, Workspace
    from app.auth import create_access_token
    from app.services.audit import log_audit

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="workspace not found")

    acct = (
        db.query(Account)
          .filter(Account.workspace_id == workspace_id, Account.is_active.is_(True))
          .order_by(Account.id.asc())
          .first()
    )
    if not acct:
        raise HTTPException(
            status_code=404,
            detail="no active Account row for this workspace; cannot impersonate",
        )

    org_role = acct.org_role or "org_owner"
    token = create_access_token(
        acct.email, acct.role,
        workspace_id=ws.id,
        org_id=ws.org_id,
        org_role=org_role,
        account_id=acct.id,
    )

    log_audit(
        db, action="admin.impersonate", request=request,
        target_type="workspace", target_id=ws.id,
        detail=f"impersonating {acct.email} (account_id={acct.id})",
    )

    return {
        "access_token": token,
        "role": acct.role,
        "username": acct.email,
        "workspace_id": ws.id,
        "workspace_name": ws.name,
        "org_id": ws.org_id,
        "org_role": org_role,
        "account_id": acct.id,
        "onboarding_complete": bool(ws.onboarding_complete),
        "parent_bot_username": None,
    }


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
    from app.services.audit import log_audit
    log_audit(db, action="workspace.switch", actor=current_user,
              target_type="workspace", target_id=workspace_id,
              detail=f"from={caller_ws_id}; to={workspace_id}")
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


# ---------------------------------------------------------------------------
# Per-account login lockout — defense in depth on top of per-IP rate limiting.
# In-memory; resets on process restart, which is fine for our scale.
# ---------------------------------------------------------------------------
_LOGIN_FAIL_THRESHOLD = 10              # failed attempts before lock
_LOGIN_FAIL_WINDOW = 15 * 60            # within this many seconds
_LOGIN_LOCK_DURATION = 30 * 60          # lock for this many seconds once triggered
_login_failures: dict[str, list[float]] = {}
_login_locks: dict[str, float] = {}
_login_lock_mutex = _Lock()


def _check_login_lock(username: str) -> Optional[int]:
    """Return seconds remaining if the account is locked, else None."""
    if not username:
        return None
    key = username.strip().lower()
    with _login_lock_mutex:
        until = _login_locks.get(key)
        if until and until > _time.time():
            return int(until - _time.time())
        if until and until <= _time.time():
            _login_locks.pop(key, None)
    return None


def _record_login_failure(username: str) -> None:
    if not username:
        return
    key = username.strip().lower()
    now = _time.time()
    with _login_lock_mutex:
        recent = [t for t in _login_failures.get(key, []) if t > now - _LOGIN_FAIL_WINDOW]
        recent.append(now)
        _login_failures[key] = recent
        if len(recent) >= _LOGIN_FAIL_THRESHOLD:
            _login_locks[key] = now + _LOGIN_LOCK_DURATION
            _login_failures[key] = []  # reset counter once locked
            logger.warning("Account locked after %d failed logins: %s", len(recent), key)


def _record_login_success(username: str) -> None:
    if not username:
        return
    key = username.strip().lower()
    with _login_lock_mutex:
        _login_failures.pop(key, None)
        _login_locks.pop(key, None)


class OrgSignupRequest(BaseModel):
    full_name: str
    email: str
    password: str
    org_name: str
    niche: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    country: Optional[str] = None
    main_channel_url: Optional[str] = None
    sales_telegram_username: Optional[str] = None
    meta_pixel_id: Optional[str] = None
    meta_ad_account_id: Optional[str] = None
    meta_access_token: Optional[str] = None


@app.post("/auth/signup/organization", status_code=201)
@limiter.limit("5/minute")
def signup_organization(request: Request, req: OrgSignupRequest, db: Session = Depends(get_db)):
    """Public. Creates Organization + root Workspace + Admin Account, seeds default pipeline."""
    from app.database.models import Account, Organization, Workspace
    from app.database import seed_workspace_defaults
    from app.auth import hash_password as _hash, create_access_token as _tok
    from sqlalchemy.exc import IntegrityError

    email = (req.email or "").strip().lower()
    if "@" not in email or len(email) < 4:
        raise HTTPException(status_code=400, detail="invalid email")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    if not req.full_name.strip():
        raise HTTPException(status_code=400, detail="full_name is required")
    if not req.org_name.strip():
        raise HTTPException(status_code=400, detail="org_name is required")

    if db.query(Account).filter(Account.email == email).first():
        raise HTTPException(status_code=409, detail="email already in use")

    try:
        org = Organization(name=req.org_name.strip())
        db.add(org); db.flush()

        ws = Workspace(
            name=req.org_name.strip(),
            org_id=org.id,
            parent_workspace_id=None,
            root_workspace_id=None,
            workspace_role="owner",
            niche=req.niche,
            language=req.language,
            timezone=req.timezone,
            country=req.country,
            main_channel_url=req.main_channel_url,
            sales_telegram_username=req.sales_telegram_username,
            meta_pixel_id=req.meta_pixel_id,
            meta_ad_account_id=req.meta_ad_account_id,
            meta_access_token=req.meta_access_token or None,
            onboarding_complete=False,
        )
        db.add(ws); db.flush()
        ws.root_workspace_id = ws.id

        acct = Account(
            workspace_id=ws.id,
            org_id=org.id,
            email=email,
            full_name=req.full_name.strip(),
            password_hash=_hash(req.password),
            role="admin",
            org_role="org_owner",
        )
        db.add(acct); db.commit(); db.refresh(acct); db.refresh(ws)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already in use")

    # Seed pipeline + keywords + templates + quick replies for the new workspace
    seed_workspace_defaults(ws.id, db)

    from app.services.audit import log_audit
    log_audit(
        db, action="signup.organization",
        actor={"username": email, "role": "admin"},
        target_type="account", target_id=acct.id,
        workspace_id=ws.id, request=request,
        detail=f"org={org.name}",
    )

    token = _tok(
        acct.email, acct.role,
        workspace_id=ws.id, org_id=org.id, org_role="org_owner",
        account_id=acct.id,
    )
    return {
        "access_token": token,
        "role": acct.role,
        "username": acct.email,
        "workspace_id": ws.id,
        "org_id": org.id,
        "org_role": "org_owner",
        "account_id": acct.id,
        "onboarding_complete": False,
    }


@app.post("/auth/login")
@limiter.limit("5/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token. Checks env-based roles and DB affiliates."""
    from app.services.audit import log_audit
    locked_for = _check_login_lock(req.username)
    if locked_for is not None:
        log_audit(db, action="login.locked", request=request,
                  detail=f"username={req.username[:64]}; locked_for_sec={locked_for}")
        raise HTTPException(
            status_code=429,
            detail=f"Account temporarily locked after too many failed attempts. Try again in {locked_for // 60 + 1} min.",
        )
    user = authenticate_user(req.username, req.password, db=db)
    if not user:
        _record_login_failure(req.username)
        log_audit(db, action="login.failure", request=request,
                  detail=f"attempted_username={req.username[:64]}")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _record_login_success(req.username)
    log_audit(db, action="login.success", actor=user, request=request)

    # Resolve workspace / org context
    from app.database.models import Workspace as WsModel, Affiliate as AffModel
    org_id = 1
    org_role = "member"

    if user.get("account_id"):
        # Account rows already carry the correct workspace/org/org_role — use directly
        ws_id = user["workspace_id"]
        org_id = user["org_id"]
        org_role = user["org_role"]
    else:
        ws_id = user.get("workspace_id", 1)

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

    ws = db.query(WsModel).filter(WsModel.id == ws_id).first()

    token = create_access_token(
        user["username"], user["role"],
        workspace_id=ws_id,
        org_id=org_id,
        org_role=org_role,
        affiliate_id=user.get("affiliate_id"),
        account_id=user.get("account_id"),
    )
    return {
        "access_token": token,
        "role": user["role"],
        "username": user["username"],
        "workspace_id": ws_id,
        "org_id": org_id,
        "org_role": org_role,
        "onboarding_complete": (bool(ws.onboarding_complete) if ws else True) if user["role"] == "affiliate" else True,
        "account_id": user.get("account_id"),
    }


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the current user's info."""
    data = dict(current_user)

    # Resolve the tenant's bot username for sub-affiliate onboarding UI.
    # Only sub-affiliates (org_role=workspace_owner with a parent workspace) need this;
    # org owners' wizard branches to the source-channel step instead.
    parent_bot_username = None
    if current_user.get("org_role") == "workspace_owner":
        from app.database.models import Workspace
        ws = db.query(Workspace).filter(Workspace.id == current_user.get("workspace_id")).first()
        if ws and ws.parent_workspace_id:
            parent = db.query(Workspace).filter(Workspace.id == ws.parent_workspace_id).first()
            if parent and parent.bot_token:
                import requests as _r
                try:
                    r = _r.get(
                        f"https://api.telegram.org/bot{parent.bot_token}/getMe",
                        timeout=5,
                    )
                    if r.status_code == 200:
                        parent_bot_username = r.json().get("result", {}).get("username")
                except Exception:
                    pass

    data["parent_bot_username"] = parent_bot_username
    return data


@app.get("/auth/config")
def auth_config():
    """Public endpoint — returns the bot username needed by the Telegram Login Widget."""
    from app.config import BOT_USERNAME, META_APP_ID
    return {"bot_username": BOT_USERNAME, "meta_app_id": META_APP_ID}


# ---------------------------------------------------------------------------
# Public well-known files (security.txt — RFC 9116)
# ---------------------------------------------------------------------------

_SECURITY_TXT = """\
Contact: mailto:sameerkaram2@gmail.com
Expires: 2027-04-25T00:00:00.000Z
Preferred-Languages: en
Canonical: https://telelytics.org/.well-known/security.txt
"""


@app.get("/.well-known/security.txt", include_in_schema=False)
def well_known_security_txt():
    """RFC 9116 — tells security researchers where to report vulnerabilities."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(_SECURITY_TXT, media_type="text/plain; charset=utf-8")


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
    db: Session = Depends(get_db),
    _=Depends(require_workspace_owner),
):
    from app.services.telethon_client import get_client
    from app.database.models import Workspace
    import json as _json

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    last_summary = None
    if ws and ws.last_backfill_summary:
        try:
            last_summary = _json.loads(ws.last_backfill_summary)
        except Exception:
            last_summary = None
    return {
        "connected": get_client(workspace_id) is not None,
        "last_backfill_at": ws.last_backfill_at.isoformat() if ws and ws.last_backfill_at else None,
        "last_backfill_summary": last_summary,
    }


@app.get("/settings/forwarding/status")
def forwarding_status(
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
    db: Session = Depends(get_db),
):
    """Return signal forwarding health: bot token set, source set, destinations configured."""
    from app.services.forwarding import get_destinations_for_org
    from app.database.models import Workspace

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    bot_token = ws.bot_token if ws else None
    source_id = ws.source_channel_id if ws else None
    destinations = get_destinations_for_org(workspace_id, db)
    destination_count = len(destinations)
    bot_configured = bool(bot_token)
    source_configured = bool(source_id)

    return {
        "bot_configured": bot_configured,
        "source_configured": source_configured,
        "destination_count": destination_count,
        "active": bot_configured and source_configured and destination_count > 0,
    }


@app.get("/settings/forwarding/config")
def get_forwarding_config(
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
    db: Session = Depends(get_db),
):
    """Return source + destination channel config for this workspace."""
    from app.services.forwarding import get_destinations_for_org
    from app.database.models import Workspace, Affiliate

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()

    affiliate_channels = (
        db.query(Affiliate.id, Affiliate.name, Affiliate.vip_channel_id)
        .join(Workspace, Affiliate.affiliate_workspace_id == Workspace.id)
        .filter(
            Workspace.root_workspace_id == workspace_id,
            Affiliate.is_active.is_(True),
            Affiliate.vip_channel_id.isnot(None),
        )
        .all()
    )

    return {
        "source_channel_id": ws.source_channel_id if ws else None,
        "destination_channel_ids": ws.destination_channel_ids if ws else None,
        "effective_source_channel_id": ws.source_channel_id if ws else None,
        "effective_destinations": get_destinations_for_org(workspace_id, db),
        "affiliate_destinations": [
            {"id": a.id, "name": a.name, "vip_channel_id": a.vip_channel_id}
            for a in affiliate_channels
        ],
    }


class ForwardingConfigRequest(BaseModel):
    source_channel_id: Optional[str] = None
    destination_channel_ids: Optional[str] = None  # CSV


@app.patch("/settings/forwarding/config")
async def set_forwarding_config(
    req: ForwardingConfigRequest,
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
    db: Session = Depends(get_db),
):
    """Save source + destination channel IDs to the workspace."""
    from app.database.models import Workspace

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    source_changed = False
    if req.source_channel_id is not None:
        ws.source_channel_id = req.source_channel_id.strip() or None
        source_changed = True
    if req.destination_channel_ids is not None:
        cleaned = ",".join(x.strip() for x in req.destination_channel_ids.split(",") if x.strip())
        ws.destination_channel_ids = cleaned or None
    db.commit()

    # Cycle Telethon client so the new source_channel_id takes effect immediately
    if source_changed and ws.telethon_session:
        from app.services.telethon_client import stop_workspace_client, start_workspace_client
        from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
        await stop_workspace_client(workspace_id)
        await start_workspace_client(workspace_id, ws.telethon_session, TELEGRAM_API_ID, TELEGRAM_API_HASH)

    return {"ok": True}


@app.post("/settings/telethon/connect")
async def telethon_connect(
    req: TelethonConnectRequest,
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
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
    current_user: dict = Depends(require_workspace_owner),
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
    from app.services.audit import log_audit
    log_audit(db, action="telethon.connected", actor=current_user,
              target_type="workspace", target_id=workspace_id,
              workspace_id=workspace_id, detail=f"phone={req.phone[-4:]}")
    return {"ok": started}


@app.post("/settings/telethon/disconnect")
async def telethon_disconnect(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    current_user: dict = Depends(require_workspace_owner),
):
    """Stop the Telethon client and clear the saved session."""
    from app.database.models import Workspace
    from app.services.telethon_client import stop_workspace_client
    from app.services.audit import log_audit

    await stop_workspace_client(workspace_id)
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws:
        ws.telethon_session = None
        db.commit()
    log_audit(db, action="telethon.disconnected", actor=current_user,
              target_type="workspace", target_id=workspace_id,
              workspace_id=workspace_id)
    return {"ok": True}


class WorkspaceSourceChannelRequest(BaseModel):
    source_channel_id: str


@app.patch("/workspace/me/source-channel")
async def update_workspace_source_channel(
    req: WorkspaceSourceChannelRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """
    Set the org owner's source channel. Cycles their Telethon client so the
    new channel's signal handler activates without a service restart.
    """
    from app.database.models import Workspace
    from app.services.telethon_client import stop_workspace_client, start_workspace_client
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH

    ws_id = current_user["workspace_id"]
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws.source_channel_id = req.source_channel_id.strip()
    db.commit()

    if ws.telethon_session:
        await stop_workspace_client(ws_id)
        await start_workspace_client(ws_id, ws.telethon_session, TELEGRAM_API_ID, TELEGRAM_API_HASH)

    return {"ok": True, "source_channel_id": ws.source_channel_id}


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
    _=Depends(require_workspace_owner),
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
    current_user: dict = Depends(require_workspace_owner),
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
    from app.services.audit import log_audit
    log_audit(db, action="bot.token_saved", actor=current_user,
              target_type="workspace", target_id=workspace_id,
              workspace_id=workspace_id)
    return {"ok": True}


@app.post("/settings/bot/register-webhook")
def bot_register_webhook(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
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


@app.get("/settings/my/pending-channels")
def my_pending_channels(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
):
    """
    Return channels/groups recently detected by the bot that serves this workspace.
    Sub-affiliates use the parent org's bot, so we read PendingChannel rows from the
    parent workspace (which is where the my_chat_member webhook stored them).
    Used by the onboarding wizard ("Detect channel").
    """
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    bot_ws_id = (
        ws.parent_workspace_id
        if (ws and ws.workspace_role == "affiliate" and ws.parent_workspace_id)
        else workspace_id
    )
    rows = (
        db.query(PendingChannel)
        .filter(PendingChannel.workspace_id == bot_ws_id)
        .order_by(PendingChannel.detected_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "chat_id": r.chat_id,
            "title": r.title,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        }
        for r in rows
    ]


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
        workspace_id=workspace_id,
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
        "invite_link": None,           # minted on first /attribution/invite call
        "channel_join_count": 0,       # populated as joins happen
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
    from app.database.models import (
        Campaign, CampaignInviteLink, ChannelJoinEvent, Contact, Workspace,
    )
    from app.config import BOT_USERNAME

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    landing_base = (ws.landing_page_url or "").strip().rstrip("/") if ws else ""

    campaigns = (
        db.query(Campaign)
          .filter(Campaign.workspace_id == workspace_id)
          .order_by(Campaign.created_at.desc())
          .all()
    )
    result = []
    for c in campaigns:
        leads = db.query(Contact).filter(Contact.source == c.source_tag).count()
        deposits = (
            db.query(Contact)
            .filter(
                Contact.source == c.source_tag,
                Contact.workspace_id == workspace_id,
                Contact.deposit_status == "deposited",
            )
            .count()
        )
        invite_row = (
            db.query(CampaignInviteLink)
              .filter_by(workspace_id=workspace_id, campaign_id=c.id)
              .filter(CampaignInviteLink.revoked_at.is_(None))
              .first()
        )
        join_count = (
            db.query(ChannelJoinEvent)
              .filter(
                  ChannelJoinEvent.workspace_id == workspace_id,
                  ChannelJoinEvent.source_tag == c.source_tag,
              )
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
            "invite_link": invite_row.invite_link if invite_row else None,
            "channel_join_count": join_count,
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


@app.get("/health/workspace")
async def health_workspace(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin", "operator", "vip_manager", "affiliate")),
):
    """
    Aggregated health for the current workspace — one card worth of info showing
    which integrations are up, degraded, or down. Logic lives in
    services/health.py so each check is independently testable.
    """
    from app.services import health
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    return await health.run_all_checks(ws, workspace_id, db)


def _origin_allowed_for_workspace(origin: str, landing_page_url: Optional[str]) -> bool:
    """
    True if `origin` matches one of:
      - the host parsed from `landing_page_url` (or its www. variant) — the
        external landing page calling /attribution/invite
      - the dashboard's own origin (APP_BASE_URL host) — the workspace owner
        previewing the link from inside Telelytics
      - localhost on the Vite dev port — frontend development
    """
    if not origin:
        return False
    try:
        from urllib.parse import urlparse
        og_host = (urlparse(origin).hostname or "").lower()
    except Exception:
        return False
    if not og_host:
        return False

    # 1. Dashboard origin (same-origin admin previews).
    try:
        from app.config import APP_BASE_URL
        dashboard_host = (urlparse(APP_BASE_URL).hostname or "").lower() if APP_BASE_URL else ""
    except Exception:
        dashboard_host = ""
    if dashboard_host and (og_host == dashboard_host or og_host == f"www.{dashboard_host}"):
        return True

    # 2. Local dev (Vite default port).
    if og_host == "localhost" or og_host == "127.0.0.1":
        return True

    # 3. Workspace's configured landing page.
    if not landing_page_url:
        return False
    try:
        from urllib.parse import urlparse as _u
        lp_host = (_u(landing_page_url).hostname or "").lower()
    except Exception:
        return False
    if not lp_host:
        return False
    return og_host == lp_host or og_host == f"www.{lp_host}" or lp_host == f"www.{og_host}"


def _attribution_error(origin: str, code: str, status: int):
    return _JSONResponse(
        {"error": code},
        status_code=status,
        headers={"Access-Control-Allow-Origin": origin} if origin else {},
    )


@app.get("/attribution/invite")
@limiter.limit("30/minute")
async def attribution_invite(
    request: Request,
    workspace_id: int,
    src: str,
    db: Session = Depends(get_db),
):
    """
    Public, CORS-allowlisted, IP-rate-limited.
    Returns the campaign-specific invite link for (workspace_id, src).
    """
    from app.database.models import Campaign, Workspace
    from app.services import attribution as _attr
    from app.services.telethon_client import get_client

    origin = request.headers.get("origin", "")

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws or not _origin_allowed_for_workspace(origin, ws.landing_page_url):
        return _attribution_error("", "origin_not_allowed", 403)

    campaign = (
        db.query(Campaign)
          .filter(
              Campaign.source_tag == src,
              Campaign.workspace_id == workspace_id,
              Campaign.is_active == True,  # noqa: E712
          )
          .first()
    )
    if not campaign:
        return _attribution_error(origin, "unknown_campaign", 404)

    client = get_client(workspace_id)
    channel_id = await _attr.resolve_attribution_channel(ws, db, client)
    if not channel_id:
        return _attribution_error(origin, "channel_unreachable", 502)

    row = await _attr.mint_invite_link(ws, campaign, db, client, channel_id=channel_id)
    if row is None:
        return _attribution_error(origin, "channel_unreachable", 502)

    return _JSONResponse(
        {
            "invite_link": row.invite_link,
            "campaign": campaign.source_tag,
            "channel_id": channel_id,
        },
        headers={
            "Access-Control-Allow-Origin": origin,
            "Cache-Control": "private, max-age=600",
        },
    )


# -----------------------------
# CRM Phase 1 API endpoints
# -----------------------------


class SendMessageRequest(BaseModel):
    contact_id: conint(ge=1)
    message: str


class ManualStageRequest(BaseModel):
    stage_id: int


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

    set_stage_manual(contact, req.stage_id)

    # Cancel stale follow-ups and schedule new ones for the new stage
    from app.services.scheduler import schedule_follow_ups_for_stage_id
    schedule_follow_ups_for_stage_id(contact_id, req.stage_id, contact.stage_entered_at)

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


class DepositRequest(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None
    occurred_at: Optional[str] = None  # ISO timestamp


@app.post("/contacts/{contact_id}/deposit")
def record_contact_deposit(
    contact_id: int,
    req: DepositRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin", "operator", "vip_manager")),
):
    """Manually record a deposit for a contact. Idempotent per (contact, day)."""
    from datetime import datetime as _dt
    from app.services.deposit import process_deposit_event
    workspace_id: int = current_user.get("workspace_id", 1)
    contact = db.query(User).filter(
        User.id == contact_id, User.workspace_id == workspace_id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")

    occurred = (_dt.fromisoformat(req.occurred_at) if req.occurred_at
                else _dt.utcnow())
    idem = f"manual:{contact_id}:{occurred.strftime('%Y%m%d')}"
    result = process_deposit_event(
        db,
        workspace_id=workspace_id,
        contact=contact,
        provider="manual",
        source="manual",
        idempotency_key=idem,
        amount=req.amount,
        currency=req.currency,
        occurred_at=occurred,
    )
    return {
        "ok": True,
        "deposit_event_id": result.deposit_event_id,
        "deduped": result.dedup,
        "moved_to_stage_id": result.moved_to_stage_id,
    }


# Backwards compat alias — old frontend builds still POST here
@app.post("/contacts/{contact_id}/deposit-confirm")
def deposit_confirm_legacy(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin", "operator", "vip_manager")),
):
    return record_contact_deposit(contact_id, DepositRequest(), db, current_user)


class PuPrimeIdRequest(BaseModel):
    puprime_client_id: str


@app.post("/contacts/{contact_id}/puprime-id")
def set_contact_puprime_id(
    contact_id: int, req: PuPrimeIdRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin", "operator")),
):
    """Store the PuPrime account number for a contact (used by deposit matching)."""
    workspace_id: int = current_user.get("workspace_id", 1)
    contact = db.query(User).filter(
        User.id == contact_id, User.workspace_id == workspace_id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.puprime_client_id = req.puprime_client_id.strip()
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
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    vip_stage_ids = {sid for sid in (ws.deposited_stage_id, ws.member_stage_id) if sid} if ws else set()
    if not vip_stage_ids or contact.current_stage_id not in vip_stage_ids:
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
    current_user: dict = Depends(require_roles("developer", "admin")),
):
    """Affiliate leaderboard with attributed leads, deposits, and commission earned."""
    return get_affiliate_performance(db, workspace_id=current_user["workspace_id"])


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


INVITE_EXPIRY_DAYS = 14


def _build_invite_url(token: str) -> str:
    """Build a public invite URL for the given token."""
    from app.config import APP_BASE_URL
    base = (APP_BASE_URL or "").rstrip("/")
    return f"{base}/invite/{token}" if base else f"/invite/{token}"


def _issue_invite_token(affiliate, db: Session) -> str:
    """Generate a fresh invite token on the given affiliate and persist it."""
    import secrets as _secrets
    from datetime import datetime, timedelta
    token = _secrets.token_urlsafe(32)
    affiliate.invite_token = token
    affiliate.invite_expires_at = datetime.utcnow() + timedelta(days=INVITE_EXPIRY_DAYS)
    db.commit()
    return token


@app.post("/affiliates")
def create_affiliate(
    req: CreateAffiliateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """
    Register a new affiliate and auto-provision a child CRM workspace for them.
    Instead of generating a password, issues a one-time invite URL the admin
    sends to the affiliate; the affiliate sets their own password on first use.
    """
    import re
    import uuid
    from app.database.models import Affiliate, Workspace
    from app.database import seed_workspace_defaults
    from app.config import BOT_USERNAME

    # Human-readable username derived from the affiliate's name.
    # "Jason Rivera" -> "jason.rivera"  (collision -> "jason.rivera2" etc.)
    base_slug = re.sub(r"[^a-z0-9]+", ".", req.name.strip().lower()).strip(".")
    if not base_slug:
        base_slug = "affiliate"
    login_username = base_slug
    suffix = 2
    while db.query(Affiliate).filter(Affiliate.login_username == login_username).first():
        login_username = f"{base_slug}{suffix}"
        suffix += 1

    # Referral tag: short, name-based, with a tiny random suffix to keep URLs unique
    referral_tag = f"{base_slug[:16]}-{uuid.uuid4().hex[:4]}"

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
        workspace_id=caller_ws_id,
        name=req.name.strip(),
        username=req.username.strip() if req.username else None,
        referral_tag=referral_tag,
        commission_rate=req.commission_rate,
        login_username=login_username,
        login_password_hash=None,  # set via invite
        affiliate_workspace_id=aff_workspace.id,
    )
    db.add(affiliate)
    db.commit()
    db.refresh(affiliate)
    db.refresh(aff_workspace)

    invite_token = _issue_invite_token(affiliate, db)

    seed_workspace_defaults(aff_workspace.id, db)

    from app.services.audit import log_audit
    log_audit(db, action="affiliate.create", actor=current_user,
              target_type="affiliate", target_id=affiliate.id,
              detail=f"name={affiliate.name}; ws={aff_workspace.id}")

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
        # Invite details — shown once at creation. Admin sends the URL to the affiliate.
        "login_username": login_username,
        "invite_url": _build_invite_url(invite_token),
        "invite_expires_at": affiliate.invite_expires_at.isoformat() if affiliate.invite_expires_at else None,
        # Stats defaults (no activity yet)
        "leads": 0, "deposits": 0, "conversion_rate": 0, "commission_earned": 0,
        # Checklist defaults
        "esim_done": False, "free_channel_id": None, "free_channel_members": 0,
        "bot_setup_done": False, "vip_channel_id": None, "vip_channel_members": 0,
        "tutorial_channel_id": None, "tutorial_channel_members": 0,
        "sales_scripts_done": False, "ib_profile_id": None,
        "ads_live": False, "pixel_setup_done": False,
    }


@app.post("/affiliates/{affiliate_id}/reset-credentials")
def reset_affiliate_credentials(
    affiliate_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """
    Regenerate the invite token for an affiliate and invalidate their password.
    Used when the affiliate lost their credentials or never finished the invite.
    Returns a fresh invite URL the admin sends them.
    """
    from app.database.models import Affiliate
    aff = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
    if not aff:
        raise HTTPException(status_code=404, detail="affiliate not found")
    # TODO: could also check caller is in aff's parent chain; require_workspace_owner
    # already gates on org/workspace scope for the queries that matter.
    aff.login_password_hash = None  # force them to set a new one via the invite
    token = _issue_invite_token(aff, db)
    from app.services.audit import log_audit
    log_audit(db, action="affiliate.credentials_reset", actor=current_user,
              target_type="affiliate", target_id=aff.id,
              detail=f"name={aff.name}")
    return {
        "login_username": aff.login_username,
        "invite_url": _build_invite_url(token),
        "invite_expires_at": aff.invite_expires_at.isoformat() if aff.invite_expires_at else None,
    }


# ---------------------------------------------------------------------------
# Public invite endpoints (no auth required)
# ---------------------------------------------------------------------------

class AcceptInviteRequest(BaseModel):
    password: str


@app.get("/invite/{token}")
def invite_lookup(token: str, db: Session = Depends(get_db)):
    """Public. Given an invite token, return the affiliate's display name + login username."""
    from datetime import datetime
    from app.database.models import Affiliate
    aff = db.query(Affiliate).filter(Affiliate.invite_token == token).first()
    if not aff or not aff.is_active:
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    if aff.invite_expires_at and aff.invite_expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invite has expired — ask your admin to resend")
    return {
        "name": aff.name,
        "login_username": aff.login_username,
        "expires_at": aff.invite_expires_at.isoformat() if aff.invite_expires_at else None,
    }


@app.post("/invite/{token}")
@limiter.limit("5/minute")
def invite_accept(token: str, req: AcceptInviteRequest, request: Request, db: Session = Depends(get_db)):
    """
    Public. The affiliate posts their chosen password here. We hash it, clear the
    invite token, and return a JWT so the frontend can log them straight in.
    """
    from datetime import datetime
    from app.database.models import Affiliate, Workspace
    from app.auth import hash_password as _hash, create_access_token as _create_token

    password = (req.password or "").strip()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    aff = db.query(Affiliate).filter(Affiliate.invite_token == token).first()
    if not aff or not aff.is_active:
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    if aff.invite_expires_at and aff.invite_expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invite has expired — ask your admin to resend")

    aff.login_password_hash = _hash(password)
    aff.invite_token = None
    aff.invite_expires_at = None
    db.commit()
    from app.services.audit import log_audit
    log_audit(db, action="invite.accepted",
              actor={"username": aff.login_username, "role": "affiliate"},
              target_type="affiliate", target_id=aff.id,
              workspace_id=aff.affiliate_workspace_id, request=request)

    # Mint a JWT just like /auth/login would, so the frontend can log the affiliate
    # in without bouncing them through the login page.
    ws_id = aff.affiliate_workspace_id or aff.workspace_id or 1
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    org_id = ws.org_id if ws and ws.org_id else 1
    token_jwt = _create_token(
        aff.login_username or aff.name, "affiliate",
        workspace_id=ws_id, org_id=org_id, org_role="workspace_owner",
        affiliate_id=aff.id,
    )

    # Resolve the parent's bot username so the wizard can show @ParentBot
    parent_bot_username = None
    parent = (
        db.query(Workspace).filter(Workspace.id == ws.parent_workspace_id).first()
        if ws and ws.parent_workspace_id else None
    )
    if parent and parent.bot_token:
        import requests as _r
        try:
            r = _r.get(f"https://api.telegram.org/bot{parent.bot_token}/getMe", timeout=5)
            if r.status_code == 200:
                parent_bot_username = r.json().get("result", {}).get("username")
        except Exception:
            pass

    return {
        "access_token": token_jwt,
        "role": "affiliate",
        "username": aff.login_username,
        "workspace_id": ws_id,
        "org_id": org_id,
        "org_role": "workspace_owner",
        "onboarding_complete": bool(ws.onboarding_complete) if ws else False,
        "parent_bot_username": parent_bot_username,
    }


# ---------------------------------------------------------------------------
# AffiliateInvite endpoints — token-based invite flow (Task 6.4)
# URL prefix /auth/affiliate-invites avoids collision with legacy /invite/{token}
# ---------------------------------------------------------------------------

class AffiliateInviteCreateRequest(BaseModel):
    email: Optional[str] = None
    expires_in_days: int = 14


class AffiliateInviteAcceptRequest(BaseModel):
    full_name: str
    email: str
    password: str
    affiliate_username: Optional[str] = None  # Telegram @handle (optional)


@app.post("/auth/affiliate-invites", status_code=201)
def issue_affiliate_invite(
    req: AffiliateInviteCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    import secrets as _secrets
    from datetime import datetime, timedelta
    from app.database.models import AffiliateInvite
    from app.services.audit import log_audit

    token = _secrets.token_urlsafe(32)
    inv = AffiliateInvite(
        workspace_id=current_user["workspace_id"],
        invited_by_account_id=current_user.get("account_id"),
        email=(req.email or "").strip() or None,
        invite_token=token,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=req.expires_in_days),
    )
    db.add(inv); db.commit(); db.refresh(inv)
    log_audit(db, action="affiliate_invite.issued", actor=current_user,
              target_type="affiliate_invite", target_id=inv.id,
              workspace_id=current_user["workspace_id"],
              detail=f"email={inv.email or '—'}")
    from app.config import APP_BASE_URL
    base = (APP_BASE_URL or "").rstrip("/")
    return {
        "invite_token": token,
        "invite_url": f"{base}/affiliate-invite/{token}" if base else f"/affiliate-invite/{token}",
        "expires_at": inv.expires_at.isoformat(),
    }


@app.get("/auth/affiliate-invites/{token}")
def lookup_affiliate_invite(token: str, db: Session = Depends(get_db)):
    from datetime import datetime
    from app.database.models import AffiliateInvite, Workspace, Account
    inv = db.query(AffiliateInvite).filter(AffiliateInvite.invite_token == token).first()
    if not inv or inv.status != "pending":
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    if inv.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")
    ws = db.query(Workspace).filter(Workspace.id == inv.workspace_id).first()
    inviter = (db.query(Account).filter(Account.id == inv.invited_by_account_id).first()
               if inv.invited_by_account_id else None)
    return {
        "workspace_name": ws.name if ws else "Unknown",
        "inviter_name": inviter.full_name if inviter else None,
        "expires_at": inv.expires_at.isoformat(),
    }


@app.post("/auth/affiliate-invites/{token}/accept")
@limiter.limit("5/minute")
def accept_affiliate_invite(
    request: Request, token: str, req: AffiliateInviteAcceptRequest,
    db: Session = Depends(get_db),
):
    """Public. Creates Account + Affiliate + child Workspace; consumes invite."""
    from datetime import datetime
    import re, uuid
    from sqlalchemy.exc import IntegrityError
    from app.database.models import (
        AffiliateInvite, Workspace, Affiliate, Account,
    )
    from app.auth import hash_password as _hash, create_access_token as _tok
    from app.database import seed_workspace_defaults
    from app.services.audit import log_audit

    inv = db.query(AffiliateInvite).filter(AffiliateInvite.invite_token == token).first()
    if not inv or inv.status != "pending":
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    if inv.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")

    email = (req.email or "").strip().lower()
    if "@" not in email or len(email) < 4:
        raise HTTPException(status_code=400, detail="invalid email")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    if not req.full_name.strip():
        raise HTTPException(status_code=400, detail="full_name is required")
    if db.query(Account).filter(Account.email == email).first():
        raise HTTPException(status_code=409, detail="email already in use")

    parent = db.query(Workspace).filter(Workspace.id == inv.workspace_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="parent workspace gone")

    base_slug = re.sub(r"[^a-z0-9]+", ".", req.full_name.strip().lower()).strip(".")
    if not base_slug:
        base_slug = "affiliate"
    referral_tag = f"{base_slug[:16]}-{uuid.uuid4().hex[:4]}"

    try:
        child = Workspace(
            name=req.full_name.strip(),
            org_id=parent.org_id, parent_workspace_id=parent.id,
            root_workspace_id=parent.root_workspace_id or parent.id,
            workspace_role="affiliate", onboarding_complete=False,
        )
        db.add(child); db.flush()

        aff = Affiliate(
            workspace_id=parent.id,
            name=req.full_name.strip(),
            username=(req.affiliate_username or "").strip() or None,
            referral_tag=referral_tag,
            affiliate_workspace_id=child.id,
        )
        db.add(aff); db.flush()

        acct = Account(
            workspace_id=child.id, org_id=parent.org_id,
            email=email, full_name=req.full_name.strip(),
            password_hash=_hash(req.password),
            role="affiliate", org_role="workspace_owner",
            affiliate_id=aff.id,
        )
        db.add(acct)

        inv.status = "accepted"
        inv.accepted_at = datetime.utcnow()
        db.commit(); db.refresh(acct); db.refresh(child); db.refresh(aff)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already in use")

    seed_workspace_defaults(child.id, db)

    log_audit(db, action="affiliate.invite_accepted",
              actor={"username": email, "role": "affiliate"},
              target_type="affiliate", target_id=aff.id,
              workspace_id=child.id, request=request)

    token_jwt = _tok(
        email, "affiliate",
        workspace_id=child.id, org_id=parent.org_id, org_role="workspace_owner",
        affiliate_id=aff.id, account_id=acct.id,
    )

    # Resolve the parent's bot username so the wizard can show @ParentBot
    # in the "Add this bot to your channel" instructions.
    parent_bot_username = None
    if parent.bot_token:
        import requests as _r
        try:
            r = _r.get(f"https://api.telegram.org/bot{parent.bot_token}/getMe", timeout=5)
            if r.status_code == 200:
                parent_bot_username = r.json().get("result", {}).get("username")
        except Exception:
            pass

    return {
        "access_token": token_jwt,
        "role": "affiliate",
        "username": email,
        "workspace_id": child.id,
        "org_id": parent.org_id,
        "org_role": "workspace_owner",
        "account_id": acct.id,
        "affiliate_id": aff.id,
        "onboarding_complete": False,
        "parent_bot_username": parent_bot_username,
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


def _cascade_delete_workspace(ws_id: int, db: Session) -> None:
    """
    Delete every row scoped to an affiliate workspace, in FK-safe order, and
    the workspace row itself. Also stops its Telethon client if running.
    Does NOT commit — caller must.
    """
    from app.database.models import (
        Workspace, Contact, Message, StageHistory, FollowUpQueue,
        FollowUpTemplate, StageKeyword, StageLabel, QuickReply, TeamMember,
        Campaign, PendingChannel, Account,
    )

    # Stop Telethon client if running (fire-and-forget)
    try:
        import asyncio
        from app.services.telethon_client import stop_workspace_client
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(stop_workspace_client(ws_id))
        else:
            loop.run_until_complete(stop_workspace_client(ws_id))
    except Exception:
        pass  # non-critical — session bytes die with the workspace row

    # Child rows first (via contact_id), then workspace-scoped rows, then the workspace
    contact_ids = [c.id for c in db.query(Contact.id).filter(Contact.workspace_id == ws_id).all()]
    if contact_ids:
        db.query(Message).filter(Message.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(StageHistory).filter(StageHistory.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(FollowUpQueue).filter(FollowUpQueue.contact_id.in_(contact_ids)).delete(synchronize_session=False)

    # Delete Account rows before Affiliate rows (Account.affiliate_id FKs into affiliates)
    db.query(Account).filter(Account.workspace_id == ws_id).delete(synchronize_session=False)

    for model in (Contact, FollowUpTemplate, StageKeyword, StageLabel, QuickReply, TeamMember, Campaign, PendingChannel):
        db.query(model).filter(model.workspace_id == ws_id).delete(synchronize_session=False)

    db.query(Workspace).filter(Workspace.id == ws_id).delete(synchronize_session=False)


@app.delete("/affiliates/{affiliate_id}")
def delete_affiliate(
    affiliate_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin")),
):
    """
    Permanently delete an affiliate AND their provisioned workspace with every
    piece of data scoped to it (contacts, messages, channels, templates, etc.).

    Refuses if the affiliate has sub-affiliates — those must be deleted first
    so we never silently orphan a deeper workspace tree.
    """
    from app.database.models import Affiliate, Workspace

    affiliate = db.query(Affiliate).filter(Affiliate.id == affiliate_id).first()
    if not affiliate:
        raise HTTPException(status_code=404, detail="affiliate not found")

    ws_id = affiliate.affiliate_workspace_id

    # Guard: don't nuke a subtree — require sub-affiliates be deleted first
    if ws_id:
        sub_count = db.query(Workspace).filter(Workspace.parent_workspace_id == ws_id).count()
        if sub_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"This affiliate has {sub_count} sub-affiliate(s). Delete them first.",
            )

    aff_name = affiliate.name
    if ws_id:
        _cascade_delete_workspace(ws_id, db)

    db.delete(affiliate)
    db.commit()
    from app.services.audit import log_audit
    log_audit(db, action="affiliate.delete", actor=current_user,
              target_type="affiliate", target_id=affiliate_id,
              detail=f"name={aff_name}; cascaded_workspace={ws_id}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Orphaned workspace cleanup (admin)
# ---------------------------------------------------------------------------

def _find_orphaned_affiliate_workspaces(db: Session) -> list:
    """
    Return Workspace rows with workspace_role='affiliate' that no longer have
    a matching Affiliate row. These are left behind by pre-cascade deletes.
    """
    from app.database.models import Workspace, Affiliate

    # Set of workspace IDs still referenced by an affiliate
    referenced = {
        wid for (wid,) in db.query(Affiliate.affiliate_workspace_id)
        .filter(Affiliate.affiliate_workspace_id.isnot(None))
        .all()
    }
    candidates = (
        db.query(Workspace)
        .filter(Workspace.workspace_role == "affiliate")
        .all()
    )
    return [w for w in candidates if w.id not in referenced]


@app.get("/admin/orphaned-workspaces")
def list_orphaned_workspaces(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """List affiliate workspaces that no longer have an affiliate record (preview before purge)."""
    from app.database.models import Contact

    orphans = _find_orphaned_affiliate_workspaces(db)
    result = []
    for w in orphans:
        lead_count = db.query(Contact).filter(Contact.workspace_id == w.id).count()
        result.append({
            "id": w.id,
            "name": w.name,
            "parent_workspace_id": w.parent_workspace_id,
            "created_at": w.created_at.isoformat() if w.created_at else None,
            "lead_count": lead_count,
        })
    return result


@app.get("/admin/audit-log")
def list_audit_log(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
    limit: int = 100,
    action: Optional[str] = None,
    actor: Optional[str] = None,
):
    """
    Read the audit log. Newest first. Filter by action prefix (e.g. 'login.')
    or actor username. Capped at 500 rows per call.
    """
    from app.database.models import AuditLog
    limit = max(1, min(limit, 500))
    q = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if action:
        q = q.filter(AuditLog.action.like(f"{action}%"))
    if actor:
        q = q.filter(AuditLog.actor_username == actor.strip().lower())
    rows = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "actor_username": r.actor_username,
            "actor_role": r.actor_role,
            "workspace_id": r.workspace_id,
            "org_id": r.org_id,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "detail": r.detail,
            "ip_address": r.ip_address,
        }
        for r in rows
    ]


@app.post("/admin/orphaned-workspaces/purge")
def purge_orphaned_workspaces(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin")),
):
    """Cascade-delete every orphaned affiliate workspace. Returns {deleted: N}."""
    orphans = _find_orphaned_affiliate_workspaces(db)
    purged_ids = [w.id for w in orphans]
    for w in orphans:
        _cascade_delete_workspace(w.id, db)
    db.commit()
    from app.services.audit import log_audit
    log_audit(db, action="workspace.orphans_purged", actor=current_user,
              detail=f"count={len(purged_ids)}; ws_ids={purged_ids}")
    return {"deleted": len(orphans)}


@app.post("/workspaces/{workspace_id}/backfill-telegram-history")
async def trigger_backfill(
    workspace_id: int,
    limit_per_dialog: int = 200,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin")),
):
    """Pull past Telegram DMs for the workspace and replay them through advance_stage."""
    if current_user.get("workspace_id") != workspace_id and current_user["role"] != "developer":
        raise HTTPException(status_code=403, detail="cross-workspace backfill not allowed")
    from app.services.backfill import backfill_workspace_history
    return await backfill_workspace_history(workspace_id, limit_per_dialog=min(limit_per_dialog, 500))


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

    # Derived connection state — reflects what onboarding actually configured.
    # Workspace is the affiliate's own provisioned workspace (affiliate_workspace_id).
    from app.database.models import Workspace as _Ws
    ws = db.query(_Ws).filter(_Ws.id == (aff.affiliate_workspace_id or aff.workspace_id)).first()
    has_bot_token = bool(ws and ws.bot_token)
    has_conversion_desk = bool(ws and ws.telethon_session)

    leads = (
        db.query(func.count(Contact.id))
        .filter(Contact.source == aff.referral_tag, Contact.classification != "noise")
        .scalar() or 0
    )
    deposits = (
        db.query(func.count(Contact.id))
        .filter(
            Contact.source == aff.referral_tag,
            Contact.deposit_status == "deposited",
        )
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
        # Derived — reflects real workspace state, always in sync with onboarding/settings
        "has_bot_token": has_bot_token,
        "has_conversion_desk": has_conversion_desk,
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
    current_user: dict = Depends(require_roles("developer", "admin")),
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
    from app.services.audit import log_audit
    log_audit(db, action="team.create", actor=current_user,
              target_type="team_member", target_id=member.id,
              workspace_id=workspace_id,
              detail=f"username={username}; role={req.role}; auth={req.auth_type}")
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
    current_user: dict = Depends(require_roles("developer", "admin")),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import TeamMember
    from app.auth import generate_password, hash_password
    from app.services.audit import log_audit
    member = db.query(TeamMember).filter(
        TeamMember.id == member_id, TeamMember.workspace_id == workspace_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="team member not found")
    plain_password = generate_password()
    member.password_hash = hash_password(plain_password)
    db.commit()
    log_audit(db, action="team.password_reset", actor=current_user,
              target_type="team_member", target_id=member.id,
              workspace_id=workspace_id, detail=f"username={member.username}")
    return {"ok": True, "password": plain_password}


@app.delete("/settings/team/{member_id}")
def settings_delete_team_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles("developer", "admin")),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import TeamMember
    from app.services.audit import log_audit
    member = db.query(TeamMember).filter(
        TeamMember.id == member_id, TeamMember.workspace_id == workspace_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="team member not found")
    member_username = member.username
    db.delete(member)
    db.commit()
    log_audit(db, action="team.delete", actor=current_user,
              target_type="team_member", target_id=member_id,
              workspace_id=workspace_id, detail=f"username={member_username}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings — keywords, follow-up templates, quick replies, stage labels
# ---------------------------------------------------------------------------

SETTINGS_ROLES = Depends(require_roles("developer", "admin"))


class KeywordCreateRequest(BaseModel):
    keyword: str
    target_stage_id: int


class KeywordUpdateRequest(BaseModel):
    keyword: Optional[str] = None
    target_stage_id: Optional[int] = None
    is_active: Optional[bool] = None


class FollowUpUpdateRequest(BaseModel):
    message_text: str
    hours_offset: Optional[float] = None


class QuickReplyCreateRequest(BaseModel):
    stage_id: int
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


# --- Workspace metadata ---

class WorkspacePatchRequest(BaseModel):
    name: Optional[str] = None
    niche: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    country: Optional[str] = None
    main_channel_url: Optional[str] = None
    sales_telegram_username: Optional[str] = None
    landing_page_url: Optional[str] = None


@app.patch("/settings/workspace")
def patch_workspace(
    req: WorkspacePatchRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
):
    """Update workspace metadata (org info, channel URLs)."""
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="workspace not found")
    for k, v in req.dict(exclude_none=True).items():
        setattr(ws, k, v)
    db.commit()
    return {"ok": True}


# --- Pipeline CRUD ---

class PipelineStageCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    is_deposit_stage: bool = False
    is_member_stage: bool = False
    is_conversion_stage: bool = False
    end_action: str = "cold"
    revert_to_stage_id: Optional[int] = None


class PipelineStageUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    is_deposit_stage: Optional[bool] = None
    is_member_stage: Optional[bool] = None
    is_conversion_stage: Optional[bool] = None
    end_action: Optional[str] = None
    revert_to_stage_id: Optional[int] = None


class PipelineReorderRequest(BaseModel):
    ordered_ids: list[int]


class PipelineFlagsRequest(BaseModel):
    deposited_stage_id: Optional[int] = None
    member_stage_id: Optional[int] = None
    conversion_stage_id: Optional[int] = None
    vip_marker_phrases: Optional[list[str]] = None


def _stage_dto(s):
    return {
        "id": s.id, "position": s.position, "name": s.name,
        "description": s.description, "color": s.color,
        "is_deposit_stage": s.is_deposit_stage,
        "is_member_stage": s.is_member_stage,
        "is_conversion_stage": s.is_conversion_stage,
        "end_action": s.end_action,
        "revert_to_stage_id": s.revert_to_stage_id,
    }


@app.get("/settings/pipeline")
def get_pipeline(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
):
    from app.database.models import PipelineStage, Workspace
    import json as _json
    stages = (db.query(PipelineStage)
              .filter(PipelineStage.workspace_id == workspace_id)
              .order_by(PipelineStage.position).all())
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    markers: list = []
    if ws and ws.vip_marker_phrases:
        try:
            markers = _json.loads(ws.vip_marker_phrases) or []
        except Exception:
            markers = []
    return {
        "stages": [_stage_dto(s) for s in stages],
        "deposited_stage_id": ws.deposited_stage_id if ws else None,
        "member_stage_id": ws.member_stage_id if ws else None,
        "conversion_stage_id": ws.conversion_stage_id if ws else None,
        "vip_marker_phrases": markers,
    }


@app.post("/settings/pipeline/stages", status_code=201)
def create_pipeline_stage(
    req: PipelineStageCreateRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
):
    from app.database.models import PipelineStage
    last = (db.query(PipelineStage)
            .filter(PipelineStage.workspace_id == workspace_id)
            .order_by(PipelineStage.position.desc()).first())
    next_pos = (last.position if last else 0) + 1
    stage = PipelineStage(
        workspace_id=workspace_id, position=next_pos, name=req.name.strip(),
        description=req.description, color=req.color,
        is_deposit_stage=req.is_deposit_stage,
        is_member_stage=req.is_member_stage,
        is_conversion_stage=req.is_conversion_stage,
        end_action=req.end_action,
        revert_to_stage_id=req.revert_to_stage_id,
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return _stage_dto(stage)


@app.patch("/settings/pipeline/stages/{stage_id}")
def update_pipeline_stage(
    stage_id: int, req: PipelineStageUpdateRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
):
    from app.database.models import PipelineStage
    s = db.query(PipelineStage).filter(
        PipelineStage.id == stage_id,
        PipelineStage.workspace_id == workspace_id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="stage not found")
    for k, v in req.dict(exclude_none=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _stage_dto(s)


@app.delete("/settings/pipeline/stages/{stage_id}")
def delete_pipeline_stage(
    stage_id: int,
    move_contacts_to: Optional[int] = None,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
):
    from app.database.models import PipelineStage, Contact, Workspace
    s = db.query(PipelineStage).filter(
        PipelineStage.id == stage_id,
        PipelineStage.workspace_id == workspace_id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="stage not found")

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws and stage_id in (ws.deposited_stage_id, ws.member_stage_id):
        raise HTTPException(
            status_code=400,
            detail="cannot delete a stage marked as deposit or member; reassign the flag first",
        )

    occupied = db.query(Contact).filter(
        Contact.workspace_id == workspace_id,
        Contact.current_stage_id == stage_id,
    ).count()
    if occupied:
        if move_contacts_to is None:
            raise HTTPException(
                status_code=409,
                detail=f"{occupied} contacts in this stage; pass ?move_contacts_to=<stage_id>",
            )
        target = db.query(PipelineStage).filter(
            PipelineStage.id == move_contacts_to,
            PipelineStage.workspace_id == workspace_id,
        ).first()
        if not target:
            raise HTTPException(status_code=400, detail="move target stage not found")
        db.query(Contact).filter(
            Contact.workspace_id == workspace_id,
            Contact.current_stage_id == stage_id,
        ).update({
            Contact.current_stage_id: target.id,
            Contact.current_stage: target.position,
        })

    db.delete(s)
    db.flush()
    # Re-densify positions so they remain 1..N contiguous.
    # Use raw SQL two-pass to avoid UNIQUE(workspace_id, position) collision.
    from sqlalchemy import text
    rest = (db.query(PipelineStage)
            .filter(PipelineStage.workspace_id == workspace_id)
            .order_by(PipelineStage.position).all())
    for row in rest:
        db.execute(
            text("UPDATE pipeline_stages SET position = :neg WHERE id = :id"),
            {"neg": -(row.id), "id": row.id},
        )
    db.flush()
    for i, row in enumerate(rest, start=1):
        db.execute(
            text("UPDATE pipeline_stages SET position = :pos WHERE id = :id"),
            {"pos": i, "id": row.id},
        )
    db.commit()
    db.expire_all()
    return {"ok": True}


@app.post("/settings/pipeline/reorder")
def reorder_pipeline(
    req: PipelineReorderRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
):
    from sqlalchemy import text
    from app.database.models import PipelineStage
    stages = (db.query(PipelineStage)
              .filter(PipelineStage.workspace_id == workspace_id).all())
    if {s.id for s in stages} != set(req.ordered_ids):
        raise HTTPException(
            status_code=400,
            detail="ordered_ids must contain exactly the workspace's stage ids",
        )
    # Two-pass to avoid UNIQUE(workspace_id, position) collisions:
    # Pass 1 — move all rows to large negative positions so none clash.
    for s in stages:
        db.execute(
            text("UPDATE pipeline_stages SET position = :neg WHERE id = :id"),
            {"neg": -(s.id), "id": s.id},
        )
    db.flush()
    # Pass 2 — assign real positions.
    for i, sid in enumerate(req.ordered_ids, start=1):
        db.execute(
            text("UPDATE pipeline_stages SET position = :pos WHERE id = :id"),
            {"pos": i, "id": sid},
        )
    db.commit()
    db.expire_all()
    return {"ok": True}


@app.patch("/settings/pipeline/flags")
def update_pipeline_flags(
    req: PipelineFlagsRequest,
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_workspace_owner),
):
    import json as _json
    from app.database.models import Workspace, PipelineStage
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="workspace not found")

    def _validate(stage_id):
        if stage_id is None:
            return None
        s = db.query(PipelineStage).filter(
            PipelineStage.id == stage_id,
            PipelineStage.workspace_id == workspace_id,
        ).first()
        if not s:
            raise HTTPException(status_code=400, detail=f"stage {stage_id} not in workspace")
        return stage_id

    if req.deposited_stage_id is not None:
        ws.deposited_stage_id = _validate(req.deposited_stage_id)
    if req.member_stage_id is not None:
        ws.member_stage_id = _validate(req.member_stage_id)
    if req.conversion_stage_id is not None:
        ws.conversion_stage_id = _validate(req.conversion_stage_id)
    if req.vip_marker_phrases is not None:
        ws.vip_marker_phrases = _json.dumps([p for p in req.vip_marker_phrases if p])

    db.commit()
    return {
        "ok": True,
        "deposited_stage_id": ws.deposited_stage_id,
        "member_stage_id": ws.member_stage_id,
        "conversion_stage_id": ws.conversion_stage_id,
    }


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
        {"id": r.id, "keyword": r.keyword, "target_stage": r.target_stage,
         "target_stage_id": r.target_stage_id, "is_active": r.is_active}
        for r in rows
    ]


@app.post("/settings/keywords", status_code=201)
def settings_create_keyword(req: KeywordCreateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageKeyword, PipelineStage
    stage = db.query(PipelineStage).filter(
        PipelineStage.id == req.target_stage_id,
        PipelineStage.workspace_id == workspace_id,
    ).first()
    if not stage:
        raise HTTPException(status_code=400, detail=f"stage {req.target_stage_id} not in workspace")
    kw = StageKeyword(
        workspace_id=workspace_id, keyword=req.keyword.strip(),
        target_stage_id=req.target_stage_id, target_stage=stage.position,
    )
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return {"id": kw.id, "keyword": kw.keyword, "target_stage": kw.target_stage,
            "target_stage_id": kw.target_stage_id, "is_active": kw.is_active}


@app.patch("/settings/keywords/{kw_id}")
def settings_update_keyword(kw_id: int, req: KeywordUpdateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import StageKeyword, PipelineStage
    kw = db.query(StageKeyword).filter(StageKeyword.id == kw_id, StageKeyword.workspace_id == workspace_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="keyword not found")
    if req.keyword is not None:
        kw.keyword = req.keyword.strip()
    if req.target_stage_id is not None:
        stage = db.query(PipelineStage).filter(
            PipelineStage.id == req.target_stage_id,
            PipelineStage.workspace_id == workspace_id,
        ).first()
        if not stage:
            raise HTTPException(status_code=400, detail=f"stage {req.target_stage_id} not in workspace")
        kw.target_stage_id = req.target_stage_id
        kw.target_stage = stage.position
    if req.is_active is not None:
        kw.is_active = req.is_active
    db.commit()
    return {"id": kw.id, "keyword": kw.keyword, "target_stage": kw.target_stage,
            "target_stage_id": kw.target_stage_id, "is_active": kw.is_active}


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
        {"id": r.id, "stage": r.stage, "sequence_num": r.sequence_num,
         "message_text": r.message_text, "hours_offset": r.hours_offset}
        for r in rows
    ]


@app.patch("/settings/follow-up-templates/{tmpl_id}")
def settings_update_template(tmpl_id: int, req: FollowUpUpdateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import FollowUpTemplate
    tmpl = db.query(FollowUpTemplate).filter(FollowUpTemplate.id == tmpl_id, FollowUpTemplate.workspace_id == workspace_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="template not found")
    tmpl.message_text = req.message_text.strip()
    if req.hours_offset is not None:
        tmpl.hours_offset = req.hours_offset
    db.commit()
    return {"id": tmpl.id, "stage": tmpl.stage, "sequence_num": tmpl.sequence_num,
            "message_text": tmpl.message_text, "hours_offset": tmpl.hours_offset}


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
        {"id": r.id, "stage_num": r.stage_num, "stage_id": r.stage_id,
         "label": r.label, "text": r.text, "sort_order": r.sort_order, "is_active": r.is_active}
        for r in rows
    ]


@app.post("/settings/quick-replies", status_code=201)
def settings_create_quick_reply(req: QuickReplyCreateRequest, db: Session = Depends(get_db), _=SETTINGS_ROLES, workspace_id: int = Depends(get_workspace_id)):
    from app.database.models import QuickReply, PipelineStage
    stage = db.query(PipelineStage).filter(
        PipelineStage.id == req.stage_id,
        PipelineStage.workspace_id == workspace_id,
    ).first()
    if not stage:
        raise HTTPException(status_code=400, detail=f"stage {req.stage_id} not in workspace")
    qr = QuickReply(
        workspace_id=workspace_id, stage_id=req.stage_id, stage_num=stage.position,
        label=req.label.strip(), text=req.text.strip(), sort_order=req.sort_order,
    )
    db.add(qr)
    db.commit()
    db.refresh(qr)
    return {"id": qr.id, "stage_num": qr.stage_num, "stage_id": qr.stage_id,
            "label": qr.label, "text": qr.text, "sort_order": qr.sort_order, "is_active": qr.is_active}


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
    return {"id": qr.id, "stage_num": qr.stage_num, "stage_id": qr.stage_id,
            "label": qr.label, "text": qr.text, "sort_order": qr.sort_order, "is_active": qr.is_active}


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
