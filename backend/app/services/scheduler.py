"""
Follow-up scheduler using APScheduler.

Fires follow-up messages only within 09:00–22:00 Dubai time (UTC+4).
If a scheduled time falls outside that window it is bumped forward to
09:00 Dubai the same day (if before window) or 09:00 next day (if after).

Timing and end-actions are driven entirely from DB rows:
  - FollowUpTemplate.hours_offset  — when to fire each follow-up
  - PipelineStage.end_action       — what to do after the last sequence ("cold" | "revert" | "weekly" | "monthly")
  - PipelineStage.revert_to_stage_id — target stage when end_action == "revert"

Follow-ups are cancelled immediately when the lead sends an inbound message.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func

from app.database import SessionLocal
from app.database.models import Contact, FollowUpQueue, FollowUpTemplate, Message, StageHistory
from app.services.classifier import classify_contact

logger = logging.getLogger(__name__)

DUBAI_TZ = timezone(timedelta(hours=4))
WINDOW_OPEN = 9    # 09:00 Dubai
WINDOW_CLOSE = 22  # 22:00 Dubai


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

def schedule_follow_ups(contact_id: int, stage_or_stage_id: int, stage_entered_at: datetime) -> None:
    """Legacy: accepts a stage_id (callers post-Task 4.1 always pass stage_id).
    Forwards to schedule_follow_ups_for_stage_id."""
    schedule_follow_ups_for_stage_id(contact_id, stage_or_stage_id, stage_entered_at)


def schedule_follow_ups_for_stage_id(contact_id: int, stage_id: int, stage_entered_at: datetime) -> None:
    """
    DB-driven follow-up scheduler keyed by stage_id (replaces the hardcoded
    _SCHEDULE dict for new code paths). Reads FollowUpTemplate rows for the
    given stage_id and schedules one FollowUpQueue row per template using
    its hours_offset. Cancels any existing pending follow-ups for the contact first.
    """
    db = SessionLocal()
    try:
        from app.database.models import PipelineStage, FollowUpTemplate
        stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
        if not stage:
            return
        templates = (
            db.query(FollowUpTemplate)
            .filter(FollowUpTemplate.stage_id == stage_id)
            .order_by(FollowUpTemplate.sequence_num)
            .all()
        )

        db.query(FollowUpQueue).filter(
            FollowUpQueue.contact_id == contact_id,
            FollowUpQueue.status == "pending",
        ).update({"status": "cancelled"})

        for tmpl in templates:
            fire_at = _bump_to_window(stage_entered_at + timedelta(hours=float(tmpl.hours_offset or 24)))
            db.add(FollowUpQueue(
                contact_id=contact_id,
                stage=stage.position,        # legacy int mirror
                stage_id=stage.id,
                sequence_num=tmpl.sequence_num,
                scheduled_at=fire_at,
                status="pending",
                template_key=f"stage{stage.position}_seq{tmpl.sequence_num}",
            ))
        db.commit()
        logger.info(
            "Scheduled %d follow-up(s) for contact_id=%s stage_id=%s",
            len(templates), contact_id, stage_id,
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

def _get_template_text(db, stage_id: int, seq_num: int, workspace_id: int = 1) -> Optional[str]:
    tmpl = (
        db.query(FollowUpTemplate)
        .filter(
            FollowUpTemplate.workspace_id == workspace_id,
            FollowUpTemplate.stage_id == stage_id,
            FollowUpTemplate.sequence_num == seq_num,
        )
        .first()
    )
    return tmpl.message_text if tmpl else None


def _end_action_for_stage_id(db, stage_id: int) -> tuple[str, Optional[int]]:
    """Return (end_action, revert_to_stage_id) for a given stage_id."""
    from app.database.models import PipelineStage
    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
    if not stage:
        return "cold", None
    return (stage.end_action or "cold"), stage.revert_to_stage_id


def _handle_post_sequence(db, contact: Contact, action: str, from_stage_id: int,
                          revert_to_stage_id: Optional[int]) -> None:
    """Execute the end-of-sequence action after the last follow-up fires."""
    from app.database.models import PipelineStage
    now = datetime.utcnow()

    if action == "cold":
        logger.info("Contact %s cold after stage_id=%s", contact.id, from_stage_id)
        return

    if action == "revert" and revert_to_stage_id:
        revert_stage = db.query(PipelineStage).filter(PipelineStage.id == revert_to_stage_id).first()
        if not revert_stage:
            logger.warning("revert target %s missing for contact %s", revert_to_stage_id, contact.id)
            return
        old_stage_id = contact.current_stage_id
        contact.current_stage_id = revert_stage.id
        contact.current_stage = revert_stage.position  # legacy mirror
        contact.stage_entered_at = now
        db.add(StageHistory(
            contact_id=contact.id,
            from_stage_id=old_stage_id, to_stage_id=revert_stage.id,
            from_stage=None, to_stage=revert_stage.position,
            moved_at=now, moved_by="system",
            trigger_keyword="follow_up_revert",
        ))
        contact.classification = classify_contact(db, contact.id, contact.source, existing=contact)
        db.commit()
        schedule_follow_ups_for_stage_id(contact.id, revert_stage.id, now)
        logger.info("Reverted contact %s to stage_id=%s position=%s",
                    contact.id, revert_stage.id, revert_stage.position)
        return

    if action in ("weekly", "monthly"):
        hours = 168 if action == "weekly" else 720
        fire_at = _bump_to_window(now + timedelta(hours=hours))
        seq_next = (
            db.query(FollowUpQueue)
            .filter(FollowUpQueue.contact_id == contact.id, FollowUpQueue.stage_id == from_stage_id)
            .count()
        ) + 1
        db.add(FollowUpQueue(
            contact_id=contact.id,
            stage_id=from_stage_id, sequence_num=seq_next,
            scheduled_at=fire_at, status="pending",
            template_key=f"recurring_{action}_seq{seq_next}",
        ))
        db.commit()
        return


_SEND_DELAY_SECONDS = 3      # pause between each follow-up send
_MAX_PER_TICK = 10           # cap sends per 5-minute tick to avoid flood


def _fire_pending_follow_ups() -> None:
    """
    APScheduler job: runs every 5 minutes.
    Fires pending follow-ups that are due AND within the Dubai window.
    Sends at most _MAX_PER_TICK per tick with a _SEND_DELAY_SECONDS gap between
    each send to avoid Telegram PeerFloodError on the operator account.
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
            .limit(_MAX_PER_TICK)
            .all()
        )

        sent_count = 0
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

            ws_id: int = getattr(contact, "workspace_id", 1) or 1
            text = _get_template_text(db, fup.stage_id, fup.sequence_num, ws_id) if fup.stage_id else None
            if text is None:
                logger.warning(
                    "No template for stage_id=%s seq=%s ws=%s — skipping follow-up id=%s",
                    fup.stage_id, fup.sequence_num, ws_id, fup.id,
                )
                continue

            # Pace sends to avoid PeerFloodError
            if sent_count > 0:
                time.sleep(_SEND_DELAY_SECONDS)

            try:
                from app.services.telethon_client import send_as_operator_sync, get_client
                from app.bot import send_message as bot_send
                sent = (
                    send_as_operator_sync(contact.id, text, ws_id)
                    if get_client(ws_id)
                    else bot_send(contact.id, text, ws_id)
                )
            except Exception as e:
                err_name = type(e).__name__
                if "PeerFlood" in err_name or "FloodWait" in err_name:
                    # Telegram rate limit — stop this tick entirely, retry next tick
                    logger.warning(
                        "Telegram flood limit hit (%s) on follow-up id=%s — stopping tick, will retry",
                        err_name, fup.id,
                    )
                    break
                logger.exception("Error sending follow-up id=%s: %s", fup.id, e)
                continue

            sent_count += 1

            if sent:
                fup.fired_at = now
                fup.status = "fired"
                db.commit()

                # Check if this was the last in the sequence → run end action
                last_seq = (
                    db.query(func.max(FollowUpTemplate.sequence_num))
                    .filter(FollowUpTemplate.stage_id == fup.stage_id)
                    .scalar()
                ) or 0
                if fup.sequence_num >= last_seq and last_seq > 0:
                    action, revert_to = _end_action_for_stage_id(db, fup.stage_id)
                    _handle_post_sequence(db, contact, action, fup.stage_id, revert_to)
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
    # Daily Meta Marketing API pull at 06:00 UTC (10:00 Dubai time)
    try:
        from app.services.meta_api import pull_campaign_insights
        _scheduler.add_job(
            pull_campaign_insights,
            "cron",
            hour=6,
            minute=0,
            id="meta_api_pull",
            max_instances=1,
        )
        logger.info("Meta API daily pull scheduled at 06:00 UTC")
    except Exception:
        logger.warning("Meta API scheduler not loaded — META_ACCESS_TOKEN may be unset")

    # Daily member activity refresh at 08:00 UTC (12:00 Dubai time)
    try:
        from app.services.member_activity import refresh_activity_statuses
        _scheduler.add_job(
            refresh_activity_statuses,
            "cron",
            hour=8,
            minute=0,
            id="member_activity_refresh",
            max_instances=1,
        )
        logger.info("Member activity refresh scheduled at 08:00 UTC")
    except Exception:
        logger.warning("Member activity scheduler not loaded")

    # Hourly affiliate channel member count sync
    try:
        from app.services.affiliate_automation import sync_channel_member_counts
        _scheduler.add_job(
            sync_channel_member_counts,
            "interval",
            hours=1,
            id="affiliate_channel_sync",
            max_instances=1,
        )
        logger.info("Affiliate channel member sync scheduled (hourly)")
    except Exception:
        logger.warning("Affiliate channel sync scheduler not loaded")

    _scheduler.start()
    logger.info("Follow-up scheduler started (5-minute tick, Dubai window %d–%d)", WINDOW_OPEN, WINDOW_CLOSE)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Follow-up scheduler stopped")
