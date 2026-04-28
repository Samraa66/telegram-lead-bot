"""
Outbound handler: process a message sent by the operator to a contact.

Scans the message text for stage keywords and advances the contact's stage
via the pipeline. Also schedules follow-ups for the new stage if a transition
occurred.

Called from:
  - POST /send-message  (REST API)
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import Contact
from app.services.pipeline import advance_stage

logger = logging.getLogger(__name__)


def handle_outbound(
    db: Session,
    contact_id: int,
    message_text: str,
) -> Optional[int]:
    """
    Process an outgoing message from the operator to a contact.

    Saves the message as 'outbound' and advances the stage if a keyword is
    matched. Schedules follow-ups for the new stage when a transition occurs.

    Returns the new stage number if a transition occurred, else None.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        logger.warning("handle_outbound: contact_id=%s not found", contact_id)
        return None

    new_stage = advance_stage(contact, message_text, moved_by="system", db=db)

    if new_stage is not None:
        try:
            from app.services.scheduler import schedule_follow_ups_for_stage_id
            schedule_follow_ups_for_stage_id(contact_id, new_stage, contact.stage_entered_at)
        except Exception:
            pass  # Never crash the send path due to scheduler errors

    logger.info(
        "Outbound processed: contact_id=%s current_stage=%s new_stage=%s",
        contact_id, contact.current_stage, new_stage,
    )
    return new_stage
