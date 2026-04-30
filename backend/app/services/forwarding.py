"""
Signal mirroring: copy messages from the Signal Feed channel to VIP destination channels.

Uses Telegram copy_message API so VIP channels do not display the original source.
Handles errors per channel so one failure does not stop the rest.

Destinations are the active affiliate VIP channel IDs scoped to the caller's org tree.
"""

import logging
from datetime import datetime
from typing import List

import requests
from sqlalchemy.orm import Session

from app.database.models import Affiliate, Workspace

logger = logging.getLogger(__name__)


def get_destinations_for_org(workspace_id: int, db: Session) -> List[str]:
    """
    Return destination channel IDs for the org rooted at workspace_id:
      - Manual destinations CSV from the owner's Workspace.destination_channel_ids
      - vip_channel_ids of all active affiliates in the org tree

    Deduplicated, preserving manual-first order so owner-configured channels
    appear before the auto-synced affiliate set.
    """
    rows = (
        db.query(Affiliate.vip_channel_id)
        .join(Workspace, Affiliate.affiliate_workspace_id == Workspace.id)
        .filter(
            Workspace.root_workspace_id == workspace_id,
            Affiliate.is_active.is_(True),
            Affiliate.vip_channel_id.isnot(None),
        )
        .all()
    )
    affiliate_channels = [ch for (ch,) in rows if ch]

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    manual_csv = (ws.destination_channel_ids if ws else None) or ""
    manual_channels = [c.strip() for c in manual_csv.split(",") if c.strip()]

    seen: set[str] = set()
    merged: List[str] = []
    for ch in manual_channels + affiliate_channels:
        if ch not in seen:
            seen.add(ch)
            merged.append(ch)
    return merged


TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def copy_message(
    from_chat_id: str,
    message_id: int,
    destination_chat_id: str,
    bot_token: str,
) -> bool:
    """
    Copy a message between chats using the given bot's token.
    Returns True on success, False on any failure (logged per-channel).
    """
    if not bot_token:
        logger.error("copy_message called with empty bot_token; cannot copy")
        return False
    url = f"{TELEGRAM_API_BASE}{bot_token}/copyMessage"
    payload = {
        "chat_id": destination_chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("Copied signal to channel %s", destination_chat_id)
            return True
        logger.error(
            "Failed copying signal to channel %s: %s %s",
            destination_chat_id, r.status_code, r.text,
        )
        return False
    except Exception as e:
        logger.exception("Error copying to channel %s: %s", destination_chat_id, e)
        return False


def copy_signal_for_org(
    workspace_id: int,
    source_chat_id: str,
    message_id: int,
    db: Session,
) -> None:
    """
    Orchestrate signal copy for one org:
      1. Fetch the org's bot_token from its workspace row
      2. Fetch destinations (active affiliates in the org tree)
      3. Loop copy_message — log per-channel failures, never abort the loop
    """
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws or not ws.bot_token:
        logger.warning(
            "copy_signal_for_org: ws=%s has no bot_token, skipping signal",
            workspace_id,
        )
        return

    destinations = get_destinations_for_org(workspace_id, db)
    if not destinations:
        logger.info(
            "copy_signal_for_org: ws=%s has no active affiliate destinations",
            workspace_id,
        )
        return

    logger.info(
        "Forwarding signal for ws=%s to %d channel(s)",
        workspace_id, len(destinations),
    )
    any_success = False
    for dest_id in destinations:
        if copy_message(
            from_chat_id=source_chat_id,
            message_id=message_id,
            destination_chat_id=dest_id,
            bot_token=ws.bot_token,
        ):
            any_success = True

    if any_success:
        ws.last_signal_forwarded_at = datetime.utcnow()
        db.commit()
