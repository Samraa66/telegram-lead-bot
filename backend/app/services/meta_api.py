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

from app.database import SessionLocal
from app.database.models import AdCampaign, AdCreative, Campaign, Contact, StageHistory, Workspace

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _get_workspace_credentials(workspace_id: int = 1) -> tuple[str, str, str]:
    """
    Return (access_token, ad_account_id, pixel_id) for a workspace.
    Falls back to .env values for workspace 1 if DB has no token set.
    """
    from app.config import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_PIXEL_ID
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if ws and ws.meta_access_token:
            return ws.meta_access_token, ws.meta_ad_account_id or "", ws.meta_pixel_id or ""
    finally:
        db.close()
    # .env fallback is workspace-1 only — never expose client credentials to other workspaces
    if workspace_id == 1:
        return META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_PIXEL_ID
    return "", "", ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _graph_get(path: str, params: dict, access_token: str = "") -> dict:
    """GET request to the Meta Graph API. Returns parsed JSON or empty dict on failure."""
    if not access_token:
        from app.config import META_ACCESS_TOKEN
        access_token = META_ACCESS_TOKEN
    params["access_token"] = access_token
    query = urllib.parse.urlencode(params)
    url = f"{GRAPH_BASE}/{path}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error("Meta Graph API GET failed (%s): %s", path, e)
        return {}


def _graph_post(path: str, payload: dict, access_token: str = "") -> dict:
    """POST request to the Meta Graph API. Returns parsed JSON or empty dict on failure."""
    if not access_token:
        from app.config import META_ACCESS_TOKEN
        access_token = META_ACCESS_TOKEN
    payload["access_token"] = access_token
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

def pull_campaign_insights(for_date: Optional[date] = None, workspace_id: int = 1) -> dict:
    """
    Fetch Meta campaign insights for `for_date` (defaults to yesterday) and
    upsert into the ad_campaigns table. Skips silently when credentials are absent.
    Returns a result dict with status, rows_upserted, and any error detail.
    """
    access_token, ad_account_id, _pixel_id = _get_workspace_credentials(workspace_id)

    if not access_token or not ad_account_id:
        logger.info("Meta credentials not set — skipping campaign pull")
        return {"ok": False, "error": "Meta credentials not configured"}

    account_id = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"

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
        access_token=access_token,
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

            # Resolve the source_tag for this Meta campaign_id via the Campaign registry.
            # contact.source stores the /start parameter (= source_tag), NOT the numeric Meta campaign_id.
            campaign_record = (
                db.query(Campaign)
                .filter(Campaign.meta_campaign_id == campaign_id)
                .first()
            )
            source_tag = campaign_record.source_tag if campaign_record else campaign_id

            leads_count = (
                db.query(func.count(Contact.id))
                .filter(
                    Contact.source == source_tag,
                    func.date(Contact.first_seen) == target_date,
                )
                .scalar() or 0
            )
            deposits_count = (
                db.query(func.count(StageHistory.id))
                .join(Contact, Contact.id == StageHistory.contact_id)
                .filter(
                    Contact.source == source_tag,
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

    pull_ad_creative_insights(for_date=target_date, workspace_id=workspace_id)
    return upsert_result


def pull_ad_creative_insights(for_date: Optional[date] = None, workspace_id: int = 1) -> None:
    """
    Pull Meta ad-level insights for `for_date` and upsert into ad_creatives.
    Called automatically at the end of pull_campaign_insights.
    """
    access_token, ad_account_id, _pixel_id = _get_workspace_credentials(workspace_id)
    if not access_token or not ad_account_id:
        return

    account_id = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"

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
        access_token=access_token,
    )

    rows = data.get("data", [])
    if not rows:
        logger.info("Meta API: no ad-level data for %s", date_str)
        return

    db = SessionLocal()
    try:
        # Cache campaign_id → source_tag lookups for this batch
        _source_tag_cache: dict[str, str] = {}

        for row in rows:
            ad_id = row.get("ad_id", "")
            if not ad_id:
                continue
            campaign_id = row.get("campaign_id", "")
            spend = float(row.get("spend", 0) or 0)
            impressions = int(row.get("impressions", 0) or 0)
            clicks = int(row.get("clicks", 0) or 0)

            if campaign_id not in _source_tag_cache:
                rec = db.query(Campaign).filter(Campaign.meta_campaign_id == campaign_id).first()
                _source_tag_cache[campaign_id] = rec.source_tag if rec else campaign_id
            source_tag = _source_tag_cache[campaign_id]

            leads_count = (
                db.query(func.count(Contact.id))
                .filter(
                    Contact.source == source_tag,
                    func.date(Contact.first_seen) == target_date,
                )
                .scalar() or 0
            )
            deposits_count = (
                db.query(func.count(StageHistory.id))
                .join(Contact, Contact.id == StageHistory.contact_id)
                .filter(
                    Contact.source == source_tag,
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

def send_capi_conversion(contact_id: int, event_time: Optional[datetime] = None, workspace_id: int = 1) -> None:
    """
    Fire a Meta CAPI 'Purchase' event when a contact reaches Stage 7.
    Uses the contact's Telegram ID as a hashed external_id.
    Skips silently when credentials are absent.
    """
    access_token, _ad_account_id, pixel_id = _get_workspace_credentials(workspace_id)
    if not access_token or not pixel_id:
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
                        "value": 1,
                        **({"campaign_source": contact.source} if contact.source else {}),
                    },
                }
            ],
        }

        resp = _graph_post(f"{pixel_id}/events", payload, access_token=access_token)
        logger.info("Meta CAPI conversion sent for contact %s: %s", contact_id, resp)
    except Exception as e:
        logger.exception("Meta CAPI failed for contact %s: %s", contact_id, e)
    finally:
        db.close()
