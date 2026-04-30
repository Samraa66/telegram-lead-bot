"""
Per-campaign Telegram invite-link attribution (Spec B).

Public functions:
- resolve_attribution_channel(ws, db, client) -> int | None
- mint_invite_link(ws, campaign, db, client) -> CampaignInviteLink
- handle_channel_join(event, db) -> None
- claim_pending_attribution(contact, telegram_user_id, db) -> Optional[str]
- cleanup_old_join_events(db, *, ttl_days=90) -> int
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import (
    CampaignInviteLink, Campaign, ChannelJoinEvent, Contact, Workspace,
)

logger = logging.getLogger(__name__)

# Matches the hash suffix of a Telegram invite link.
# Accepts: https://t.me/+abc123, t.me/+abc123, https://t.me/joinchat/abc123, t.me/joinchat/abc123
_HASH_RE = re.compile(r"(?:t\.me/(?:\+|joinchat/))([A-Za-z0-9_\-]+)")


def _extract_hash(invite_link: str) -> Optional[str]:
    """Pull the hash suffix out of a Telegram invite link URL. Returns None on miss."""
    if not invite_link:
        return None
    m = _HASH_RE.search(invite_link)
    return m.group(1) if m else None


async def resolve_attribution_channel(
    ws: Workspace, db: Optional[Session], client,
) -> Optional[int]:
    """
    Return the numeric channel ID for the workspace's attribution channel.

    - Reads from cached `Workspace.attribution_channel_id` when set.
    - Otherwise resolves `main_channel_url` via Telethon, persists the result,
      and returns it.
    - Returns None when `main_channel_url` is unset or Telethon resolution fails.
    """
    if ws is None:
        return None
    if ws.attribution_channel_id:
        return int(ws.attribution_channel_id)

    url = (ws.main_channel_url or "").strip() if ws.main_channel_url else ""
    if not url:
        return None
    if client is None:
        return None

    try:
        entity = await client.get_entity(url)
    except Exception as exc:
        logger.warning("attribution: failed to resolve %s: %s", url, exc)
        return None

    chan_id = getattr(entity, "id", None)
    if not chan_id:
        return None
    chan_id = int(chan_id)

    ws.attribution_channel_id = chan_id
    if db is not None:
        db.commit()
    return chan_id


# mint_invite_link — Task 5
# handle_channel_join — Task 7
# claim_pending_attribution — Task 9
# cleanup_old_join_events — Task 10
