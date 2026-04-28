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


def _deposit_stage_id(db: Session, workspace_id: int) -> Optional[int]:
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    return ws.deposited_stage_id if ws else None


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
    new_today = db.query(Contact).filter(
        ws_filter, Contact.classification != "noise", Contact.first_seen >= today_start,
    ).count()
    new_this_week = db.query(Contact).filter(
        ws_filter, Contact.classification != "noise", Contact.first_seen >= week_start,
    ).count()

    dep_q = db.query(Contact).filter(
        ws_filter, Contact.classification != "noise",
        Contact.deposit_status == "deposited",
    )
    if from_dt:
        dep_q = dep_q.filter(Contact.deposited_at >= from_dt)
    if to_dt:
        dep_q = dep_q.filter(Contact.deposited_at <= to_dt)
    dep_rows = dep_q.all()
    total_deposited = len(dep_rows)

    avg_days = None
    deltas = [(c.deposited_at - c.first_seen).total_seconds() / 86400
              for c in dep_rows if c.deposited_at and c.first_seen]
    if deltas:
        avg_days = round(sum(deltas) / len(deltas), 1)

    overall_conversion = round(total_deposited / total_non_noise * 100, 1) if total_non_noise else 0.0

    return {
        "total_leads": total_non_noise,
        "new_today": new_today,
        "new_this_week": new_this_week,
        "total_deposited": total_deposited,
        "overall_conversion": overall_conversion,
        "avg_days_to_deposit": avg_days,
    }


def _cohort_conversion_id(
    db: Session,
    from_id: Optional[int],
    to_id: Optional[int],
    workspace_id: int,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
) -> tuple[int, int, Optional[float]]:
    """
    Return (cohort_size, converted, rate%) for contacts who reached `from_id`
    AND later reached `to_id` (StageHistory entries).
    """
    ws_filter = Contact.workspace_id == workspace_id
    if from_id is None or to_id is None:
        return 0, 0, None
    q = (
        db.query(func.distinct(StageHistory.contact_id).label("contact_id"))
        .join(Contact, Contact.id == StageHistory.contact_id)
        .filter(ws_filter, Contact.classification != "noise",
                StageHistory.to_stage_id == from_id)
    )
    q = _date_filters(q, StageHistory.moved_at, from_dt, to_dt)
    cohort = q.subquery()
    cohort_size = db.query(func.count()).select_from(cohort).scalar() or 0
    if cohort_size == 0:
        return 0, 0, None
    converted = (
        db.query(func.count(func.distinct(StageHistory.contact_id)))
        .filter(StageHistory.contact_id.in_(db.query(cohort)),
                StageHistory.to_stage_id == to_id)
        .scalar() or 0
    )
    return cohort_size, converted, round(converted / cohort_size * 100, 1)


def get_conversion_metrics(
    db: Session,
    workspace_id: int = 1,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list:
    from app.database.models import PipelineStage, Workspace
    stages = (db.query(PipelineStage)
              .filter(PipelineStage.workspace_id == workspace_id)
              .order_by(PipelineStage.position).all())
    if not stages:
        return []
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    deposit_id = ws.deposited_stage_id if ws else None

    # Adjacent-position cohorts plus first→deposit
    cohorts: list[tuple] = [(stages[i], stages[i + 1]) for i in range(len(stages) - 1)]
    if deposit_id:
        first = stages[0]
        deposit = next((s for s in stages if s.id == deposit_id), None)
        if deposit and deposit.id != first.id:
            cohorts.append((first, deposit))

    out = []
    for src, dst in cohorts:
        f, t, rate = _cohort_conversion_id(db, src.id, dst.id, workspace_id, from_dt, to_dt)
        out.append({
            "label": f"{src.name} → {dst.name}",
            "from_entries": f, "to_entries": t, "rate": rate, "target": None,
        })
    return out


def get_stage_distribution(db: Session, workspace_id: int = 1) -> list:
    from app.database.models import PipelineStage
    stages = (db.query(PipelineStage)
              .filter(PipelineStage.workspace_id == workspace_id)
              .order_by(PipelineStage.position).all())
    counts = dict(
        db.query(Contact.current_stage_id, func.count(Contact.id))
        .filter(Contact.workspace_id == workspace_id,
                Contact.classification != "noise",
                Contact.current_stage_id.isnot(None))
        .group_by(Contact.current_stage_id).all()
    )
    return [
        {"stage_id": s.id, "position": s.position, "name": s.name,
         "is_deposit_stage": s.is_deposit_stage,
         "is_member_stage": s.is_member_stage,
         "count": counts.get(s.id, 0)}
        for s in stages
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

    deposit_id = _deposit_stage_id(db, workspace_id)

    leads_by_day = [0] * 7
    deposits_by_day = [0] * 7
    for (ts,) in lq.all():
        if ts:
            leads_by_day[(ts + timedelta(hours=4)).weekday()] += 1
    if deposit_id is not None:
        dq = (
            db.query(StageHistory.moved_at)
            .join(Contact, Contact.id == StageHistory.contact_id)
            .filter(ws_filter, Contact.classification != "noise",
                    StageHistory.to_stage_id == deposit_id, StageHistory.moved_at.isnot(None))
        )
        dq = _date_filters(dq, StageHistory.moved_at, from_dt, to_dt)
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

    dep_stage_id = _deposit_stage_id(db, workspace_id)

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
        dep_q = (
            db.query(func.count(Contact.id))
            .filter(
                Contact.workspace_id == workspace_id,
                Contact.source == aff.referral_tag,
                Contact.classification != "noise",
                Contact.deposit_status == "deposited",
            )
        )
        if dep_stage_id is not None:
            deposits = (
                db.query(func.count(func.distinct(StageHistory.contact_id)))
                .join(Contact, Contact.id == StageHistory.contact_id)
                .filter(
                    Contact.workspace_id == workspace_id,
                    Contact.source == aff.referral_tag,
                    StageHistory.to_stage_id == dep_stage_id,
                )
                .scalar() or 0
            )
        else:
            deposits = dep_q.scalar() or 0
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
