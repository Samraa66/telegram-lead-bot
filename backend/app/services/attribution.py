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


async def handle_channel_join(event, db: Session) -> None:
    """
    Process a Telethon ChatAction join event. Pure async function — does not
    depend on a live Telethon instance, so tests can call it with synthetic
    event objects.

    Records a ChannelJoinEvent row for any join into a workspace's attribution
    channel. Organic joins (no invite link) are recorded with source_tag=NULL
    so we keep channel-growth analytics; attributed joins resolve the campaign
    via invite_link_hash → CampaignInviteLink.source_tag.
    """
    chat_id = getattr(event, "chat_id", None)
    user_id = getattr(event, "user_id", None)
    if not chat_id or not user_id:
        return

    ws = db.query(Workspace).filter(
        Workspace.attribution_channel_id == int(chat_id)
    ).first()
    if not ws:
        return  # not our attribution channel for any workspace

    invite_link_hash = None
    source_tag = None

    action_message = getattr(event, "action_message", None)
    action = getattr(action_message, "action", None) if action_message else None
    invite = getattr(action, "invite", None) if action else None
    link = getattr(invite, "link", None) if invite else None

    if link:
        invite_link_hash = _extract_hash(link)
        if invite_link_hash:
            row = (
                db.query(CampaignInviteLink)
                  .filter_by(workspace_id=ws.id, invite_link_hash=invite_link_hash)
                  .first()
            )
            if row:
                source_tag = row.source_tag

    db.add(ChannelJoinEvent(
        workspace_id=ws.id,
        telegram_user_id=int(user_id),
        channel_id=int(chat_id),
        source_tag=source_tag,
        invite_link_hash=invite_link_hash,
        joined_at=datetime.utcnow(),
    ))
    db.commit()


def claim_pending_attribution(
    contact: Contact, *, telegram_user_id: int, db: Session, workspace_id: int,
) -> Optional[str]:
    """
    Look up the most recent unclaimed, attributed ChannelJoinEvent for this
    user in this workspace and copy its source_tag onto the contact.

    Returns the claimed source_tag (string) on success, or None if there's
    nothing to claim.

    Caller (ensure_contact) is responsible for committing.
    """
    pending = (
        db.query(ChannelJoinEvent)
          .filter(
              ChannelJoinEvent.workspace_id == workspace_id,
              ChannelJoinEvent.telegram_user_id == telegram_user_id,
              ChannelJoinEvent.source_tag.isnot(None),
              ChannelJoinEvent.claimed_contact_id.is_(None),
          )
          .order_by(ChannelJoinEvent.joined_at.desc())
          .first()
    )
    if not pending:
        return None

    contact.source_tag = pending.source_tag
    contact.source = pending.source_tag       # legacy mirror
    contact.entry_path = "public_channel"
    pending.claimed_contact_id = contact.id
    pending.claimed_at = datetime.utcnow()
    return pending.source_tag


def cleanup_old_join_events(db: Session, *, ttl_days: int = 90) -> int:
    """
    Delete unclaimed ChannelJoinEvent rows older than ttl_days.
    Claimed rows are kept indefinitely (they're part of contact attribution audit).
    Returns the number of rows deleted.
    """
    cutoff = datetime.utcnow() - timedelta(days=ttl_days)
    deleted = (
        db.query(ChannelJoinEvent)
          .filter(
              ChannelJoinEvent.joined_at < cutoff,
              ChannelJoinEvent.claimed_contact_id.is_(None),
          )
          .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)
