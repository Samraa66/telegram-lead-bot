"""
Provider-agnostic deposit processor.

Single function called by:
  - Manual button:        POST /contacts/{id}/deposit
  - Email-based webhook:  POST /webhook/deposit-events
  - Future PuPrime API:   call directly

Effect when a new deposit is recorded:
  - inserts a DepositEvent row (idempotency_key dedupes)
  - sets contact.deposit_status = "deposited" + deposited_at + amount + currency + source
  - moves contact to workspace.deposited_stage_id (StageHistory.moved_by="deposit_event")
  - schedules follow-ups for the new stage
  - fires Meta CAPI conversion
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import (
    Contact, DepositEvent, PipelineStage, StageHistory, Workspace,
)

logger = logging.getLogger(__name__)


class DepositResult:
    def __init__(self, *, deposit_event_id: int, contact_id: int, dedup: bool, moved_to_stage_id: Optional[int]):
        self.deposit_event_id = deposit_event_id
        self.contact_id = contact_id
        self.dedup = dedup                    # True if this idempotency_key existed
        self.moved_to_stage_id = moved_to_stage_id


def find_contact_for_deposit(
    db: Session,
    workspace_id: int,
    *,
    contact_id: Optional[int] = None,
    puprime_client_id: Optional[str] = None,
) -> Optional[Contact]:
    """Resolve a Contact by direct id or by puprime_client_id, scoped to workspace."""
    if contact_id is not None:
        return db.query(Contact).filter(
            Contact.id == contact_id, Contact.workspace_id == workspace_id,
        ).first()
    if puprime_client_id:
        return db.query(Contact).filter(
            Contact.workspace_id == workspace_id,
            Contact.puprime_client_id == str(puprime_client_id),
        ).first()
    return None


def process_deposit_event(
    db: Session,
    *,
    workspace_id: int,
    contact: Contact,
    provider: str,
    source: str,
    idempotency_key: str,
    amount: Optional[float] = None,
    currency: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    provider_client_id: Optional[str] = None,
    raw_payload: Optional[str] = None,
) -> DepositResult:
    """
    Idempotent deposit recording. Returns DepositResult with dedup=True if this
    (workspace_id, provider, idempotency_key) tuple already exists.
    """
    occurred_at = occurred_at or datetime.utcnow()

    existing = (
        db.query(DepositEvent)
        .filter(
            DepositEvent.workspace_id == workspace_id,
            DepositEvent.provider == provider,
            DepositEvent.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        return DepositResult(
            deposit_event_id=existing.id,
            contact_id=existing.contact_id,
            dedup=True,
            moved_to_stage_id=None,
        )

    event = DepositEvent(
        workspace_id=workspace_id,
        contact_id=contact.id,
        provider=provider,
        provider_client_id=str(provider_client_id) if provider_client_id is not None else None,
        amount=amount,
        currency=currency,
        occurred_at=occurred_at,
        source=source,
        idempotency_key=idempotency_key,
        raw_payload=raw_payload,
    )
    db.add(event)
    db.flush()

    is_first_time = contact.deposit_status != "deposited"
    contact.deposit_status = "deposited"
    contact.deposited_at = occurred_at
    if amount is not None:
        contact.deposit_amount = amount
    if currency:
        contact.deposit_currency = currency
    contact.deposit_source = source
    # Legacy mirror for any code still reading the old columns
    contact.deposit_confirmed = True
    contact.deposit_date = occurred_at.date()

    moved_to_stage_id: Optional[int] = None
    if is_first_time:
        moved_to_stage_id = _move_to_deposit_stage(db, contact, workspace_id, occurred_at)
        try:
            from app.services.meta_api import send_capi_conversion
            send_capi_conversion(contact.id, occurred_at)
        except Exception:
            logger.exception("CAPI fire failed for contact %s on deposit", contact.id)

    db.commit()

    logger.info(
        "deposit recorded contact=%s provider=%s amount=%s source=%s dedup=False first_time=%s",
        contact.id, provider, amount, source, is_first_time,
    )
    return DepositResult(
        deposit_event_id=event.id,
        contact_id=contact.id,
        dedup=False,
        moved_to_stage_id=moved_to_stage_id,
    )


def _move_to_deposit_stage(
    db: Session, contact: Contact, workspace_id: int, when: datetime,
) -> Optional[int]:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws or not ws.deposited_stage_id:
        logger.warning("workspace %s has no deposited_stage_id — cannot promote contact", workspace_id)
        return None
    target = db.query(PipelineStage).filter(PipelineStage.id == ws.deposited_stage_id).first()
    if not target:
        return None
    if contact.current_stage_id == target.id:
        return target.id

    from_stage_id = contact.current_stage_id
    contact.current_stage_id = target.id
    contact.stage_entered_at = when
    # Keep legacy int column in sync
    contact.current_stage = target.position

    db.add(StageHistory(
        contact_id=contact.id,
        from_stage_id=from_stage_id,
        to_stage_id=target.id,
        from_stage=None,
        to_stage=target.position,
        moved_at=when,
        moved_by="deposit_event",
        trigger_keyword=None,
    ))

    try:
        from app.services.classifier import classify_contact
        contact.classification = classify_contact(db, contact.id, contact.source, existing=contact)
    except Exception:
        pass

    try:
        from app.services.scheduler import schedule_follow_ups_for_stage_id
        schedule_follow_ups_for_stage_id(contact.id, target.id, when)
    except Exception:
        logger.exception("follow-up scheduling failed for contact %s after deposit", contact.id)

    return target.id
