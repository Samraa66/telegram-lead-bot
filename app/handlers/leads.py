"""
Lead tracking handler: process private chat messages from users.

Stores user_id, username, message_text, timestamp, and source campaign.
Handles /start with campaign parameter and normal messages; returns reply text.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.database.models import User, Message
from app.config import WELCOME_MESSAGE, MESSAGE_REPLY

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


def ensure_user(
    db: Session,
    user_id: int,
    username: Optional[str],
    source: Optional[str],
) -> User:
    """
    Get or create a user by Telegram user_id. Updates last_seen and optionally
    username/source. Prevents duplicates by using user_id as primary key.
    """
    user = db.query(User).filter(User.id == user_id).first()
    now = datetime.utcnow()
    if user:
        user.last_seen = now
        if username is not None:
            user.username = username
        if source is not None:
            user.source = source
        db.commit()
        db.refresh(user)
        return user
    user = User(
        id=user_id,
        username=username,
        source=source,
        first_seen=now,
        last_seen=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def record_message(db: Session, user_id: int, message_text: Optional[str]) -> Message:
    """Insert a new message for the given user."""
    msg = Message(user_id=user_id, message_text=message_text or "")
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def process_lead_update(update: dict, db: Session) -> Tuple[Optional[str], Optional[int]]:
    """
    Process one Telegram update that contains a private-chat message.
    Performs DB writes and returns (reply_text, chat_id).
    If no reply should be sent, returns (None, chat_id) or (None, None).
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
    text = message.get("text")

    if user_id is None:
        return None, chat_id

    logger.info("Received lead message from user_id=%s", user_id)

    if is_start_command(text):
        source = extract_start_source(text)
        ensure_user(db, user_id, username, source)
        return WELCOME_MESSAGE, chat_id

    # Normal message: ensure user exists (may have started without /start param)
    ensure_user(db, user_id, username, None)
    record_message(db, user_id, text)
    logger.info("Lead recorded (user_id=%s)", user_id)
    return MESSAGE_REPLY, chat_id
