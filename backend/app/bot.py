"""
Telegram Bot API helpers.

send_message looks up the bot token for the given workspace from the DB,
falling back to the global BOT_TOKEN env var for workspace 1.
"""

import logging
import requests

from app.config import BOT_TOKEN, DRY_RUN_SEND

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def _get_bot_token(workspace_id: int = 1) -> str:
    """Return the bot token for a workspace. Only workspace 1 falls back to .env."""
    try:
        from app.database import SessionLocal
        from app.database.models import Workspace
        db = SessionLocal()
        try:
            ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if ws and ws.bot_token:
                return ws.bot_token
        finally:
            db.close()
    except Exception:
        pass
    # .env fallback is workspace-1 only — never expose Walid's token to other workspaces
    if workspace_id == 1:
        return BOT_TOKEN
    return ""


def send_message(chat_id: int, text: str, workspace_id: int = 1) -> bool:
    """Send a text message to a Telegram chat via the Bot API."""
    if DRY_RUN_SEND:
        logger.info("DRY_RUN_SEND enabled: skipping sendMessage for chat_id=%s", chat_id)
        return True

    token = _get_bot_token(workspace_id)
    if not token:
        logger.error("No bot token available for workspace_id=%s", workspace_id)
        return False

    url = f"{TELEGRAM_API_BASE}{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        if r.status_code == 200:
            return True
        logger.warning("sendMessage failed: %s %s", r.status_code, r.text)
        return False
    except Exception as e:
        logger.exception("Error sending message: %s", e)
        return False
