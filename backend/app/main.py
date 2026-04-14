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

from app.auth import authenticate_user, create_access_token, get_current_user, require_roles, require_affiliate
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
        try:
            await start_telethon(SESSION_FILE, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        except Exception:
            logger.exception(
                "Telethon failed to start — server will run without it. "
                "Re-run scripts/setup_telethon.py to fix the session."
            )
    logger.info("Server starting; database initialized")
    yield
    from app.services.telethon_client import stop_telethon
    await stop_telethon()
    stop_scheduler()
    logger.info("Server shutting down")


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Lead Tracking & Signal Mirroring Bot API",
    description="Webhook for leads and signal mirroring; analytics for leads.",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

        # Bot added to / removed from a channel — store as pending channel for affiliate linking
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
                    # Also check if already linked to an affiliate
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
@limiter.limit("5/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token. Checks env-based roles and DB affiliates."""
    user = authenticate_user(req.username, req.password, db=db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(
        user["username"], user["role"],
        affiliate_id=user.get("affiliate_id"),
    )
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


def _parse_date_range(from_date: Optional[str], to_date: Optional[str]):
    """Parse ISO date strings (YYYY-MM-DD) into UTC datetimes. Returns (from_dt, to_dt)."""
    from datetime import datetime as dt
    from_dt = dt.strptime(from_date, "%Y-%m-%d") if from_date else None
    to_dt = dt.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if to_date else None
    return from_dt, to_dt


@app.get("/analytics/overview")
def analytics_overview(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_overview(db, from_dt, to_dt)


@app.get("/analytics/conversions")
def analytics_conversions(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_conversion_metrics(db, from_dt, to_dt)


@app.get("/analytics/stage-distribution")
def analytics_stage_distribution(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Current stage distribution — always reflects live state, no date filter."""
    return get_stage_distribution(db)


@app.get("/analytics/hourly-heatmap")
def analytics_hourly_heatmap(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_hourly_heatmap(db, from_dt, to_dt)


@app.get("/analytics/day-of-week")
def analytics_day_of_week(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_day_of_week(db, from_dt, to_dt)


@app.get("/analytics/leads-over-time")
def analytics_leads_over_time(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    days: int = 30, db: Session = Depends(get_db), _=Depends(get_current_user),
):
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_leads_over_time(db, from_dt, to_dt, days=min(days, 365))


@app.get("/analytics/campaigns")
def analytics_campaigns(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Campaign performance: spend, CPL, CPD per Meta campaign, optionally date-filtered."""
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_campaign_performance(db, from_dt, to_dt)


@app.get("/analytics/campaigns/flags")
def analytics_campaign_flags(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Campaigns flagged as underperforming (CPD > 200 EUR for 3+ consecutive days)."""
    return get_underperforming_campaigns(db)


@app.get("/analytics/campaigns/creatives")
def analytics_creatives(
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Ad creative leaderboard — aggregated by ad, sorted by CPD ascending (best first)."""
    from_dt, to_dt = _parse_date_range(from_date, to_date)
    return get_best_performing_creatives(db, from_dt, to_dt)


@app.get("/analytics/alerts")
def analytics_alerts(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Active ad performance alerts: spend threshold, CPL > €3, CPD > €150."""
    return get_campaign_alerts(db)


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
    _=Depends(require_roles("developer", "admin")),
):
    """Create a tracked campaign and return the Telegram deep link."""
    import uuid
    from app.database.models import Campaign
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

    link = f"https://t.me/{BOT_USERNAME}?start={source_tag}" if BOT_USERNAME else None
    return {
        "id": campaign.id,
        "source_tag": source_tag,
        "name": campaign.name,
        "meta_campaign_id": campaign.meta_campaign_id,
        "link": link,
        "created_at": campaign.created_at.isoformat(),
    }


@app.get("/campaigns")
def list_campaigns(
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """List all tracked campaigns with their attribution stats."""
    from app.database.models import Campaign, Contact, StageHistory
    from app.config import BOT_USERNAME

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
        result.append({
            "id": c.id,
            "source_tag": c.source_tag,
            "name": c.name,
            "meta_campaign_id": c.meta_campaign_id,
            "link": link,
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
    Used exclusively for quick-reply template sends from the dashboard.
    Talal's day-to-day conversations happen natively in Telegram; the Telethon
    outgoing listener detects those messages and advances stages automatically.

    - Telethon path: listener fires after send and calls handle_outbound there.
    - Bot API fallback: listener won't fire, so handle_outbound is called here.
    """
    contact = db.query(User).filter(User.id == req.contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")

    from app.services.telethon_client import send_as_operator_sync, get_client
    used_telethon = False
    if get_client():
        ok = send_as_operator_sync(contact.id, req.message)
        used_telethon = ok
    else:
        ok = send_message(contact.id, req.message)
    if not ok:
        raise HTTPException(status_code=502, detail="telegram send failed")

    # Only call handle_outbound directly when using the bot API fallback.
    # When Telethon sent the message, the outgoing listener handles it instead
    # (avoids double stage detection).
    if not used_telethon:
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


@app.post("/contacts/{contact_id}/deposit-confirm")
def confirm_deposit(
    contact_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin", "operator", "vip_manager")),
):
    """Mark deposit as confirmed and auto-promote contact to stage 8."""
    from datetime import datetime, date
    contact = db.query(User).filter(User.id == contact_id).first()
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
def mark_as_noise(contact_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Mark a contact as noise (spam/unrelated). Removes them from the lead pipeline."""
    contact = db.query(User).filter(User.id == contact_id).first()
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
    return get_vip_members(db)


@app.post("/members/{contact_id}/reengage")
def reengage_member(
    contact_id: int,
    req: ReengageRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin", "vip_manager")),
):
    """Send a one-tap re-engagement message to a VIP member."""
    contact = db.query(User).filter(User.id == contact_id).first()
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
        }
        for a in affiliates
    ]


@app.post("/affiliates")
def create_affiliate(
    req: CreateAffiliateRequest,
    db: Session = Depends(get_db),
    _=Depends(require_roles("developer", "admin")),
):
    """Register a new affiliate and generate a unique referral tag."""
    import uuid
    from app.database.models import Affiliate
    from app.config import BOT_USERNAME

    from app.auth import generate_password, hash_password
    referral_tag = "ref_" + uuid.uuid4().hex[:8]
    login_username = "aff_" + uuid.uuid4().hex[:8]
    plain_password = generate_password()

    affiliate = Affiliate(
        name=req.name.strip(),
        username=req.username.strip() if req.username else None,
        referral_tag=referral_tag,
        commission_rate=req.commission_rate,
        login_username=login_username,
        login_password_hash=hash_password(plain_password),
    )
    db.add(affiliate)
    db.commit()
    db.refresh(affiliate)

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
