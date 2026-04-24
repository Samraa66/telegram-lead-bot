"""
Signal mirroring: copy messages from the Signal Feed channel to VIP destination channels.

Uses Telegram copy_message API so VIP channels do not display the original source.
Handles errors per channel so one failure does not stop the rest.

Destinations are the union of:
  - DESTINATION_CHANNEL_IDS from env (static, always included)
  - All active affiliate VIP channel IDs from the DB (dynamic — added when affiliates
    link their VIP channel from the dashboard)
"""

import logging
from typing import List, Optional

import requests

from app.config import BOT_TOKEN, DESTINATION_CHANNEL_IDS

logger = logging.getLogger(__name__)


def _parse_csv(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def get_static_destination_channels(workspace_id: int = 1) -> List[str]:
    """
    Return the workspace's static destination channels (user-configured via UI),
    falling back to the env DESTINATION_CHANNEL_IDS when DB is empty (workspace 1 only).
    """
    try:
        from app.database import SessionLocal
        from app.database.models import Workspace
        db = SessionLocal()
        try:
            ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if ws and ws.destination_channel_ids:
                parsed = _parse_csv(ws.destination_channel_ids)
                if parsed:
                    return parsed
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not load workspace destination channels: %s", e)
    if workspace_id == 1:
        return list(DESTINATION_CHANNEL_IDS)
    return []


def get_effective_source_channel_id(workspace_id: int = 1) -> str:
    """Return the workspace's source channel ID (DB first, env fallback for workspace 1)."""
    try:
        from app.database import SessionLocal
        from app.database.models import Workspace
        from app.config import SOURCE_CHANNEL_ID
        db = SessionLocal()
        try:
            ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if ws and ws.source_channel_id:
                return ws.source_channel_id.strip()
        finally:
            db.close()
        return SOURCE_CHANNEL_ID if workspace_id == 1 else ""
    except Exception as e:
        logger.warning("Could not load workspace source channel: %s", e)
        from app.config import SOURCE_CHANNEL_ID
        return SOURCE_CHANNEL_ID if workspace_id == 1 else ""


def get_all_destination_channels() -> List[str]:
    """
    Return the combined list of all VIP signal destinations:
    workspace static destinations (UI-configured, env fallback) + every active
    affiliate's vip_channel_id. Deduplicates.
    """
    destinations = list(get_static_destination_channels())
    try:
        from app.database import SessionLocal
        from app.database.models import Affiliate
        db = SessionLocal()
        try:
            affiliate_channels = (
                db.query(Affiliate.vip_channel_id)
                .filter(
                    Affiliate.is_active.is_(True),
                    Affiliate.vip_channel_id.isnot(None),
                )
                .all()
            )
            for (ch_id,) in affiliate_channels:
                if ch_id and ch_id not in destinations:
                    destinations.append(ch_id)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not load affiliate VIP channels for forwarding: %s", e)
    return destinations

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def copy_message(
    from_chat_id: str,
    message_id: int,
    destination_chat_id: str,
) -> bool:
    """
    Copy a message from one chat to another using Telegram Bot API.
    Works for text, photos with captions, videos, documents (no need to inspect type).
    Returns True if successful, False otherwise.
    """
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set; cannot copy message")
        return False
    url = f"{TELEGRAM_API_BASE}{BOT_TOKEN}/copyMessage"
    payload = {
        "chat_id": destination_chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("Copied signal to VIP channel %s", destination_chat_id)
            return True
        logger.error(
            "Failed copying signal to channel %s: %s %s",
            destination_chat_id,
            r.status_code,
            r.text,
        )
        return False
    except Exception as e:
        logger.exception("Error copying signal to channel %s: %s", destination_chat_id, e)
        return False


def copy_signal_to_all_destinations(
    source_channel_id: str,
    message_id: int,
    destination_channel_ids: Optional[List[str]] = None,
) -> None:
    """
    Copy the given message to each destination channel. Logs and continues
    if one channel fails so the rest are still processed.
    """
    destinations = destination_channel_ids if destination_channel_ids is not None else get_all_destination_channels()
    if not destinations:
        logger.warning("No destination channels configured; signal not copied")
        return
    for dest_id in destinations:
        ok = copy_message(
            from_chat_id=source_channel_id,
            message_id=message_id,
            destination_chat_id=dest_id,
        )
        if not ok:
            logger.error("Failed copying signal to channel %s", dest_id)
