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

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from telethon.tl.functions.messages import ExportChatInviteRequest

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
    - Returns None when `main_channel_url` is unset, `client` is None, or
      Telethon resolution fails.
    """
    if ws is None:
        return None
    if ws.attribution_channel_id is not None:
        return int(ws.attribution_channel_id)

    url = (ws.main_channel_url or "").strip() if ws.main_channel_url else ""
    if not url:
        return None
    if client is None:
        return None

    try:
        entity = await client.get_entity(url)
    except Exception as exc:
        logger.warning("attribution: failed to resolve %s: %s", url, exc, exc_info=True)
        return None

    chan_id = getattr(entity, "id", None)
    if chan_id is None:
        return None
    chan_id = int(chan_id)

    ws.attribution_channel_id = chan_id
    if db is not None:
        db.commit()
    return chan_id


async def mint_invite_link(
    ws: Workspace, campaign: Campaign, db: Session, client, *, channel_id: int,
) -> Optional[CampaignInviteLink]:
    """
    Return the CampaignInviteLink for (workspace, campaign), minting one via
    Telethon's ExportChatInviteRequest if it doesn't exist yet.

    Idempotent — repeat calls reuse the cached row. Returns None if Telethon
    fails (rate limit, kicked from channel, etc.); caller should surface 502.
    """
    existing = (
        db.query(CampaignInviteLink)
          .filter_by(
              workspace_id=ws.id, campaign_id=campaign.id, channel_id=channel_id,
          )
          .filter(CampaignInviteLink.revoked_at.is_(None))
          .first()
    )
    if existing is not None:
        return existing

    try:
        # Telegram caps invite-link title at 32 chars.
        result = await client(ExportChatInviteRequest(
            peer=channel_id,
            title=(campaign.name or campaign.source_tag or "campaign")[:32],
        ))
    except Exception as exc:
        logger.warning(
            "attribution: ExportChatInviteRequest failed for ws=%s campaign=%s (id=%s): %s",
            ws.id, campaign.source_tag, campaign.id, exc, exc_info=True,
        )
        return None

    link = getattr(result, "link", None)
    if not link:
        return None

    invite_hash = _extract_hash(link)
    if not invite_hash:
        logger.warning("attribution: could not extract hash from %r", link)
        return None

    row = CampaignInviteLink(
        workspace_id=ws.id,
        campaign_id=campaign.id,
        source_tag=campaign.source_tag,
        channel_id=channel_id,
        invite_link=link,
        invite_link_hash=invite_hash,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(CampaignInviteLink)
              .filter_by(
                  workspace_id=ws.id, campaign_id=campaign.id, channel_id=channel_id,
              )
              .first()
        )
        return existing
    db.refresh(row)
    return row


# handle_channel_join — Task 7
# claim_pending_attribution — Task 9
# cleanup_old_join_events — Task 10
