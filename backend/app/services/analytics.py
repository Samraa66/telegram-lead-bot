"""
Analytics queries for lead and message metrics.

All functions accept workspace_id=1 to scope data per tenant.
AdCampaign / AdCreative tables don't carry workspace_id yet — those queries
are unscoped for now and will be wired up once the second workspace goes live.
"""

from datetime import date as date_type, datetime, timedelta
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import AdCampaign, AdCreative, Affiliate, Contact, Message, StageHistory


def get_today_stats(db: Session, workspace_id: int = 1) -> dict:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    users_today = (
        db.query(Contact)
        .filter(Contact.workspace_id == workspace_id, Contact.first_seen >= today_start)
        .count()
    )
    messages_today = (
        db.query(Message)
        .join(Contact, Contact.id == Message.user_id)
        .filter(
            Contact.workspace_id == workspace_id,
            Message.timestamp >= today_start,
            (Message.direction == "inbound") | (Message.direction.is_(None)),
        )
        .count()
    )
    return {"users_today": users_today, "messages_today": messages_today}


def get_stats_by_source(db: Session, workspace_id: int = 1) -> list:
    rows = (
        db.query(Contact.source, func.count(Contact.id).label("count"))
        .filter(Contact.workspace_id == workspace_id)
        .group_by(Contact.source)
        .all()
    )
    return [{"source": (source or "unknown"), "count": count} for source, count in rows]


def get_messages_per_day(db: Session, workspace_id: int = 1, days: int = 30) -> list:
    since = (datetime.utcnow() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(func.date(Message.timestamp).label("day"), func.count(Message.id).label("count"))
        .join(Contact, Contact.id == Message.user_id)
        .filter(
            Contact.workspace_id == workspace_id,
            Message.timestamp >= since,
            (Message.direction == "inbound") | (Message.direction.is_(None)),
        )
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
    if from_dt:
        q = q.filter(timestamp_col >= from_dt)
    if to_dt:
        q = q.filter(timestamp_col <= to_dt)
    return q


def _entries_at_stage(
    db: Session,
    stage: int,
    total_non_noise: int,
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> int:
    ws_filter = Contact.workspace_id == workspace_id
    if stage == 1:
        if from_dt is None and to_dt is None:
            return total_non_noise
        q = db.query(func.count(Contact.id)).filter(ws_filter, Contact.classification != "noise")
        q = _date_filters(q, Contact.first_seen, from_dt, to_dt)
        return q.scalar() or 0
    q = (
        db.query(func.count(func.distinct(StageHistory.contact_id)))
        .join(Contact, Contact.id == StageHistory.contact_id)
        .filter(ws_filter, Contact.classification != "noise", StageHistory.to_stage == stage)
    )
    q = _date_filters(q, StageHistory.moved_at, from_dt, to_dt)
    return q.scalar() or 0


def get_overview(
    db: Session,
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> dict:
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    ws_filter = Contact.workspace_id == workspace_id

    total_non_noise = db.query(Contact).filter(ws_filter, Contact.classification != "noise").count()

    new_today = (
        db.query(Contact)
        .filter(ws_filter, Contact.classification != "noise", Contact.first_seen >= today_start)
        .count()
    )
    new_this_week = (
        db.query(Contact)
        .filter(ws_filter, Contact.classification != "noise", Contact.first_seen >= week_start)
        .count()
    )

    stage1_in_range = _entries_at_stage(db, 1, total_non_noise, workspace_id, from_dt, to_dt)
    stage7_q = (
        db.query(func.count(func.distinct(StageHistory.contact_id)))
        .join(Contact, Contact.id == StageHistory.contact_id)
        .filter(
            ws_filter,
            Contact.classification != "noise",
            StageHistory.to_stage == 7,
            StageHistory.trigger_keyword != "vip_name_detected",
        )
    )
    stage7_q = _date_filters(stage7_q, StageHistory.moved_at, from_dt, to_dt)
    stage7_in_range = stage7_q.scalar() or 0
    overall_conversion = round(stage7_in_range / stage1_in_range * 100, 1) if stage1_in_range > 0 else 0.0

    avg_days_to_deposit: Optional[float] = None
    try:
        q = (
            db.query(StageHistory.moved_at, Contact.first_seen)
            .join(Contact, Contact.id == StageHistory.contact_id)
            .filter(
                ws_filter,
                Contact.classification != "noise",
                StageHistory.to_stage == 7,
                StageHistory.trigger_keyword != "vip_name_detected",
            )
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


def _cohort_conversion(
    db: Session,
    from_stage: int,
    to_stage: int,
    workspace_id: int,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
) -> tuple[int, int, Optional[float]]:
    ws_filter = Contact.workspace_id == workspace_id
    if from_stage == 1:
        q = db.query(Contact.id).filter(ws_filter, Contact.classification != "noise")
        q = _date_filters(q, Contact.first_seen, from_dt, to_dt)
    else:
        q = (
            db.query(func.distinct(StageHistory.contact_id).label("contact_id"))
            .join(Contact, Contact.id == StageHistory.contact_id)
            .filter(ws_filter, Contact.classification != "noise", StageHistory.to_stage == from_stage)
        )
        q = _date_filters(q, StageHistory.moved_at, from_dt, to_dt)

    cohort_subq = q.subquery()
    cohort_size = db.query(func.count()).select_from(cohort_subq).scalar() or 0
    if cohort_size == 0:
        return 0, 0, None

    converted = (
        db.query(func.count(func.distinct(StageHistory.contact_id)))
        .filter(
            StageHistory.contact_id.in_(db.query(cohort_subq)),
            StageHistory.to_stage == to_stage,
            StageHistory.trigger_keyword != "vip_name_detected",
        )
        .scalar() or 0
    )

    rate = round(converted / cohort_size * 100, 1)
    return cohort_size, converted, rate


def get_conversion_metrics(
    db: Session,
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    f1, t2, r12 = _cohort_conversion(db, 1, 2, workspace_id, from_dt, to_dt)
    f2, t4, r24 = _cohort_conversion(db, 2, 4, workspace_id, from_dt, to_dt)
    f4, t5, r45 = _cohort_conversion(db, 4, 5, workspace_id, from_dt, to_dt)
    f5, t7, r57 = _cohort_conversion(db, 5, 7, workspace_id, from_dt, to_dt)
    f1b, t7b, r17 = _cohort_conversion(db, 1, 7, workspace_id, from_dt, to_dt)

    return [
        {"label": "Stage 1 → 2", "from_entries": f1,  "to_entries": t2,  "rate": r12, "target": 40},
        {"label": "Stage 2 → 4", "from_entries": f2,  "to_entries": t4,  "rate": r24, "target": 50},
        {"label": "Stage 4 → 5", "from_entries": f4,  "to_entries": t5,  "rate": r45, "target": 60},
        {"label": "Stage 5 → 7", "from_entries": f5,  "to_entries": t7,  "rate": r57, "target": 60},
        {"label": "Overall 1 → 7", "from_entries": f1b, "to_entries": t7b, "rate": r17, "target": 10},
    ]


def get_stage_distribution(db: Session, workspace_id: int = 1) -> list:
    current_rows = (
        db.query(Contact.current_stage, func.count(Contact.id).label("cnt"))
        .filter(Contact.workspace_id == workspace_id, Contact.classification != "noise", Contact.current_stage.isnot(None))
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
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    q = (
        db.query(Message.timestamp)
        .join(Contact, Contact.id == Message.user_id)
        .filter(
            Contact.workspace_id == workspace_id,
            Message.direction == "inbound",
            Message.timestamp.isnot(None),
        )
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
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    ws_filter = Contact.workspace_id == workspace_id
    lq = (
        db.query(Contact.first_seen)
        .filter(ws_filter, Contact.classification != "noise", Contact.first_seen.isnot(None))
    )
    lq = _date_filters(lq, Contact.first_seen, from_dt, to_dt)

    dq = (
        db.query(StageHistory.moved_at)
        .join(Contact, Contact.id == StageHistory.contact_id)
        .filter(ws_filter, Contact.classification != "noise", StageHistory.to_stage == 7, StageHistory.moved_at.isnot(None))
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
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    days: int = 30,
) -> list:
    if from_dt is None:
        from_dt = (datetime.utcnow() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    q = (
        db.query(func.date(Contact.first_seen).label("day"), func.count(Contact.id).label("count"))
        .filter(Contact.workspace_id == workspace_id, Contact.classification != "noise", Contact.first_seen >= from_dt)
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
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
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
                "spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "deposits": 0,
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
        result.append({**c, "spend": round(c["spend"], 2), "cpl": cpl, "cpd": cpd})

    return sorted(result, key=lambda x: x["spend"], reverse=True)


def get_underperforming_campaigns(db: Session, workspace_id: int = 1) -> list:
    cutoff = date_type.today() - timedelta(days=30)
    rows = (
        db.query(AdCampaign)
        .filter(AdCampaign.date >= cutoff)
        .order_by(AdCampaign.campaign_id, AdCampaign.date)
        .all()
    )

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


def get_campaign_alerts(db: Session, workspace_id: int = 1) -> list:
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
                "type": "spend", "severity": "warning", "campaign_name": name,
                "message": f"Daily spend €{row.spend:.2f} exceeds threshold €{ALERT_DAILY_SPEND_THRESHOLD:.0f}",
                "value": round(row.spend, 2), "threshold": ALERT_DAILY_SPEND_THRESHOLD,
            })
        if cpl is not None and cpl > ALERT_CPL_THRESHOLD:
            alerts.append({
                "type": "cpl", "severity": "warning", "campaign_name": name,
                "message": f"CPL €{cpl:.2f} exceeds threshold €{ALERT_CPL_THRESHOLD:.0f}",
                "value": round(cpl, 2), "threshold": ALERT_CPL_THRESHOLD,
            })
        if cpd is not None and cpd > ALERT_CPD_THRESHOLD:
            alerts.append({
                "type": "cpd", "severity": "critical", "campaign_name": name,
                "message": f"CPD €{cpd:.2f} exceeds threshold €{ALERT_CPD_THRESHOLD:.0f}",
                "value": round(cpd, 2), "threshold": ALERT_CPD_THRESHOLD,
            })

    return alerts


def get_best_performing_creatives(
    db: Session,
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
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
                "ad_id": row.ad_id, "ad_name": row.ad_name or row.ad_id,
                "campaign_id": row.campaign_id, "campaign_name": row.campaign_name or row.campaign_id,
                "spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "deposits": 0,
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

    return sorted(result, key=lambda x: (x["cpd"] is None, x["cpd"] or 0, -x["spend"]))


# ---------------------------------------------------------------------------
# Phase 6: Affiliate Dashboard
# ---------------------------------------------------------------------------

def get_affiliate_performance(db: Session, workspace_id: int = 1) -> list:
    from app.config import BOT_USERNAME
    from app.database.models import Workspace

    affiliates = (
        db.query(Affiliate)
        .filter(Affiliate.workspace_id == workspace_id, Affiliate.is_active.is_(True))
        .order_by(Affiliate.created_at)
        .all()
    )

    # Bulk-load each affiliate's own workspace so we can derive connection state
    aff_ws_ids = [a.affiliate_workspace_id for a in affiliates if a.affiliate_workspace_id]
    ws_by_id: dict = {}
    if aff_ws_ids:
        rows = db.query(Workspace).filter(Workspace.id.in_(aff_ws_ids)).all()
        ws_by_id = {w.id: w for w in rows}

    result = []
    for aff in affiliates:
        aff_ws = ws_by_id.get(aff.affiliate_workspace_id) if aff.affiliate_workspace_id else None
        has_bot_token = bool(aff_ws and aff_ws.bot_token)
        has_conversion_desk = bool(aff_ws and aff_ws.telethon_session)
        leads = (
            db.query(func.count(Contact.id))
            .filter(
                Contact.workspace_id == workspace_id,
                Contact.source == aff.referral_tag,
                Contact.classification != "noise",
            )
            .scalar() or 0
        )
        deposits = (
            db.query(func.count(func.distinct(StageHistory.contact_id)))
            .join(Contact, Contact.id == StageHistory.contact_id)
            .filter(
                Contact.workspace_id == workspace_id,
                Contact.source == aff.referral_tag,
                StageHistory.to_stage == 7,
            )
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
            "esim_done": bool(aff.esim_done),
            "free_channel_id": aff.free_channel_id,
            "free_channel_members": aff.free_channel_members or 0,
            "bot_setup_done": bool(aff.bot_setup_done),
            "vip_channel_id": aff.vip_channel_id,
            "vip_channel_members": aff.vip_channel_members or 0,
            "tutorial_channel_id": aff.tutorial_channel_id,
            "tutorial_channel_members": aff.tutorial_channel_members or 0,
            "sales_scripts_done": bool(aff.sales_scripts_done),
            "ib_profile_id": aff.ib_profile_id,
            "ads_live": bool(aff.ads_live),
            "pixel_setup_done": bool(aff.pixel_setup_done),
            # Derived — reflects real workspace state, always in sync with onboarding/settings
            "has_bot_token": has_bot_token,
            "has_conversion_desk": has_conversion_desk,
        })

    return sorted(result, key=lambda x: (x["deposits"], x["leads"]), reverse=True)
