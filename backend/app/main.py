"""
FastAPI application: lead tracking + signal mirroring.

- POST /webhook: receives Telegram updates; validates secret; routes message → leads,
  channel_post → signals.
- GET /stats/*: analytics for leads.
- GET /health: health check for monitoring.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, conint
from sqlalchemy.orm import Session

from app.auth import authenticate_user, create_access_token, get_current_user, require_roles
from app.config import WEBHOOK_SECRET
from app.database import get_db, init_db
from app.database.models import User
from app.handlers.outbound import handle_outbound
from app.handlers.leads import process_lead_update
from app.handlers.signals import process_signal_update
from app.bot import send_message
from app.services.analytics import get_today_stats, get_stats_by_source, get_messages_per_day
from app.services.crm_queries import get_contacts, get_contact_messages
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.pipeline import set_stage_manual

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
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH, SESSION_FILE
    from app.services.telethon_client import start_telethon
    if TELEGRAM_API_ID and TELEGRAM_API_HASH:
        await start_telethon(SESSION_FILE, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    logger.info("Server starting; database initialized")
    yield
    from app.services.telethon_client import stop_telethon
    await stop_telethon()
    stop_scheduler()
    logger.info("Server shutting down")


app = FastAPI(
    title="Lead Tracking & Signal Mirroring Bot API",
    description="Webhook for leads and signal mirroring; analytics for leads.",
    lifespan=lifespan,
)

# Allow frontend (Vite/local UI) to call backend APIs from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _validate_webhook_secret(request: Request) -> bool:
    """Return True if WEBHOOK_SECRET is not set or matches the header."""
    if not WEBHOOK_SECRET:
        return True
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
    return header_secret == WEBHOOK_SECRET


@app.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """
    Telegram sends updates here. Validate secret, deserialize update,
    then route: message → leads handler, channel_post / edited_channel_post → signals handler.
    Always return 200 on valid JSON so Telegram does not retry; log errors internally.
    """
    if not _validate_webhook_secret(request):
        logger.warning("Webhook rejected: invalid or missing secret")
        return {"ok": False, "error": "forbidden"}, 403

    try:
        body = await request.json()
    except Exception as e:
        logger.warning("Webhook invalid JSON: %s", e)
        return {"ok": False, "error": "invalid json"}

    update_id = body.get("update_id", "?")
    logger.info("Webhook received (update_id=%s)", update_id)

    try:
        # Route by update type.
        #
        # IMPORTANT: lead tracking uses a synchronous SQLAlchemy session (`db`).
        # Passing that session into another thread can break DB writes (especially with SQLite).
        # So we keep DB work in this request thread, and only move outbound HTTP calls to a thread.
        if body.get("message") is not None:
            reply_text, chat_id = process_lead_update(body, db)
            if reply_text and chat_id is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, send_message, chat_id, reply_text)
            return {"ok": True}

        if body.get("channel_post") is not None or body.get("edited_channel_post") is not None:
            # Signal forwarding performs outbound HTTP calls only; safe to run in a thread.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, process_signal_update, body)
            return {"ok": True}

        # Other update types (e.g. callback_query) — acknowledge and ignore
        logger.debug("Webhook update type not handled (update_id=%s); ignoring", update_id)
        return {"ok": True}
    except Exception as e:
        logger.exception("Webhook handler error (update_id=%s): %s", update_id, e)
        # Return 200 so Telegram does not retry; error is logged
        return {"ok": True}


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(req: LoginRequest):
    """Authenticate and return a JWT token."""
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user["username"], user["role"])
    return {"access_token": token, "role": user["role"], "username": user["username"]}


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    """Return the current user's info."""
    return current_user


@app.get("/stats/today")
def stats_today(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Number of users (first seen) today and number of messages today."""
    return get_today_stats(db)


@app.get("/stats/by-source")
def stats_by_source(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Lead count grouped by campaign source (start parameter)."""
    return get_stats_by_source(db)


@app.get("/stats/messages-per-day")
def stats_messages_per_day(db: Session = Depends(get_db), days: int = 30, _=Depends(get_current_user)):
    """Count of messages grouped by day (default last 30 days)."""
    return get_messages_per_day(db, days=min(days, 365))


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
def contacts_list(include_noise: bool = False, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """List contacts. Noise contacts are excluded by default; pass ?include_noise=true to include them."""
    return get_contacts(db, include_noise=include_noise)


@app.get("/contacts/{contact_id}/messages")
def contacts_messages(contact_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Return full chat history (inbound + outbound) for a contact."""
    return get_contact_messages(db, contact_id)


@app.post("/send-message")
def send_message_to_contact(req: SendMessageRequest, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """
    Operator sends an outbound message to a contact.
    - Sends via Telegram API
    - Saves outbound message (direction=outbound) inside stage pipeline
    - Performs stage transitions based on outgoing message keywords
    """
    contact = db.query(User).filter(User.id == req.contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")

    from app.services.telethon_client import send_as_operator_sync, get_client
    if get_client():
        ok = send_as_operator_sync(contact.id, req.message)
    else:
        ok = send_message(contact.id, req.message)
    if not ok:
        raise HTTPException(status_code=502, detail="telegram send failed")

    # Outbound handler logs message, advances stage, and schedules follow-ups.
    handle_outbound(db, req.contact_id, req.message)
    return {"ok": True}


@app.post("/contacts/{contact_id}/stage")
def set_contact_stage(contact_id: int, req: ManualStageRequest, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Manually override a contact stage."""
    contact = db.query(User).filter(User.id == contact_id).first()
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
def update_contact_notes(contact_id: int, req: NotesRequest, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Save free-text notes for a contact."""
    contact = db.query(User).filter(User.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.notes = req.notes
    db.commit()
    return {"ok": True}


@app.post("/contacts/{contact_id}/escalate")
def escalate_contact(contact_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Flag a contact as escalated."""
    from datetime import datetime
    contact = db.query(User).filter(User.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact.escalated = True
    contact.escalated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


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
# Frontend static files (React dashboard)
# ---------------------------------------------------------------------------

_FRONTEND_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)

if os.path.isdir(_FRONTEND_DIST):
    _assets_dir = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        """Serve the React SPA for any route not matched by the API."""
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))
