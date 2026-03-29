"""
Contact classifier: determines the lead type for an inbound contact.

Classifications (stored as VARCHAR, never ENUM):
  new_lead   — not in DB yet and arrived via a tracked /start source
  warm_lead  — in DB, stage 1-6, no deposit confirmed, not affiliate
  vip        — in DB, stage 7-8 OR deposit confirmed
  affiliate  — manually tagged (is_affiliate=True)
  noise      — no tracked source and not already in the DB

Priority order: affiliate > vip > warm_lead > new_lead > noise
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
    Return the classification string for a contact.

    Args:
        db:       active SQLAlchemy session
        user_id:  Telegram user ID
        source:   campaign source from /start parameter (may be None)
        existing: pre-fetched Contact row to avoid an extra DB round-trip
    """
    contact = existing or db.query(Contact).filter(Contact.id == user_id).first()

    # Affiliate wins over everything
    if contact and contact.is_affiliate:
        return "affiliate"

    if contact:
        # Affiliate wins over stage-based classification
        if contact.is_affiliate:
            return "affiliate"

        # Noise contacts stay noise unless manually promoted
        if contact.classification == "noise":
            return "noise"

        stage = contact.current_stage or 1

        # VIP: deposit confirmed OR stage 7-8
        if contact.deposit_confirmed or stage >= 7:
            return "vip"

        # New lead: stage 1 (first contact, not yet qualified)
        if stage == 1:
            return "new_lead"

        # Warm lead: stage 2-6, interacting, no deposit yet
        if 2 <= stage <= 6:
            return "warm_lead"

    # Not in DB — classify by source
    if source:
        return "new_lead"

    return "noise"
