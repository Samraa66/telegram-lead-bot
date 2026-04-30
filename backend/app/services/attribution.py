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


# resolve_attribution_channel — Task 4
# mint_invite_link — Task 5
# handle_channel_join — Task 7
# claim_pending_attribution — Task 9
# cleanup_old_join_events — Task 10
