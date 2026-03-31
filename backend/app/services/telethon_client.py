"""
Telethon MTProto client — operator account.

Runs inside the FastAPI asyncio event loop. Handles:
  - Listening for inbound DMs to the operator's Telegram account
  - Sending messages as the operator (dashboard replies + follow-ups)

Signal forwarding still uses the Bot API (bot.py / forwarding.py).

Setup: run scripts/setup_telethon.py once on the VPS to create the session file.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from telethon import TelegramClient, events
from telethon.tl.types import User

from app.database import SessionLocal
from app.database.models import Contact, Message
from app.services.classifier import classify_contact
from app.services.scheduler import cancel_follow_ups

logger = logging.getLogger(__name__)

_client: Optional[TelegramClient] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_running: bool = False


# ---------------------------------------------------------------------------
# Inbound handler
# ---------------------------------------------------------------------------

async def _on_outgoing_message(event) -> None:
    """
    Capture messages sent directly from the operator's Telegram app and run
    stage detection via handle_outbound.

    Dedup: if the same message to the same contact was already saved within
    30 seconds (i.e. sent via the /send-message endpoint), skip processing to
    avoid double stage transitions.
    """
    if not event.is_private:
        return

    peer = await event.get_chat()
    if not isinstance(peer, User):
        return

    contact_id: int = peer.id
    text: str = event.message.text or ""
    now = datetime.utcnow()

    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return

        # Dedup: skip if this exact message was already saved via /send-message
        from datetime import timedelta
        recent_cutoff = now - timedelta(seconds=30)
        already_saved = (
            db.query(Message)
            .filter(
                Message.user_id == contact_id,
                Message.direction == "outbound",
                Message.content == text,
                Message.timestamp >= recent_cutoff,
            )
            .first()
        )
        if already_saved:
            logger.debug("Outgoing message dedup skip for contact_id=%s", contact_id)
            return

        # Run stage detection — saves message + advances stage + schedules follow-ups
        from app.handlers.outbound import handle_outbound
        handle_outbound(db, contact_id, text)
        logger.info("Outgoing Telegram message processed for contact_id=%s", contact_id)
    except Exception:
        logger.exception("Error processing outgoing message for contact_id=%s", contact_id)
        db.rollback()
    finally:
        db.close()


async def _on_new_message(event) -> None:
    """Capture every inbound private DM to the operator account."""
    if not event.is_private:
        return

    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot:
        return  # ignore other bots messaging the account

    user_id: int = sender.id
    username: Optional[str] = sender.username
    text: str = event.message.text or ""
    now = datetime.utcnow()

    # Extract /start source parameter for campaign analytics (e.g. "/start meta_jan").
    # NOTE: /start is NOT used to gate lead entry — @WalidxBullish_Support is a personal
    # account, not a bot. Telegram never auto-sends /start for personal accounts.
    # Every new DM is treated as a potential lead; noise is tagged manually by the operator.
    source: Optional[str] = None
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            source = parts[1].strip()

    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == user_id).first()

        if not contact:
            # New contact — enter pipeline as new_lead at stage 1.
            contact = Contact(
                id=user_id,
                username=username,
                source=source,
                classification="new_lead",
                current_stage=1,
                stage_entered_at=now,
                first_seen=now,
                last_seen=now,
            )
            db.add(contact)
            db.flush()
            logger.info("New lead created: user_id=%s username=%s source=%s", user_id, username, source)
        else:
            contact.username = username
            contact.last_seen = now
            # Update source if we now have one (e.g. they sent /start with a param later)
            if source and not contact.source:
                contact.source = source
            # Re-classify based on current stage (handles noise → lead promotion if needed)
            contact.classification = classify_contact(
                db, user_id, contact.source, existing=contact
            )

        db.add(Message(
            user_id=user_id,
            message_text=text,
            content=text,
            direction="inbound",
            sender="contact",
            timestamp=now,
        ))
        db.commit()

        # Cancel scheduled follow-ups — operator will take over
        cancel_follow_ups(user_id)

        logger.info("Inbound message from user_id=%s stage=%s", user_id, contact.current_stage)

    except Exception:
        logger.exception("Error handling inbound message from user_id=%s", user_id)
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Outbound send
# ---------------------------------------------------------------------------

async def send_as_operator(chat_id: int, text: str) -> bool:
    """Send a message as the operator account (async)."""
    if _client is None or not _running:
        logger.error("Telethon client not running — cannot send message")
        return False
    try:
        if not _client.is_connected():
            await _client.connect()
        await _client.send_message(chat_id, text)
        return True
    except Exception:
        logger.exception("Telethon send failed for chat_id=%s", chat_id)
        return False


def send_as_operator_sync(chat_id: int, text: str) -> bool:
    """
    Thread-safe sync wrapper around send_as_operator.
    Used by the follow-up scheduler which runs in a background thread.
    """
    if _client is None or _loop is None or not _running:
        return False
    try:
        future = asyncio.run_coroutine_threadsafe(
            send_as_operator(chat_id, text), _loop
        )
        return future.result(timeout=15)
    except Exception:
        logger.exception("send_as_operator_sync failed for chat_id=%s", chat_id)
        return False


def get_client() -> Optional[TelegramClient]:
    return _client if _running else None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def start_telethon(session_file: str, api_id: int, api_hash: str) -> None:
    global _client, _loop, _running

    if not os.path.exists(session_file):
        logger.warning(
            "Telethon session file not found (%s). "
            "Run scripts/setup_telethon.py to create it.",
            session_file,
        )
        return

    _loop = asyncio.get_running_loop()
    _client = TelegramClient(
        session_file, api_id, api_hash,
        auto_reconnect=True,
        retry_delay=5,
        connection_retries=10,
    )
    _client.add_event_handler(_on_new_message, events.NewMessage(incoming=True))
    _client.add_event_handler(_on_outgoing_message, events.NewMessage(outgoing=True))

    await _client.connect()
    if not await _client.is_user_authorized():
        logger.warning(
            "Telethon session exists but is not authorized. "
            "Re-run scripts/setup_telethon.py on the server to authenticate."
        )
        await _client.disconnect()
        return

    _running = True

    me = await _client.get_me()
    logger.info(
        "Telethon client started — operator account: %s (@%s)",
        me.first_name, me.username,
    )


async def stop_telethon() -> None:
    global _running
    _running = False
    if _client:
        await _client.disconnect()
        logger.info("Telethon client stopped")
