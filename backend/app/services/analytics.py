"""
Analytics queries for lead and message metrics.

Provides data for the /stats/* API endpoints: today counts, by-source breakdown,
and messages per day. Uses the Contact model (table: contacts).
"""

from datetime import date as date_type, datetime, timedelta
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import AdCampaign, AdCreative, Affiliate, Contact, Message, StageHistory


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


# ---------------------------------------------------------------------------
# Phase 3: Funnel Analytics
# ---------------------------------------------------------------------------

STAGE_LABELS = [
    "New Lead",
    "Qualified",
    "Hesitant / Ghosting",
    "Link Sent",
    "Account Created",
    "Deposit Intent",
    "Deposited",
    "VIP Member",
]

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _date_filters(q, timestamp_col, from_dt: Optional[datetime], to_dt: Optional[datetime]):
    """Apply optional from/to date filters to a query on a timestamp column."""
    if from_dt:
        q = q.filter(timestamp_col >= from_dt)
    if to_dt:
        q = q.filter(timestamp_col <= to_dt)
    return q


def _entries_at_stage(
    db: Session,
    stage: int,
    total_non_noise: int,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> int:
    """
    Count of non-noise contacts that entered a given stage within the date range.
    Stage 1: contacts first_seen in range.
    Stage 2-8: stage_history rows with to_stage = N and moved_at in range.
    """
    if stage == 1:
        if from_dt is None and to_dt is None:
            return total_non_noise
        q = db.query(func.count(Contact.id)).filter(Contact.classification != "noise")
        q = _date_filters(q, Contact.first_seen, from_dt, to_dt)
        return q.scalar() or 0
    q = (
        db.query(func.count(func.distinct(StageHistory.contact_id)))
        .join(Contact, Contact.id == StageHistory.contact_id)
        .filter(Contact.classification != "noise", StageHistory.to_stage == stage)
    )
    q = _date_filters(q, StageHistory.moved_at, from_dt, to_dt)
    return q.scalar() or 0


def get_overview(
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> dict:
    """
    Header cards filtered to the selected date range:
    - total leads entered in range
    - new today / this week (always relative to now, ignores range)
    - total deposited in range
    - overall 1→7 conversion rate
    - average days to deposit
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    # Total non-noise (unfiltered, for relative context)
    total_non_noise = db.query(Contact).filter(Contact.classification != "noise").count()

    new_today = (
        db.query(Contact)
        .filter(Contact.classification != "noise", Contact.first_seen >= today_start)
        .count()
    )
    new_this_week = (
        db.query(Contact)
        .filter(Contact.classification != "noise", Contact.first_seen >= week_start)
        .count()
    )

    # Range-scoped entries
    stage1_in_range = _entries_at_stage(db, 1, total_non_noise, from_dt, to_dt)
    stage7_in_range = _entries_at_stage(db, 7, total_non_noise, from_dt, to_dt)
    overall_conversion = round(stage7_in_range / stage1_in_range * 100, 1) if stage1_in_range > 0 else 0.0

    avg_days_to_deposit: Optional[float] = None
    try:
        q = (
            db.query(StageHistory.moved_at, Contact.first_seen)
            .join(Contact, Contact.id == StageHistory.contact_id)
            .filter(Contact.classification != "noise", StageHistory.to_stage == 7)
        )
        q = _date_filters(q, StageHistory.moved_at, from_dt, to_dt)
        rows = q.all()
        if rows:
            deltas = [(r.moved_at - r.first_seen).total_seconds() / 86400 for r in rows if r.moved_at and r.first_seen]
            avg_days_to_deposit = round(sum(deltas) / len(deltas), 1) if deltas else None
    except Exception:
        pass

    return {
        "total_leads": stage1_in_range,
        "new_today": new_today,
        "new_this_week": new_this_week,
        "total_deposited": stage7_in_range,
        "overall_conversion": overall_conversion,
        "avg_days_to_deposit": avg_days_to_deposit,
    }


def get_conversion_metrics(
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    """
    The 5 spec conversion metrics, optionally scoped to a date range.
    Stage 1 entries = contacts first_seen in range.
    Stage N entries = stage_history moved_at in range with to_stage = N.
    """
    total_non_noise = db.query(Contact).filter(Contact.classification != "noise").count()
    e = {s: _entries_at_stage(db, s, total_non_noise, from_dt, to_dt) for s in [1, 2, 4, 5, 7]}

    def rate(num: int, den: int) -> Optional[float]:
        if den == 0:
            return None
        return round(num / den * 100, 1)

    return [
        {"label": "Stage 1 → 2", "from_entries": e[1], "to_entries": e[2], "rate": rate(e[2], e[1]), "target": 40},
        {"label": "Stage 2 → 4", "from_entries": e[2], "to_entries": e[4], "rate": rate(e[4], e[2]), "target": 50},
        {"label": "Stage 4 → 5", "from_entries": e[4], "to_entries": e[5], "rate": rate(e[5], e[4]), "target": 60},
        {"label": "Stage 5 → 7", "from_entries": e[5], "to_entries": e[7], "rate": rate(e[7], e[5]), "target": 60},
        {"label": "Overall 1 → 7", "from_entries": e[1], "to_entries": e[7], "rate": rate(e[7], e[1]), "target": 10},
    ]


def get_stage_distribution(db: Session) -> list:
    """Current contact count at each stage (non-noise). Not date-filtered — reflects live state."""
    current_rows = (
        db.query(Contact.current_stage, func.count(Contact.id).label("cnt"))
        .filter(Contact.classification != "noise", Contact.current_stage.isnot(None))
        .group_by(Contact.current_stage)
        .all()
    )
    current_map: dict[int, int] = {stage: cnt for stage, cnt in current_rows}
    return [
        {"stage": i, "label": STAGE_LABELS[i - 1], "count": current_map.get(i, 0)}
        for i in range(1, 9)
    ]


def get_hourly_heatmap(
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    """Inbound message count by hour of day (Dubai time), optionally date-filtered."""
    q = db.query(Message.timestamp).filter(
        Message.direction == "inbound", Message.timestamp.isnot(None)
    )
    q = _date_filters(q, Message.timestamp, from_dt, to_dt)
    rows = q.all()
    counts = [0] * 24
    for (ts,) in rows:
        if ts:
            counts[(ts.hour + 4) % 24] += 1
    return [{"hour": h, "count": counts[h]} for h in range(24)]


def get_day_of_week(
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    """New leads and deposits by day of week (Dubai time), optionally date-filtered."""
    lq = db.query(Contact.first_seen).filter(
        Contact.classification != "noise", Contact.first_seen.isnot(None)
    )
    lq = _date_filters(lq, Contact.first_seen, from_dt, to_dt)

    dq = (
        db.query(StageHistory.moved_at)
        .join(Contact, Contact.id == StageHistory.contact_id)
        .filter(Contact.classification != "noise", StageHistory.to_stage == 7, StageHistory.moved_at.isnot(None))
    )
    dq = _date_filters(dq, StageHistory.moved_at, from_dt, to_dt)

    leads_by_day = [0] * 7
    deposits_by_day = [0] * 7
    for (ts,) in lq.all():
        if ts:
            leads_by_day[(ts + timedelta(hours=4)).weekday()] += 1
    for (ts,) in dq.all():
        if ts:
            deposits_by_day[(ts + timedelta(hours=4)).weekday()] += 1

    return [{"day": DAY_NAMES[i], "leads": leads_by_day[i], "deposits": deposits_by_day[i]} for i in range(7)]


def get_leads_over_time(
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    days: int = 30,
) -> list:
    """New leads per day. Uses from_dt/to_dt if provided, otherwise last N days."""
    if from_dt is None:
        from_dt = (datetime.utcnow() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    q = (
        db.query(func.date(Contact.first_seen).label("day"), func.count(Contact.id).label("count"))
        .filter(Contact.classification != "noise", Contact.first_seen >= from_dt)
    )
    if to_dt:
        q = q.filter(Contact.first_seen <= to_dt)
    q = q.group_by(func.date(Contact.first_seen)).order_by(func.date(Contact.first_seen))
    return [{"date": str(day), "count": count} for day, count in q.all()]


# ---------------------------------------------------------------------------
# Phase 4: Ad Intelligence
# ---------------------------------------------------------------------------

def get_campaign_performance(
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    """
    Aggregate ad_campaigns rows by campaign, optionally scoped to a date range.
    Returns spend, impressions, clicks, leads, deposits, CPL, CPD per campaign.
    """
    q = db.query(AdCampaign)
    if from_dt:
        q = q.filter(AdCampaign.date >= from_dt.date())
    if to_dt:
        q = q.filter(AdCampaign.date <= to_dt.date())

    rows = q.all()
    campaigns: dict[str, dict] = {}
    for row in rows:
        if row.campaign_id not in campaigns:
            campaigns[row.campaign_id] = {
                "campaign_id": row.campaign_id,
                "campaign_name": row.campaign_name or row.campaign_id,
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "leads": 0,
                "deposits": 0,
            }
        c = campaigns[row.campaign_id]
        c["spend"] += row.spend
        c["impressions"] += row.impressions
        c["clicks"] += row.clicks
        c["leads"] += row.leads
        c["deposits"] += row.deposits

    result = []
    for c in campaigns.values():
        cpl = round(c["spend"] / c["leads"], 2) if c["leads"] > 0 else None
        cpd = round(c["spend"] / c["deposits"], 2) if c["deposits"] > 0 else None
        result.append({
            **c,
            "spend": round(c["spend"], 2),
            "cpl": cpl,
            "cpd": cpd,
        })

    return sorted(result, key=lambda x: x["spend"], reverse=True)


def get_underperforming_campaigns(db: Session) -> list:
    """
    Flag campaigns where cost-per-deposit (CPD) exceeds 200 EUR
    for 3 or more consecutive days in the last 30 days.
    """
    cutoff = date_type.today() - timedelta(days=30)
    rows = (
        db.query(AdCampaign)
        .filter(AdCampaign.date >= cutoff)
        .order_by(AdCampaign.campaign_id, AdCampaign.date)
        .all()
    )

    # Group daily rows by campaign
    by_campaign: dict[str, list] = {}
    for row in rows:
        by_campaign.setdefault(row.campaign_id, []).append(row)

    flagged = []
    for campaign_id, daily_rows in by_campaign.items():
        consecutive = 0
        worst_cpd = 0.0
        for row in daily_rows:
            cpd = (row.spend / row.deposits) if row.deposits > 0 else 0.0
            if cpd > 200:
                consecutive += 1
                worst_cpd = max(worst_cpd, cpd)
            else:
                consecutive = 0
                worst_cpd = 0.0

            if consecutive >= 3:
                flagged.append({
                    "campaign_id": campaign_id,
                    "campaign_name": row.campaign_name or campaign_id,
                    "consecutive_days": consecutive,
                    "latest_cpd": round(worst_cpd, 2),
                })
                break

    return flagged


def get_campaign_alerts(db: Session) -> list:
    """
    Returns active alerts based on yesterday's campaign data:
    - Daily spend exceeds ALERT_DAILY_SPEND_THRESHOLD
    - CPL exceeds ALERT_CPL_THRESHOLD (€3)
    - CPD exceeds ALERT_CPD_THRESHOLD (€150)
    """
    from app.config import ALERT_DAILY_SPEND_THRESHOLD, ALERT_CPL_THRESHOLD, ALERT_CPD_THRESHOLD

    yesterday = date_type.today() - timedelta(days=1)
    rows = db.query(AdCampaign).filter(AdCampaign.date == yesterday).all()

    alerts = []
    for row in rows:
        name = row.campaign_name or row.campaign_id
        cpl = (row.spend / row.leads) if row.leads > 0 else None
        cpd = (row.spend / row.deposits) if row.deposits > 0 else None

        if row.spend > ALERT_DAILY_SPEND_THRESHOLD:
            alerts.append({
                "type": "spend",
                "severity": "warning",
                "campaign_name": name,
                "message": f"Daily spend €{row.spend:.2f} exceeds threshold €{ALERT_DAILY_SPEND_THRESHOLD:.0f}",
                "value": round(row.spend, 2),
                "threshold": ALERT_DAILY_SPEND_THRESHOLD,
            })
        if cpl is not None and cpl > ALERT_CPL_THRESHOLD:
            alerts.append({
                "type": "cpl",
                "severity": "warning",
                "campaign_name": name,
                "message": f"CPL €{cpl:.2f} exceeds threshold €{ALERT_CPL_THRESHOLD:.0f}",
                "value": round(cpl, 2),
                "threshold": ALERT_CPL_THRESHOLD,
            })
        if cpd is not None and cpd > ALERT_CPD_THRESHOLD:
            alerts.append({
                "type": "cpd",
                "severity": "critical",
                "campaign_name": name,
                "message": f"CPD €{cpd:.2f} exceeds threshold €{ALERT_CPD_THRESHOLD:.0f}",
                "value": round(cpd, 2),
                "threshold": ALERT_CPD_THRESHOLD,
            })

    return alerts


def get_best_performing_creatives(
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    """
    Aggregate AdCreative rows by ad_id and return sorted by CPD ascending (best first).
    Creatives with no deposits are listed last.
    """
    q = db.query(AdCreative)
    if from_dt:
        q = q.filter(AdCreative.date >= from_dt.date())
    if to_dt:
        q = q.filter(AdCreative.date <= to_dt.date())

    rows = q.all()
    creatives: dict[str, dict] = {}
    for row in rows:
        if row.ad_id not in creatives:
            creatives[row.ad_id] = {
                "ad_id": row.ad_id,
                "ad_name": row.ad_name or row.ad_id,
                "campaign_id": row.campaign_id,
                "campaign_name": row.campaign_name or row.campaign_id,
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "leads": 0,
                "deposits": 0,
            }
        c = creatives[row.ad_id]
        c["spend"] += row.spend
        c["impressions"] += row.impressions
        c["clicks"] += row.clicks
        c["leads"] += row.leads
        c["deposits"] += row.deposits

    result = []
    for c in creatives.values():
        cpl = round(c["spend"] / c["leads"], 2) if c["leads"] > 0 else None
        cpd = round(c["spend"] / c["deposits"], 2) if c["deposits"] > 0 else None
        result.append({**c, "spend": round(c["spend"], 2), "cpl": cpl, "cpd": cpd})

    # Sort: creatives with deposits first (by CPD asc), then no-deposit creatives by spend desc
    return sorted(result, key=lambda x: (x["cpd"] is None, x["cpd"] or 0, -x["spend"]))


# ---------------------------------------------------------------------------
# Phase 6: Affiliate Dashboard
# ---------------------------------------------------------------------------

def get_affiliate_performance(db: Session) -> list:
    """
    For each active affiliate: count attributed leads and deposits via contact.source,
    compute conversion rate and commission earned (lots_traded × commission_rate).
    Sorted by deposits descending (leaderboard order).
    """
    from app.config import BOT_USERNAME

    affiliates = db.query(Affiliate).filter(Affiliate.is_active.is_(True)).order_by(Affiliate.created_at).all()
    result = []
    for aff in affiliates:
        leads = (
            db.query(func.count(Contact.id))
            .filter(Contact.source == aff.referral_tag, Contact.classification != "noise")
            .scalar() or 0
        )
        deposits = (
            db.query(func.count(func.distinct(StageHistory.contact_id)))
            .join(Contact, Contact.id == StageHistory.contact_id)
            .filter(Contact.source == aff.referral_tag, StageHistory.to_stage == 7)
            .scalar() or 0
        )
        conversion_rate = round(deposits / leads * 100, 1) if leads > 0 else 0.0
        commission_earned = round(aff.lots_traded * aff.commission_rate, 2)
        referral_link = (
            f"https://t.me/{BOT_USERNAME}?start={aff.referral_tag}" if BOT_USERNAME else None
        )
        result.append({
            "id": aff.id,
            "name": aff.name,
            "username": aff.username,
            "referral_tag": aff.referral_tag,
            "referral_link": referral_link,
            "leads": leads,
            "deposits": deposits,
            "conversion_rate": conversion_rate,
            "lots_traded": aff.lots_traded,
            "commission_rate": aff.commission_rate,
            "commission_earned": commission_earned,
            "is_active": aff.is_active,
            "created_at": aff.created_at.isoformat() if aff.created_at else None,
        })

    return sorted(result, key=lambda x: (x["deposits"], x["leads"]), reverse=True)
