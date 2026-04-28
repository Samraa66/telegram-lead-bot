"""
CRM Stage Pipeline — workspace-scoped, stage-id based.

Stage advances when the operator's OUTGOING message contains a keyword phrase
(case-insensitive substring match over normalised whitespace).

Keywords are loaded from the stage_keywords DB table, scoped to the contact's
workspace. Each keyword points at a target_stage_id (FK into pipeline_stages).
Multiple matches in one message: the keyword whose stage has the highest
position wins. Every stage change is logged to stage_history.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, object_session

from app.database.models import (
    Contact, Message, PipelineStage, StageHistory, StageKeyword, Workspace,
)
from app.services.classifier import classify_contact

logger = logging.getLogger(__name__)


def _load_keywords(db: Session, workspace_id: int = 1) -> List[Tuple[str, int]]:
    """Return active (phrase, target_stage_id) pairs for the workspace."""
    rows = (
        db.query(StageKeyword)
        .filter(
            StageKeyword.workspace_id == workspace_id,
            StageKeyword.is_active.is_(True),
            StageKeyword.target_stage_id.isnot(None),
        )
        .all()
    )
    return [(r.keyword, r.target_stage_id) for r in rows]


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def infer_stage_id(
    message_text: str,
    keywords: List[Tuple[str, int]],
) -> Optional[Tuple[int, str]]:
    """
    Return (target_stage_id, trigger_keyword) for the highest-stage_id keyword
    matched. The caller resolves the actual position to enforce monotonic
    advance ordering.
    """
    text = _normalize(message_text)
    best_id: Optional[int] = None
    best_keyword: Optional[str] = None
    for keyword, stage_id in keywords:
        if _normalize(keyword) in text:
            if best_id is None or stage_id > best_id:
                best_id = stage_id
                best_keyword = keyword
    if best_id is None:
        return None
    return best_id, best_keyword or ""


# Back-compat shim for tests / callers that still pass (phrase, stage_id) tuples.
def infer_stage(message_text, keywords=None):
    return infer_stage_id(message_text, keywords or [])


def advance_stage(
    contact: Contact,
    message_text: str,
    *,
    moved_by: str = "system",
    db: Optional[Session] = None,
) -> Optional[int]:
    """
    Scan the outbound text for a keyword match, advance the contact to the
    target stage if its position is strictly higher than the current one,
    and write a StageHistory row. Returns the new stage_id on transition,
    else None.
    """
    session = db or object_session(contact)
    if session is None:
        raise RuntimeError("advance_stage requires contact bound to a live session")

    now = datetime.utcnow()
    contact.last_seen = now

    session.add(Message(
        user_id=contact.id, message_text=message_text, content=message_text,
        direction="outbound", sender="operator", timestamp=now,
    ))

    ws_id = getattr(contact, "workspace_id", 1) or 1
    keywords = _load_keywords(session, ws_id)
    if not keywords:
        session.commit()
        return None

    text = _normalize(message_text)
    matches: List[Tuple[str, int]] = [
        (phrase, stage_id) for phrase, stage_id in keywords
        if _normalize(phrase) in text
    ]
    if not matches:
        session.commit()
        return None

    stages_in_ws = {
        s.id: s for s in
        session.query(PipelineStage).filter(PipelineStage.workspace_id == ws_id).all()
    }
    matches.sort(
        key=lambda m: stages_in_ws.get(m[1]).position if stages_in_ws.get(m[1]) else 0,
        reverse=True,
    )
    keyword, target_stage_id = matches[0]
    target = stages_in_ws.get(target_stage_id)
    if not target:
        session.commit()
        return None

    current = stages_in_ws.get(contact.current_stage_id) if contact.current_stage_id else None
    current_pos = current.position if current else 0
    if target.position <= current_pos:
        session.commit()
        return None

    from_stage_id = contact.current_stage_id
    contact.current_stage_id = target.id
    contact.current_stage = target.position  # legacy mirror
    contact.stage_entered_at = now

    session.add(StageHistory(
        contact_id=contact.id,
        from_stage_id=from_stage_id, to_stage_id=target.id,
        from_stage=current_pos or None, to_stage=target.position,
        moved_at=now, moved_by=moved_by, trigger_keyword=keyword,
    ))
    contact.classification = classify_contact(session, contact.id, contact.source, existing=contact)
    logger.info(
        "Stage transition contact_id=%s %s→%s position=%s keyword=%r by=%s",
        contact.id, from_stage_id, target.id, target.position, keyword, moved_by,
    )
    session.commit()

    ws = session.query(Workspace).filter(Workspace.id == ws_id).first()
    if ws and target.id == ws.deposited_stage_id:
        try:
            from app.services.meta_api import send_capi_conversion
            send_capi_conversion(contact.id, now)
        except Exception:
            logger.exception("CAPI fire failed for contact %s", contact.id)

    return target.id


def set_stage_manual(
    contact: Contact, new_stage_id: int,
    *, moved_by: str = "operator", db: Optional[Session] = None,
) -> None:
    """Manually move the contact to `new_stage_id`. Writes a StageHistory row
    if the stage actually changes."""
    session = db or object_session(contact)
    if session is None:
        raise RuntimeError("set_stage_manual requires contact bound to a live session")

    target = session.query(PipelineStage).filter(PipelineStage.id == new_stage_id).first()
    if not target:
        return

    now = datetime.utcnow()
    if contact.current_stage_id == target.id:
        return

    from_stage_id = contact.current_stage_id
    from_pos: Optional[int] = None
    if from_stage_id:
        prev = session.query(PipelineStage).filter(PipelineStage.id == from_stage_id).first()
        from_pos = prev.position if prev else None

    contact.current_stage_id = target.id
    contact.current_stage = target.position
    contact.stage_entered_at = now

    session.add(StageHistory(
        contact_id=contact.id,
        from_stage_id=from_stage_id, to_stage_id=target.id,
        from_stage=from_pos, to_stage=target.position,
        moved_at=now, moved_by=moved_by, trigger_keyword=None,
    ))
    contact.classification = classify_contact(session, contact.id, contact.source, existing=contact)
    logger.info(
        "Manual stage override contact_id=%s %s→%s position=%s by=%s",
        contact.id, from_stage_id, target.id, target.position, moved_by,
    )
    session.commit()

    ws = session.query(Workspace).filter(Workspace.id == (contact.workspace_id or 1)).first()
    if ws and target.id == ws.deposited_stage_id:
        try:
            from app.services.meta_api import send_capi_conversion
            send_capi_conversion(contact.id, now)
        except Exception:
            logger.exception("CAPI fire failed for contact %s", contact.id)
