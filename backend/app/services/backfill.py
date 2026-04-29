"""
Cold-start backfill: pulls past Telegram DMs via Telethon, creates Contacts,
replays each outbound through advance_stage so the keyword pipeline yields the
correct stage for each lead's history.
"""

from __future__ import annotations

import logging
from app.database import SessionLocal
from app.database.models import Contact
from app.handlers.leads import ensure_contact, record_message
from app.services.pipeline import advance_stage

logger = logging.getLogger(__name__)


async def backfill_workspace_history(workspace_id: int, *, limit_per_dialog: int = 200) -> dict:
    """
    Iterate every DM dialog of the workspace's Telethon client and replay history.

    Returns {"contacts_created": N, "messages_replayed": M, "skipped": K}.
    Idempotent — repeat calls re-touch existing contacts but the pipeline's
    no-backwards rule blocks duplicate StageHistory regression.
    """
    from app.services.telethon_client import get_client
    client = get_client(workspace_id)
    if client is None:
        return {
            "contacts_created": 0,
            "messages_replayed": 0,
            "skipped": 0,
            "error": "no telethon client for this workspace",
        }

    contacts_created = 0
    messages_replayed = 0
    skipped = 0
    db = SessionLocal()
    try:
        async for dialog in client.iter_dialogs():
            if not dialog.is_user:
                continue
            user = dialog.entity
            user_id = getattr(user, "id", None)
            if user_id is None:
                skipped += 1
                continue

            existed = (
                db.query(Contact)
                .filter(Contact.id == user_id, Contact.workspace_id == workspace_id)
                .first()
            )
            ensure_contact(
                db, user_id, getattr(user, "username", None), source=None,
                first_name=getattr(user, "first_name", None),
                last_name=getattr(user, "last_name", None),
                workspace_id=workspace_id,
            )
            if not existed:
                contacts_created += 1

            contact = (
                db.query(Contact)
                .filter(Contact.id == user_id, Contact.workspace_id == workspace_id)
                .first()
            )
            if not contact:
                skipped += 1
                continue

            # VIP-name re-detection — covers the case where the operator already
            # renamed the lead (e.g. "VIP Mike") before backfill was run.
            from app.services.pipeline import maybe_promote_to_member_stage
            maybe_promote_to_member_stage(contact, db)

            async for msg in client.iter_messages(user, limit=limit_per_dialog, reverse=True):
                if not msg.text:
                    continue
                if msg.out:
                    advance_stage(contact, msg.text, moved_by="backfill", db=db)
                else:
                    record_message(db, user_id, msg.text, direction="inbound", sender="system")
                messages_replayed += 1
    finally:
        db.close()

    logger.info(
        "backfill ws=%s contacts_created=%s messages=%s skipped=%s",
        workspace_id, contacts_created, messages_replayed, skipped,
    )
    return {
        "contacts_created": contacts_created,
        "messages_replayed": messages_replayed,
        "skipped": skipped,
    }
