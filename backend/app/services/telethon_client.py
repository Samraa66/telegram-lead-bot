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

    # Extract /start source parameter if present (e.g. "/start meta_jan")
    source: Optional[str] = None
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            source = parts[1].strip()

    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == user_id).first()

        if not contact:
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
        else:
            contact.username = username
            contact.last_seen = now
            if source and not contact.source:
                contact.source = source

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
    _client = TelegramClient(session_file, api_id, api_hash)
    _client.add_event_handler(_on_new_message, events.NewMessage(incoming=True))

    await _client.start()
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
