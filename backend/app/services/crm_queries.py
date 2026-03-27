"""
CRM Phase 1 queries.

Used by:
- GET /contacts
- GET /contacts/{id}/messages
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import Message, User


def get_contacts(db: Session, include_noise: bool = False) -> List[Dict[str, Any]]:
    """
    List all contacts with:
    - current_stage
    - username
    - last message timestamp
    """
    last_msg_subq = (
        db.query(Message.user_id.label("user_id"), func.max(Message.timestamp).label("last_ts"))
        .group_by(Message.user_id)
        .subquery()
    )

    q = (
        db.query(
            User.id,
            User.username,
            User.current_stage,
            User.classification,
            User.notes,
            User.stage_entered_at,
            last_msg_subq.c.last_ts,
        )
        .outerjoin(last_msg_subq, User.id == last_msg_subq.c.user_id)
        .order_by(User.first_seen.desc())
    )
    if not include_noise:
        q = q.filter(User.classification != "noise")
    rows = q.all()

    result: List[Dict[str, Any]] = []
    for user_id, username, current_stage, classification, notes, stage_entered_at, last_ts in rows:
        result.append(
            {
                "id": user_id,
                "username": username,
                "current_stage": current_stage or 1,
                "classification": classification or "new_lead",
                "notes": notes or "",
                "stage_entered_at": str(stage_entered_at) if stage_entered_at else None,
                "last_message_at": str(last_ts) if last_ts else None,
            }
        )
    return result


def get_contact_messages(db: Session, contact_id: int) -> List[Dict[str, Any]]:
    """Return full inbound/outbound message history for a contact."""
    messages = (
        db.query(Message)
        .filter(Message.user_id == contact_id)
        .order_by(Message.timestamp.asc())
        .all()
    )

    result: List[Dict[str, Any]] = []
    for m in messages:
        # `content` is the CRM-friendly field; `message_text` is kept for backward compatibility.
        content = m.content if m.content is not None else m.message_text
        result.append(
            {
                "id": m.id,
                "direction": m.direction,
                "content": content,
                "sender": m.sender,
                "timestamp": str(m.timestamp) if m.timestamp else None,
            }
        )
    return result

