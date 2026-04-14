"""
Meta Marketing API + Conversions API (CAPI) service.

pull_campaign_insights()  — daily cron: fetches spend/impressions/clicks per campaign
                            from the Meta Marketing API and upserts into ad_campaigns.

send_capi_conversion()    — fires a 'Purchase' conversion event to Meta Pixel via CAPI
                            when a contact reaches Stage 7.

Both functions are no-ops when credentials are not configured, so the app runs
normally in local dev without Meta keys.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func

from app.config import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_PIXEL_ID
from app.database import SessionLocal
from app.database.models import AdCampaign, AdCreative, Contact, StageHistory

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _graph_get(path: str, params: dict) -> dict:
    """GET request to the Meta Graph API. Returns parsed JSON or empty dict on failure."""
    params["access_token"] = META_ACCESS_TOKEN
    query = urllib.parse.urlencode(params)
    url = f"{GRAPH_BASE}/{path}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error("Meta Graph API GET failed (%s): %s", path, e)
        return {}


def _graph_post(path: str, payload: dict) -> dict:
    """POST request to the Meta Graph API. Returns parsed JSON or empty dict on failure."""
    payload["access_token"] = META_ACCESS_TOKEN
    data = json.dumps(payload).encode()
    url = f"{GRAPH_BASE}/{path}"
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error("Meta Graph API POST failed (%s): %s", path, e)
        return {}


# ---------------------------------------------------------------------------
# Marketing API pull
# ---------------------------------------------------------------------------

def pull_campaign_insights(for_date: Optional[date] = None) -> dict:
    """
    Fetch Meta campaign insights for `for_date` (defaults to yesterday) and
    upsert into the ad_campaigns table. Skips silently when credentials are absent.
    Returns a result dict with status, rows_upserted, and any error detail.
    """
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT_ID:
        logger.info("Meta credentials not set — skipping campaign pull")
        return {"ok": False, "error": "Meta credentials not configured (META_ACCESS_TOKEN or META_AD_ACCOUNT_ID missing)"}

    # Ensure the account ID has the required act_ prefix
    account_id = META_AD_ACCOUNT_ID
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    target_date = for_date or (date.today() - timedelta(days=1))
    date_str = target_date.isoformat()

    data = _graph_get(
        f"{account_id}/insights",
        {
            "fields": "campaign_id,campaign_name,spend,impressions,clicks",
            "time_range": json.dumps({"since": date_str, "until": date_str}),
            "level": "campaign",
            "limit": "500",
        },
    )

    if "error" in data:
        err = data["error"]
        logger.error("Meta API error: %s", err)
        return {"ok": False, "error": err.get("message", str(err)), "date": date_str}

    rows = data.get("data", [])
    if not rows:
        logger.info("Meta API: no campaign data for %s", date_str)
        return {"ok": True, "rows_upserted": 0, "date": date_str, "note": "Meta returned no campaign rows for this date"}

    db = SessionLocal()
    try:
        for row in rows:
            campaign_id = row.get("campaign_id", "")
            if not campaign_id:
                continue
            campaign_name = row.get("campaign_name", "")
            spend = float(row.get("spend", 0) or 0)
            impressions = int(row.get("impressions", 0) or 0)
            clicks = int(row.get("clicks", 0) or 0)

            # Attribution: contacts whose source tag matches this campaign_id
            leads_count = (
                db.query(func.count(Contact.id))
                .filter(
                    Contact.source == campaign_id,
                    func.date(Contact.first_seen) == target_date,
                )
                .scalar() or 0
            )
            deposits_count = (
                db.query(func.count(StageHistory.id))
                .join(Contact, Contact.id == StageHistory.contact_id)
                .filter(
                    Contact.source == campaign_id,
                    StageHistory.to_stage == 7,
                    func.date(StageHistory.moved_at) == target_date,
                )
                .scalar() or 0
            )

            existing = (
                db.query(AdCampaign)
                .filter(AdCampaign.campaign_id == campaign_id, AdCampaign.date == target_date)
                .first()
            )
            if existing:
                existing.campaign_name = campaign_name
                existing.spend = spend
                existing.impressions = impressions
                existing.clicks = clicks
                existing.leads = leads_count
                existing.deposits = deposits_count
                existing.updated_at = datetime.utcnow()
            else:
                db.add(AdCampaign(
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    date=target_date,
                    spend=spend,
                    impressions=impressions,
                    clicks=clicks,
                    leads=leads_count,
                    deposits=deposits_count,
                ))

        db.commit()
        logger.info("Meta API: upserted %d campaign rows for %s", len(rows), date_str)
        upsert_result = {"ok": True, "rows_upserted": len(rows), "date": date_str}
    except Exception as e:
        logger.exception("Meta API upsert failed: %s", e)
        upsert_result = {"ok": False, "error": str(e), "date": date_str}
    finally:
        db.close()

    # Also pull ad-level creative data
    pull_ad_creative_insights(for_date=target_date)
    return upsert_result


def pull_ad_creative_insights(for_date: Optional[date] = None) -> None:
    """
    Pull Meta ad-level insights for `for_date` and upsert into ad_creatives.
    Called automatically at the end of pull_campaign_insights.
    """
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT_ID:
        return

    account_id = META_AD_ACCOUNT_ID
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    target_date = for_date or (date.today() - timedelta(days=1))
    date_str = target_date.isoformat()

    data = _graph_get(
        f"{account_id}/insights",
        {
            "fields": "ad_id,ad_name,campaign_id,campaign_name,spend,impressions,clicks",
            "time_range": json.dumps({"since": date_str, "until": date_str}),
            "level": "ad",
            "limit": "500",
        },
    )

    rows = data.get("data", [])
    if not rows:
        logger.info("Meta API: no ad-level data for %s", date_str)
        return

    db = SessionLocal()
    try:
        for row in rows:
            ad_id = row.get("ad_id", "")
            if not ad_id:
                continue
            campaign_id = row.get("campaign_id", "")
            spend = float(row.get("spend", 0) or 0)
            impressions = int(row.get("impressions", 0) or 0)
            clicks = int(row.get("clicks", 0) or 0)

            # Ad-level attribution: contacts whose source matches this campaign
            # (we attribute at campaign level since source_tag maps to campaign)
            leads_count = (
                db.query(func.count(Contact.id))
                .filter(
                    Contact.source == campaign_id,
                    func.date(Contact.first_seen) == target_date,
                )
                .scalar() or 0
            )
            deposits_count = (
                db.query(func.count(StageHistory.id))
                .join(Contact, Contact.id == StageHistory.contact_id)
                .filter(
                    Contact.source == campaign_id,
                    StageHistory.to_stage == 7,
                    func.date(StageHistory.moved_at) == target_date,
                )
                .scalar() or 0
            )

            existing = (
                db.query(AdCreative)
                .filter(AdCreative.ad_id == ad_id, AdCreative.date == target_date)
                .first()
            )
            if existing:
                existing.ad_name = row.get("ad_name", "")
                existing.campaign_id = campaign_id
                existing.campaign_name = row.get("campaign_name", "")
                existing.spend = spend
                existing.impressions = impressions
                existing.clicks = clicks
                existing.leads = leads_count
                existing.deposits = deposits_count
                existing.updated_at = datetime.utcnow()
            else:
                db.add(AdCreative(
                    ad_id=ad_id,
                    ad_name=row.get("ad_name", ""),
                    campaign_id=campaign_id,
                    campaign_name=row.get("campaign_name", ""),
                    date=target_date,
                    spend=spend,
                    impressions=impressions,
                    clicks=clicks,
                    leads=leads_count,
                    deposits=deposits_count,
                ))

        db.commit()
        logger.info("Meta API: upserted %d ad creative rows for %s", len(rows), date_str)
    except Exception as e:
        logger.exception("Meta API ad creative upsert failed: %s", e)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Conversions API (CAPI) — Stage 7 deposit event
# ---------------------------------------------------------------------------

def send_capi_conversion(contact_id: int, event_time: Optional[datetime] = None) -> None:
    """
    Fire a Meta CAPI 'Purchase' event when a contact reaches Stage 7.
    Uses the contact's Telegram ID as a hashed external_id.
    Skips silently when credentials are absent.
    """
    if not META_ACCESS_TOKEN or not META_PIXEL_ID:
        logger.info("Meta CAPI not configured — skipping conversion event for contact %s", contact_id)
        return

    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return

        ts = int((event_time or datetime.utcnow()).timestamp())
        hashed_id = hashlib.sha256(str(contact.id).encode()).hexdigest()

        payload = {
            "data": [
                {
                    "event_name": "Purchase",
                    "event_time": ts,
                    "action_source": "other",
                    "user_data": {
                        "external_id": hashed_id,
                    },
                    "custom_data": {
                        "currency": "USD",
                        "value": 1,  # placeholder — real deposit amount not stored yet
                        **({"campaign_source": contact.source} if contact.source else {}),
                    },
                }
            ],
        }

        resp = _graph_post(f"{META_PIXEL_ID}/events", payload)
        logger.info("Meta CAPI conversion sent for contact %s: %s", contact_id, resp)
    except Exception as e:
        logger.exception("Meta CAPI failed for contact %s: %s", contact_id, e)
    finally:
        db.close()
