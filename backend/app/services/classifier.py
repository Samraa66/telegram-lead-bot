"""
Contact classifier: determines the lead type based on pipeline stage flags and deposit status.

Classifications (stored as VARCHAR, never ENUM):
  new_lead   — no stage assigned, or stage at position 1
  warm_lead  — in pipeline at position >= 2, no deposit, not a member stage
  vip        — deposit_status="deposited" OR current stage has is_member_stage=True
  affiliate  — manually tagged (is_affiliate=True)
  noise      — manually tagged by operator (not automatic)

Priority order: affiliate > noise > vip > warm_lead > new_lead

NOTE: noise is MANUAL ONLY. All new DMs default to new_lead; the operator
marks spam as noise from the dashboard.

VIP and warm_lead are determined purely by PipelineStage flags (is_member_stage,
position) and Contact.deposit_status. The legacy deposit_confirmed boolean and
integer current_stage field are no longer consulted.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import Contact


def classify_contact(
    db: Session,
    contact_id: int,
    source: Optional[str],
    *,
    existing: Optional[Contact] = None,
) -> str:
    """
    Return the classification string for a contact based on deposit_status and
    their current PipelineStage flags.

    Called after every stage transition to keep classification in sync.
    Never call this on a brand-new contact before flush() — use the
    initial classification set in telethon_client instead.
    """
    from app.database.models import PipelineStage

    contact = existing or db.query(Contact).filter(Contact.id == contact_id).first()

    if not contact:
        return "new_lead"

    # Affiliate wins over everything
    if contact.is_affiliate:
        return "affiliate"

    # Noise is a manual operator tag — respect it regardless of stage
    if contact.classification == "noise":
        return "noise"

    # Deposited contacts are always VIP, regardless of which stage they currently sit in.
    if contact.deposit_status == "deposited":
        return "vip"

    # Members (people in the explicit member-stage) are VIP too.
    if contact.current_stage_id:
        stage = db.query(PipelineStage).filter(PipelineStage.id == contact.current_stage_id).first()
        if stage:
            if stage.is_member_stage:
                return "vip"
            if stage.position >= 2:
                return "warm_lead"

    return "new_lead"
