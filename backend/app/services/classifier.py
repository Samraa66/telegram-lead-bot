"""
Contact classifier: determines the lead type based on pipeline stage and flags.

Classifications (stored as VARCHAR, never ENUM):
  new_lead   — in DB, stage 1 (just arrived, pipeline not yet started)
  warm_lead  — in DB, stage 2-6, no deposit
  vip        — in DB, stage 7-8 OR deposit confirmed
  affiliate  — manually tagged (is_affiliate=True)
  noise      — manually tagged by operator (not automatic)

Priority order: affiliate > noise > vip > warm_lead > new_lead

NOTE: noise is MANUAL ONLY. @WalidxBullish_Support is a personal Telegram
account — Telegram never auto-sends /start for personal accounts, so we
cannot use /start to distinguish leads from random DMs. All new DMs default
to new_lead; the operator marks spam as noise from the dashboard.
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

    # VIP: deposit confirmed OR stage 7-8
    if contact.deposit_confirmed or stage >= 7:
        return "vip"

    # Warm lead: in pipeline, stages 2-6, no deposit
    if stage >= 2:
        return "warm_lead"

    # New lead: stage 1 — just arrived, pipeline not yet advanced
    return "new_lead"
