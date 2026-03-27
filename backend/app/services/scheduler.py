"""
Follow-up scheduler using APScheduler.

Fires follow-up messages only within 09:00–22:00 Dubai time (UTC+4).
If a scheduled time falls outside that window it is bumped forward to
09:00 Dubai the same day (if before window) or 09:00 next day (if after).

Per-stage follow-up sequences (hours after the contact entered that stage):

  stage 1:  +24h, +72h                     → then cold (no more follow-ups)
  stage 2:  +24h                            → then cold
  stage 3:  +48h, +120h                     → then weekly (+168h repeating)
  stage 4:  +6h, +24h, +48h                → then revert to stage 3
  stage 5:  +6h, +24h                       → then revert to stage 3
  stage 6:  +6h, +24h                       → then revert to stage 3
  stage 7:  +1h, +72h, +168h               → then monthly (+720h repeating)
  stage 8:  (no follow-ups — VIP confirmed)

Follow-ups are cancelled immediately when the lead sends an inbound message.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.database import SessionLocal
from app.database.models import Contact, FollowUpQueue, FollowUpTemplate, Message, StageHistory

logger = logging.getLogger(__name__)

DUBAI_TZ = timezone(timedelta(hours=4))
WINDOW_OPEN = 9    # 09:00 Dubai
WINDOW_CLOSE = 22  # 22:00 Dubai

# (sequence_num, hours_offset, end_action)
# end_action: "cold" | "revert3" | "weekly" | "monthly"
_SCHEDULE: dict[int, list[tuple[int, float, str]]] = {
    1: [(1, 24.0, "cold"), (2, 72.0, "cold")],
    2: [(1, 24.0, "cold")],
    3: [(1, 48.0, "weekly"), (2, 120.0, "weekly")],
    4: [(1, 6.0, "revert3"), (2, 24.0, "revert3"), (3, 48.0, "revert3")],
    5: [(1, 6.0, "revert3"), (2, 24.0, "revert3")],
    6: [(1, 6.0, "revert3"), (2, 24.0, "revert3")],
    7: [(1, 1.0, "monthly"), (2, 72.0, "monthly"), (3, 168.0, "monthly")],
    8: [],
}


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def _within_window(utc_dt: datetime) -> bool:
    """Return True if the UTC datetime falls within 09:00–22:00 Dubai."""
    aware = utc_dt.replace(tzinfo=timezone.utc) if utc_dt.tzinfo is None else utc_dt
    dubai_hour = aware.astimezone(DUBAI_TZ).hour
    return WINDOW_OPEN <= dubai_hour < WINDOW_CLOSE


def _bump_to_window(utc_dt: datetime) -> datetime:
    """
    Return a naive UTC datetime adjusted so it falls within the Dubai window.
    If before window → 09:00 Dubai same day.
    If after window  → 09:00 Dubai next day.
    """
    aware = utc_dt.replace(tzinfo=timezone.utc) if utc_dt.tzinfo is None else utc_dt
    dubai_dt = aware.astimezone(DUBAI_TZ)
    if dubai_dt.hour < WINDOW_OPEN:
        bumped = dubai_dt.replace(hour=WINDOW_OPEN, minute=0, second=0, microsecond=0)
    elif dubai_dt.hour >= WINDOW_CLOSE:
        bumped = (dubai_dt + timedelta(days=1)).replace(
            hour=WINDOW_OPEN, minute=0, second=0, microsecond=0
        )
    else:
        return utc_dt.replace(tzinfo=None) if utc_dt.tzinfo else utc_dt
    return bumped.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Public: schedule / cancel
# ---------------------------------------------------------------------------

def schedule_follow_ups(contact_id: int, stage: int, stage_entered_at: datetime) -> None:
    """
    Create FollowUpQueue rows for a contact entering a given stage.
    Cancels any existing pending follow-ups for the contact first.
    """
    db = SessionLocal()
    try:
        # Cancel stale pending follow-ups from the previous stage
        db.query(FollowUpQueue).filter(
            FollowUpQueue.contact_id == contact_id,
            FollowUpQueue.status == "pending",
        ).update({"status": "cancelled"})

        sequence = _SCHEDULE.get(stage, [])
        for seq_num, hours, _action in sequence:
            fire_at = _bump_to_window(stage_entered_at + timedelta(hours=hours))
            db.add(
                FollowUpQueue(
                    contact_id=contact_id,
                    stage=stage,
                    sequence_num=seq_num,
                    scheduled_at=fire_at,
                    status="pending",
                    template_key=f"stage{stage}_seq{seq_num}",
                )
            )
        db.commit()
        logger.info(
            "Scheduled %d follow-up(s) for contact_id=%s stage=%s",
            len(sequence), contact_id, stage,
        )
    finally:
        db.close()


def cancel_follow_ups(contact_id: int) -> None:
    """Cancel all pending follow-ups for a contact (called when they reply)."""
    db = SessionLocal()
    try:
        updated = (
            db.query(FollowUpQueue)
            .filter(
                FollowUpQueue.contact_id == contact_id,
                FollowUpQueue.status == "pending",
            )
            .update({"status": "cancelled"})
        )
        db.commit()
        if updated:
            logger.info(
                "Cancelled %d pending follow-up(s) for contact_id=%s (reply received)",
                updated, contact_id,
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler job
# ---------------------------------------------------------------------------

def _get_template_text(db, stage: int, seq_num: int) -> str:
    tmpl = (
        db.query(FollowUpTemplate)
        .filter(FollowUpTemplate.stage == stage, FollowUpTemplate.sequence_num == seq_num)
        .first()
    )
    return tmpl.message_text if tmpl else f"[Follow-up: stage {stage}, attempt {seq_num}]"


def _end_action_for(stage: int, seq_num: int) -> str:
    """Return the end_action string for a given stage + sequence_num."""
    for sn, _h, action in _SCHEDULE.get(stage, []):
        if sn == seq_num:
            return action
    return "cold"


def _handle_post_sequence(db, contact: Contact, action: str, from_stage: int) -> None:
    """Execute the end-of-sequence action after the last follow-up fires."""
    now = datetime.utcnow()

    if action == "cold":
        logger.info("Contact %s cold after stage %s sequence", contact.id, from_stage)

    elif action == "revert3":
        old_stage = contact.current_stage
        contact.current_stage = 3
        contact.stage_entered_at = now
        db.add(
            StageHistory(
                contact_id=contact.id,
                from_stage=old_stage,
                to_stage=3,
                moved_at=now,
                moved_by="system",
                trigger_keyword="follow_up_revert",
            )
        )
        db.commit()
        schedule_follow_ups(contact.id, 3, now)
        logger.info("Reverted contact %s to stage 3", contact.id)

    elif action == "weekly":
        fire_at = _bump_to_window(now + timedelta(hours=168))
        seq_next = (
            db.query(FollowUpQueue)
            .filter(FollowUpQueue.contact_id == contact.id, FollowUpQueue.stage == from_stage)
            .count()
        ) + 1
        db.add(
            FollowUpQueue(
                contact_id=contact.id,
                stage=from_stage,
                sequence_num=seq_next,
                scheduled_at=fire_at,
                status="pending",
                template_key=f"stage{from_stage}_seq{seq_next}",
            )
        )
        db.commit()

    elif action == "monthly":
        fire_at = _bump_to_window(now + timedelta(hours=720))
        seq_next = (
            db.query(FollowUpQueue)
            .filter(FollowUpQueue.contact_id == contact.id, FollowUpQueue.stage == from_stage)
            .count()
        ) + 1
        db.add(
            FollowUpQueue(
                contact_id=contact.id,
                stage=from_stage,
                sequence_num=seq_next,
                scheduled_at=fire_at,
                status="pending",
                template_key=f"stage{from_stage}_seq{seq_next}",
            )
        )
        db.commit()


def _fire_pending_follow_ups() -> None:
    """
    APScheduler job: runs every 5 minutes.
    Fires all pending follow-ups that are due AND within the Dubai window.
    Skips any where the contact has replied since the follow-up was scheduled.
    """
    now = datetime.utcnow()
    if not _within_window(now):
        return  # Outside window — do nothing this tick

    db = SessionLocal()
    try:
        due = (
            db.query(FollowUpQueue)
            .filter(
                FollowUpQueue.status == "pending",
                FollowUpQueue.scheduled_at <= now,
            )
            .all()
        )

        for fup in due:
            # Skip if lead replied after the follow-up was scheduled
            replied = (
                db.query(Message)
                .filter(
                    Message.user_id == fup.contact_id,
                    Message.direction == "inbound",
                    Message.timestamp >= fup.scheduled_at,
                )
                .first()
            )
            if replied:
                fup.status = "cancelled"
                db.commit()
                continue

            contact = db.query(Contact).filter(Contact.id == fup.contact_id).first()
            if not contact:
                fup.status = "cancelled"
                db.commit()
                continue

            text = _get_template_text(db, fup.stage, fup.sequence_num)

            try:
                from app.bot import send_message
                sent = send_message(contact.id, text)
            except Exception as e:
                logger.exception("Error sending follow-up id=%s: %s", fup.id, e)
                continue

            if sent:
                fup.fired_at = now
                fup.status = "fired"
                db.commit()

                # Check if this was the last in the sequence → run end action
                stage_seq = _SCHEDULE.get(fup.stage, [])
                max_seq = max((sn for sn, _, _ in stage_seq), default=0)
                if fup.sequence_num >= max_seq and max_seq > 0:
                    action = _end_action_for(fup.stage, max_seq)
                    _handle_post_sequence(db, contact, action, fup.stage)
            else:
                logger.warning("Telegram send failed for follow-up id=%s", fup.id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

_scheduler: Optional[BackgroundScheduler] = None


def start_scheduler() -> None:
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _fire_pending_follow_ups,
        "interval",
        minutes=5,
        id="follow_up_tick",
        max_instances=1,
    )
    _scheduler.start()
    logger.info("Follow-up scheduler started (5-minute tick, Dubai window %d–%d)", WINDOW_OPEN, WINDOW_CLOSE)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Follow-up scheduler stopped")
