"""
CRM Phase 1 queries.

Used by:
- GET /contacts
- GET /contacts/{id}/messages
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import Message, User


def get_contacts(db: Session, workspace_id: int = 1, include_noise: bool = False) -> List[Dict[str, Any]]:
    """List all contacts with current_stage, username, and last message timestamp."""
    last_msg_subq = (
        db.query(Message.user_id.label("user_id"), func.max(Message.timestamp).label("last_ts"))
        .group_by(Message.user_id)
        .subquery()
    )

    q = (
        db.query(
            User.id,
            User.username,
            User.first_name,
            User.last_name,
            User.current_stage,
            User.classification,
            User.notes,
            User.stage_entered_at,
            last_msg_subq.c.last_ts,
        )
        .filter(User.workspace_id == workspace_id)
        .outerjoin(last_msg_subq, User.id == last_msg_subq.c.user_id)
        .order_by(User.first_seen.desc())
    )
    if not include_noise:
        q = q.filter(User.classification != "noise")
        # Exclude VIP/deposited contacts from the regular leads list
        from app.database.models import Workspace
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        exclude_ids = []
        if ws:
            if ws.deposited_stage_id:
                exclude_ids.append(ws.deposited_stage_id)
            if ws.member_stage_id:
                exclude_ids.append(ws.member_stage_id)
        if exclude_ids:
            q = q.filter(~User.current_stage_id.in_(exclude_ids))
        q = q.filter(User.deposit_status != "deposited")
    rows = q.all()

    result: List[Dict[str, Any]] = []
    for user_id, username, first_name, last_name, current_stage, classification, notes, stage_entered_at, last_ts in rows:
        result.append(
            {
                "id": user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
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
