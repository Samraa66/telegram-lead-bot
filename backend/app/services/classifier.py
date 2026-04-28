"""
Contact classifier: determines the lead type based on pipeline stage and flags.

Classifications (stored as VARCHAR, never ENUM):
  new_lead   — in DB, stage 1 (just arrived, pipeline not yet started)
  warm_lead  — in DB, stage 2-6, no deposit
  vip        — in DB, member stage OR deposit confirmed
  affiliate  — manually tagged (is_affiliate=True)
  noise      — manually tagged by operator (not automatic)

Priority order: affiliate > noise > vip > warm_lead > new_lead

NOTE: noise is MANUAL ONLY. All new DMs default to new_lead; the operator
marks spam as noise from the dashboard.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import Contact


def classify_contact(
    db: Session,
    user_id: int,
    source: Optional[str],
    *,
    existing: Optional[Contact] = None,
) -> str:
    """
    Return the classification string for a contact based on their current stage.

    Called after every stage transition to keep classification in sync.
    Never call this on a brand-new contact before flush() — use the
    initial classification set in telethon_client instead.
    """
    contact = existing or db.query(Contact).filter(Contact.id == user_id).first()

    if not contact:
        return "new_lead"

    # Affiliate wins over everything
    if contact.is_affiliate:
        return "affiliate"

    # Noise is a manual operator tag — respect it regardless of stage
    if contact.classification == "noise":
        return "noise"

    stage = contact.current_stage or 1

    # VIP: deposit confirmed OR deposit_status="deposited" OR member stage
    # deposit_status is the new canonical field; deposit_confirmed is the legacy boolean.
    # Task 4.2 will consolidate these — for now both are checked.
    deposited = contact.deposit_confirmed or getattr(contact, "deposit_status", None) == "deposited"

    # When current_stage_id is set, use the is_member_stage flag on PipelineStage
    # to determine VIP status (replaces the hardcoded stage >= 7 heuristic).
    is_member = False
    stage_id = getattr(contact, "current_stage_id", None)
    if stage_id:
        from app.database.models import PipelineStage
        ps = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
        if ps:
            is_member = bool(ps.is_member_stage)
        else:
            # Fallback for legacy data: position >= 8 is member
            is_member = stage >= 8
    else:
        # Legacy path: no stage_id — use old heuristic
        is_member = stage >= 7

    if deposited or is_member:
        return "vip"

    # Warm lead: in pipeline, stages 2+, no deposit, not a member stage
    if stage >= 2:
        return "warm_lead"

    # New lead: stage 1 — just arrived, pipeline not yet advanced
    return "new_lead"
