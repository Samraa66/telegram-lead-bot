"""
Phase 5 — Member Activity Monitor.

Activity status for VIP contacts (Stage 7 / 8):
  active      — last inbound message < 7 days ago
  at_risk     — no inbound message in 7–14 days  → alert brother, queue check-in
  churned     — no inbound message in 14+ days   → trigger re-engagement
  high_value  — Stage 8 (VIP Member confirmed)   → flag for Walid attention

Proxy for "trading activity": last inbound Telegram message.
PuPrime trading volume data not yet available — replace proxy when integrated.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.database.models import Contact, Message

logger = logging.getLogger(__name__)

RE_ENGAGEMENT_TEMPLATE = (
    "Hey! Just checking in — hope all is well. "
    "The signals have been performing really well lately, would love to have you back! 🚀"
)


# ---------------------------------------------------------------------------
# Status computation
# ---------------------------------------------------------------------------

def compute_activity_status(last_inbound_at: Optional[datetime], stage: int) -> str:
    """
    Derive activity status from last inbound message timestamp and stage.
    Stage 8 always = high_value regardless of activity.
    """
    if stage == 8:
        return "high_value"
    if last_inbound_at is None:
        return "churned"
    days_since = (datetime.utcnow() - last_inbound_at).total_seconds() / 86400
    if days_since < 7:
        return "active"
    elif days_since < 14:
        return "at_risk"
    else:
        return "churned"


def _last_inbound_at(db: Session, contact_id: int) -> Optional[datetime]:
    """Return the timestamp of the most recent inbound message for a contact."""
    row = (
        db.query(Message.timestamp)
        .filter(Message.user_id == contact_id, Message.direction == "inbound")
        .order_by(Message.timestamp.desc())
        .first()
    )
    return row[0] if row else None


# ---------------------------------------------------------------------------
# VIP member list
# ---------------------------------------------------------------------------

def get_vip_members(db: Session) -> list:
    """
    Return all VIP contacts (Stage 7 or 8, non-noise) with their computed
    activity status and days since last activity.
    """
    contacts = (
        db.query(Contact)
        .filter(
            Contact.current_stage.in_([7, 8]),
            Contact.classification != "noise",
        )
        .order_by(Contact.stage_entered_at.desc())
        .all()
    )

    result = []
    for c in contacts:
        last_at = _last_inbound_at(db, c.id)
        status = compute_activity_status(last_at, c.current_stage or 7)
        days_inactive = None
        if last_at:
            days_inactive = round((datetime.utcnow() - last_at).total_seconds() / 86400, 1)

        first = (c.first_name or "").strip()
        last = (c.last_name or "").strip()
        display_name = f"{first} {last}".strip() or (
            c.username.replace("@", "") if c.username else f"User {c.id}"
        )
        words = display_name.split()
        avatar = (words[0][0] + words[1][0]).upper() if len(words) >= 2 else display_name[:2].upper()

        result.append({
            "id": str(c.id),
            "name": display_name,
            "username": f"@{c.username}" if c.username else f"@user_{c.id}",
            "avatar": avatar,
            "stage": c.current_stage,
            "activity_status": status,
            "days_inactive": days_inactive,
            "last_activity_at": last_at.isoformat() if last_at else None,
            "deposit_date": c.deposit_date.isoformat() if c.deposit_date else None,
            "notes": c.notes or "",
            "classification": c.classification or "",
        })

    return result


# ---------------------------------------------------------------------------
# Re-engagement — one-tap send
# ---------------------------------------------------------------------------

def send_reengage_message(contact_id: int, text: Optional[str] = None) -> bool:
    """
    Send a re-engagement message to a VIP contact via Telethon (or bot fallback).
    Returns True on success.
    """
    message = text or RE_ENGAGEMENT_TEMPLATE
    try:
        from app.services.telethon_client import send_as_operator_sync, get_client
        from app.bot import send_message as bot_send
        if get_client():
            return send_as_operator_sync(contact_id, message)
        return bot_send(contact_id, message)
    except Exception as e:
        logger.exception("Re-engagement send failed for contact %s: %s", contact_id, e)
        return False


# ---------------------------------------------------------------------------
# Scheduler job — daily activity refresh
# ---------------------------------------------------------------------------

def refresh_activity_statuses() -> None:
    """
    Daily job: recompute activity_status for all VIP contacts and store it.
    For At Risk contacts: logs alert (brother sees them on next dashboard load).
    For Churned contacts: fires re-engagement message if not sent in last 14 days.
    """
    db = SessionLocal()
    try:
        contacts = (
            db.query(Contact)
            .filter(
                Contact.current_stage.in_([7, 8]),
                Contact.classification != "noise",
            )
            .all()
        )

        counts = {"active": 0, "at_risk": 0, "churned": 0, "high_value": 0}
        for c in contacts:
            last_at = _last_inbound_at(db, c.id)
            status = compute_activity_status(last_at, c.current_stage or 7)
            c.activity_status = status
            counts[status] += 1

            if status == "at_risk":
                logger.warning(
                    "MEMBER AT RISK: contact_id=%s name='%s %s' — no activity for 7-14 days",
                    c.id, c.first_name or "", c.last_name or "",
                )

            elif status == "churned":
                # Only re-engage if we haven't sent an outbound message in the last 14 days
                recent_outbound = (
                    db.query(Message)
                    .filter(
                        Message.user_id == c.id,
                        Message.direction == "outbound",
                        Message.timestamp >= datetime.utcnow() - timedelta(days=14),
                    )
                    .first()
                )
                if not recent_outbound:
                    logger.info("Triggering re-engagement for churned contact %s", c.id)
                    send_reengage_message(c.id)

        db.commit()
        logger.info(
            "Member activity refresh complete: %s active, %s at_risk, %s churned, %s high_value",
            counts["active"], counts["at_risk"], counts["churned"], counts["high_value"],
        )
    except Exception as e:
        logger.exception("Member activity refresh failed: %s", e)
    finally:
        db.close()
