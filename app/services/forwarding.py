"""
Signal mirroring: copy messages from the Signal Feed channel to VIP destination channels.

Uses Telegram copy_message API so VIP channels do not display the original source.
Handles errors per channel so one failure does not stop the rest.
"""

import logging
from typing import List, Optional

import requests

from app.config import BOT_TOKEN, DESTINATION_CHANNEL_IDS

logger = logging.getLogger(__name__)

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
    destinations = destination_channel_ids or DESTINATION_CHANNEL_IDS
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
