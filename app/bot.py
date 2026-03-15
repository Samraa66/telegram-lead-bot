"""
Telegram Bot API helpers.

Provides send_message for lead replies. copy_message is in services/forwarding
so signal mirroring stays in the forwarding layer.
"""

import logging
import requests

from app.config import BOT_TOKEN

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def send_message(chat_id: int, text: str) -> bool:
    """Send a text message to a Telegram chat via the Bot API."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set; cannot send message")
        return False
    url = f"{TELEGRAM_API_BASE}{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True
        logger.warning("sendMessage failed: %s %s", r.status_code, r.text)
        return False
    except Exception as e:
        logger.exception("Error sending message: %s", e)
        return False
