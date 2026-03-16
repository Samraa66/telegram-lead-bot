"""
FastAPI application: lead tracking + signal mirroring.

- POST /webhook: receives Telegram updates; validates secret; routes message → leads,
  channel_post → signals.
- GET /stats/*: analytics for leads.
- GET /health: health check for monitoring.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from sqlalchemy.orm import Session

from app.config import WEBHOOK_SECRET
from app.database import get_db, init_db
from app.handlers.leads import process_lead_update
from app.handlers.signals import process_signal_update
from app.bot import send_message
from app.services.analytics import get_today_stats, get_stats_by_source, get_messages_per_day

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
    logger.info("Server starting; database initialized")
    yield
    logger.info("Server shutting down")


app = FastAPI(
    title="Lead Tracking & Signal Mirroring Bot API",
    description="Webhook for leads and signal mirroring; analytics for leads.",
    lifespan=lifespan,
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
        # Route by update type; run sync handlers in thread pool to avoid blocking event loop
        if body.get("message") is not None:
            reply_text, chat_id = await asyncio.to_thread(process_lead_update, body, db)
            if reply_text and chat_id is not None:
                await asyncio.to_thread(send_message, chat_id, reply_text)
            return {"ok": True}

        if body.get("channel_post") is not None or body.get("edited_channel_post") is not None:
            await asyncio.to_thread(process_signal_update, body)
            return {"ok": True}

        # Other update types (e.g. callback_query) — acknowledge and ignore
        logger.debug("Webhook update type not handled (update_id=%s); ignoring", update_id)
        return {"ok": True}
    except Exception as e:
        logger.exception("Webhook handler error (update_id=%s): %s", update_id, e)
        # Return 200 so Telegram does not retry; error is logged
        return {"ok": True}


@app.get("/stats/today")
def stats_today(db: Session = Depends(get_db)):
    """Number of users (first seen) today and number of messages today."""
    return get_today_stats(db)


@app.get("/stats/by-source")
def stats_by_source(db: Session = Depends(get_db)):
    """Lead count grouped by campaign source (start parameter)."""
    return get_stats_by_source(db)


@app.get("/stats/messages-per-day")
def stats_messages_per_day(db: Session = Depends(get_db), days: int = 30):
    """Count of messages grouped by day (default last 30 days)."""
    return get_messages_per_day(db, days=min(days, 365))


@app.get("/health")
def health():
    """Health check for deployment."""
    return {"status": "ok"}
