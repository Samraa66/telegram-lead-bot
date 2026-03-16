"""
Application configuration loaded from environment variables.

Supports both lead tracking and signal mirroring (SOURCE_CHANNEL_ID,
DESTINATION_CHANNEL_IDS). DESTINATION_CHANNEL_IDS is a comma-separated list.
"""

import os
from typing import List

from dotenv import load_dotenv

load_dotenv()

# Telegram bot
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "").strip()

# Database: empty = SQLite for local dev
DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()

# Server port (for gunicorn/uvicorn: -b 0.0.0.0:$PORT)
PORT: str = os.getenv("PORT", "8000").strip() or "8000"

# Signal mirroring: source channel (Signal Feed) and destination VIP channels
SOURCE_CHANNEL_ID: str = os.getenv("SOURCE_CHANNEL_ID", "").strip()
_DESTINATION_RAW: str = os.getenv("DESTINATION_CHANNEL_IDS", "").strip()


def get_destination_channel_ids() -> List[str]:
    """Parse comma-separated DESTINATION_CHANNEL_IDS into a list of channel IDs."""
    if not _DESTINATION_RAW:
        return []
    return [cid.strip() for cid in _DESTINATION_RAW.split(",") if cid.strip()]


DESTINATION_CHANNEL_IDS: List[str] = get_destination_channel_ids()

# Optional lead tracking messages
WELCOME_MESSAGE: str = os.getenv(
    "WELCOME_MESSAGE",
    "Hi! Send your message to Walid to join the VIP.",
)
MESSAGE_REPLY: str = os.getenv(
    "MESSAGE_REPLY",
    "Thanks, your request was sent.",
)
