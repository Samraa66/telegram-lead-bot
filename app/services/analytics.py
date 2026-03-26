"""
Analytics queries for lead and message metrics.

Provides data for the /stats/* API endpoints: today counts, by-source breakdown,
and messages per day. Uses the Contact model (table: contacts).
"""

from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import Contact, Message


def get_today_stats(db: Session) -> dict:
    """Number of contacts first seen today and number of inbound messages today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    users_today = db.query(Contact).filter(Contact.first_seen >= today_start).count()
    messages_today = (
        db.query(Message)
        .filter(Message.timestamp >= today_start)
        .filter((Message.direction == "inbound") | (Message.direction.is_(None)))
        .count()
    )
    return {
        "users_today": users_today,
        "messages_today": messages_today,
    }


def get_stats_by_source(db: Session) -> list:
    """Lead count grouped by campaign source (from /start parameter)."""
    rows = (
        db.query(Contact.source, func.count(Contact.id).label("count"))
        .group_by(Contact.source)
        .all()
    )
    return [
        {"source": (source if source else "unknown"), "count": count}
        for source, count in rows
    ]


def get_messages_per_day(db: Session, days: int = 30) -> list:
    """Count of inbound messages grouped by day (UTC). Returns up to `days` recent days."""
    since = datetime.utcnow() - timedelta(days=days)
    since = since.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(func.date(Message.timestamp).label("day"), func.count(Message.id).label("count"))
        .filter(Message.timestamp >= since)
        .filter((Message.direction == "inbound") | (Message.direction.is_(None)))
        .group_by(func.date(Message.timestamp))
        .order_by(func.date(Message.timestamp))
        .all()
    )
    return [{"date": str(day), "count": count} for day, count in rows]
