"""
CRM Stage Pipeline — canonical implementation.

Stage advances when the operator's OUTGOING message contains a keyword phrase
(case-insensitive substring match over normalised whitespace).

Keywords are loaded from the stage_keywords DB table (workspace_id=1).
Hardcoded STAGE_KEYWORDS is kept as a fallback for tests that run without a DB.

Multiple keyword matches in one message: highest stage wins.
Every stage change is logged to stage_history with who/when/keyword.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session, object_session

from app.database.models import Contact, Message, StageHistory, StageKeyword
from app.services.classifier import classify_contact

logger = logging.getLogger(__name__)

# Fallback used only when no DB session is available (e.g. unit tests).
STAGE_KEYWORDS: list[tuple[str, int]] = [
    ("any experience trading", 2),
    ("is there something specific holding you back", 3),
    ("your link to open your free puprime account", 4),
    ("the hard part done", 5),
    ("exactly how to get set up", 6),
    ("welcome to the vip room", 7),
    ("really happy to have you here", 8),
]


def _load_keywords(db: Session, workspace_id: int = 1) -> list[tuple[str, int]]:
    """Load active keywords from DB for the given workspace."""
    rows = (
        db.query(StageKeyword)
        .filter(StageKeyword.workspace_id == workspace_id, StageKeyword.is_active.is_(True))
        .all()
    )
    if rows:
        return [(r.keyword, r.target_stage) for r in rows]
    # DB empty or table not yet seeded — fall back to hardcoded list
    return STAGE_KEYWORDS


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for robust substring matching."""
    return " ".join((text or "").lower().split())


def infer_stage(
    message_text: str,
    keywords: Optional[list[tuple[str, int]]] = None,
) -> Optional[Tuple[int, str]]:
    """
    Return (target_stage, trigger_keyword) for the highest-stage keyword found,
    or None if no keyword matches.

    Pass `keywords` to use a custom list; omit to use the hardcoded fallback.
    """
    kw_list = keywords if keywords is not None else STAGE_KEYWORDS
    text = _normalize(message_text)
    best_stage: Optional[int] = None
    best_keyword: Optional[str] = None
    for keyword, stage in kw_list:
        if _normalize(keyword) in text:
            if best_stage is None or stage > best_stage:
                best_stage = stage
                best_keyword = keyword
    if best_stage is None:
        return None
    return best_stage, best_keyword or ""


def advance_stage(
    contact: Contact,
    message_text: str,
    *,
    moved_by: str = "system",
    db: Optional[Session] = None,
) -> Optional[int]:
    """
    Save an outbound message and advance the contact's stage if a keyword matches.

    Returns the new stage number if a transition occurred, else None.

    Args:
        contact:      Contact bound to a live SQLAlchemy session
        message_text: the outgoing message text to scan
        moved_by:     'system' (keyword-triggered) or 'operator' / 'manual'
        db:           override session; falls back to object_session(contact)
    """
    session = db or object_session(contact)
    if session is None:
        raise RuntimeError(
            "advance_stage requires contact bound to an active SQLAlchemy session"
        )

    now = datetime.utcnow()
    contact.last_seen = now

    # Always persist the outbound message
    session.add(
        Message(
            user_id=contact.id,
            message_text=message_text,
            content=message_text,
            direction="outbound",
            sender="operator",
            timestamp=now,
        )
    )

    ws_id = getattr(contact, "workspace_id", 1) or 1
    result = infer_stage(message_text, keywords=_load_keywords(session, ws_id))
    if result is None:
        session.commit()
        return None

    target_stage, keyword = result
    from_stage = contact.current_stage or 1

    # Never allow backwards stage transitions
    if target_stage <= from_stage:
        session.commit()
        return None

    if contact.current_stage != target_stage:
        contact.current_stage = target_stage
        contact.stage_entered_at = now
        session.add(
            StageHistory(
                contact_id=contact.id,
                from_stage=from_stage,
                to_stage=target_stage,
                moved_at=now,
                moved_by=moved_by,
                trigger_keyword=keyword,
            )
        )
        contact.classification = classify_contact(session, contact.id, contact.source, existing=contact)
        logger.info(
            "Stage transition: contact_id=%s %s→%s (keyword=%r, by=%s, classification=%s)",
            contact.id, from_stage, target_stage, keyword, moved_by, contact.classification,
        )
        session.commit()

        if target_stage == 7:
            try:
                from app.services.meta_api import send_capi_conversion
                send_capi_conversion(contact.id, now)
            except Exception:
                logger.exception("CAPI fire failed for contact %s", contact.id)

        return target_stage

    session.commit()
    return None


def set_stage_manual(
    contact: Contact,
    new_stage: int,
    *,
    moved_by: str = "operator",
    db: Optional[Session] = None,
) -> None:
    """
    Manually override a contact's stage.
    Always writes a stage_history row if the stage actually changes.
    """
    session = db or object_session(contact)
    if session is None:
        raise RuntimeError(
            "set_stage_manual requires contact bound to a live SQLAlchemy session"
        )

    now = datetime.utcnow()
    from_stage = contact.current_stage or 1

    if contact.current_stage != new_stage:
        contact.current_stage = new_stage
        contact.stage_entered_at = now
        session.add(
            StageHistory(
                contact_id=contact.id,
                from_stage=from_stage,
                to_stage=new_stage,
                moved_at=now,
                moved_by=moved_by,
                trigger_keyword=None,
            )
        )
        contact.classification = classify_contact(session, contact.id, contact.source, existing=contact)
        logger.info(
            "Manual stage override: contact_id=%s %s→%s (by=%s, classification=%s)",
            contact.id, from_stage, new_stage, moved_by, contact.classification,
        )
        session.commit()

        if new_stage == 7:
            try:
                from app.services.meta_api import send_capi_conversion
                send_capi_conversion(contact.id, now)
            except Exception:
                logger.exception("CAPI fire failed for contact %s", contact.id)
        return

    session.commit()
