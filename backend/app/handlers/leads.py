"""
Lead tracking handler: process private chat messages from Telegram users.

Stores contact, records messages, classifies the contact, and cancels any
pending follow-ups when the lead replies (scheduler picks them back up on
the next stage advance).
"""

import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.database.models import Contact, Message
from app.config import WELCOME_MESSAGE, MESSAGE_REPLY
from app.services.classifier import classify_contact

logger = logging.getLogger(__name__)


def extract_start_source(text: Optional[str]) -> Optional[str]:
    """
    Extract campaign source from /start command.
    Telegram sends '/start vip' when user opens t.me/BOT?start=vip.
    """
    if not text or not text.strip().lower().startswith("/start"):
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


def is_start_command(text: Optional[str]) -> bool:
    """Return True if the message is a /start command."""
    if not text or not text.strip():
        return False
    return text.strip().lower().startswith("/start")


def ensure_contact(
    db: Session,
    user_id: int,
    username: Optional[str],
    source: Optional[str],
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    workspace_id: int = 1,
) -> Contact:
    """
    Get or create a Contact by Telegram user_id, scoped to the workspace.

    On create: sets classification via classifier, initialises stage to 1.
    On update: refreshes last_seen, updates username/source/name, re-classifies.
    """
    contact = db.query(Contact).filter(Contact.id == user_id, Contact.workspace_id == workspace_id).first()
    now = datetime.utcnow()

    if contact:
        contact.last_seen = now
        if username is not None:
            contact.username = username
        if first_name is not None:
            contact.first_name = first_name
        if last_name is not None:
            contact.last_name = last_name
        if source is not None:
            contact.source = source

        # Initialise missing defaults (rows created before CRM columns existed)
        if contact.current_stage is None:
            contact.current_stage = 1
        if contact.stage_entered_at is None:
            contact.stage_entered_at = now

        # Re-classify in case stage or deposit status changed
        contact.classification = classify_contact(
            db, user_id, contact.source, existing=contact
        )
        db.commit()
        db.refresh(contact)
        return contact

    # New contact
    classification = classify_contact(db, user_id, source)
    stage, entered_at = _vip_stage_from_name(first_name, last_name, now)
    contact = Contact(
        id=user_id,
        workspace_id=workspace_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        source=source,
        first_seen=now,
        last_seen=now,
        classification=classification,
        current_stage=stage,
        stage_entered_at=entered_at,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    if stage == 1:
        try:
            from app.services.scheduler import schedule_follow_ups
            schedule_follow_ups(user_id, 1, now)
        except Exception:
            pass
    return contact


def _vip_stage_from_name(
    first_name: Optional[str],
    last_name: Optional[str],
    now: datetime,
) -> tuple[int, datetime]:
    """Return (stage, stage_entered_at) — stage 7 if name contains 'VIP', else stage 1."""
    full = f"{first_name or ''} {last_name or ''}".lower()
    if "vip" in full:
        return 7, now
    return 1, now


# Keep the old name as an alias so any external callers still work
ensure_user = ensure_contact


def record_message(
    db: Session,
    user_id: int,
    message_text: Optional[str],
    *,
    direction: str,
    sender: str,
) -> Message:
    """Insert an inbound/outbound message for the given contact."""
    content = message_text or ""
    msg = Message(
        user_id=user_id,
        message_text=content,  # backward compatible column
        content=content,
        direction=direction,
        sender=sender,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def process_lead_update(update: dict, db: Session, workspace_id: int = 1) -> Tuple[Optional[str], Optional[int]]:
    """
    Process one Telegram update containing a private-chat message.

    Writes the contact + message to the DB, cancels pending follow-ups on reply,
    and returns (reply_text, chat_id).
    """
    message = update.get("message")
    if not message:
        return None, None

    chat_id = message.get("chat", {}).get("id")
    if chat_id is None:
        return None, None

    from_user = message.get("from") or {}
    user_id = from_user.get("id")
    username = from_user.get("username")
    first_name = from_user.get("first_name")
    last_name = from_user.get("last_name")
    text = message.get("text")

    if user_id is None:
        return None, chat_id

    logger.info("Received lead message from user_id=%s", user_id)

    if is_start_command(text):
        source = extract_start_source(text)
        ensure_contact(db, user_id, username, source, first_name, last_name, workspace_id=workspace_id)
        return WELCOME_MESSAGE, chat_id

    # Normal inbound message: ensure contact, record it, cancel follow-ups
    ensure_contact(db, user_id, username, None, first_name, last_name, workspace_id=workspace_id)
    record_message(db, user_id, text, direction="inbound", sender="system")

    # Cancel pending follow-ups — the lead replied, so the sequence resets
    try:
        from app.services.scheduler import cancel_follow_ups
        cancel_follow_ups(user_id)
    except Exception:
        pass  # Scheduler may not be running in tests; never crash the webhook

    logger.info("Lead recorded (user_id=%s)", user_id)
    return MESSAGE_REPLY, chat_id
