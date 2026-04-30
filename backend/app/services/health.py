"""
Health-check functions, one per integration. Each function is pure (no
global mutation outside the cache module) and can be tested in isolation
with a MockHttpClient.

Cache strategy (see services/health_cache.py):
- _probe_cache: 5-min TTL for most external probes.
- _membership_cache: 1-min TTL for getChatMember probes — fix surfaces fast.
- _bot_self_cache: 1-hour TTL for the bot's own user_id (getMe).

Every external call uses an httpx.AsyncClient passed in by the orchestrator.
The orchestrator also handles per-check exception isolation via
asyncio.gather(..., return_exceptions=True), so individual checks may raise
freely; _exception_to_check converts that into a synthetic error entry.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import urllib.parse
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import APP_BASE_URL
from app.database.models import Affiliate, Workspace
from app.services.health_cache import (
    _bot_self_cache, _membership_cache, _probe_cache,
)

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v19.0"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _exception_to_check(exc: BaseException, check_id: str, label: str) -> dict:
    """Turn an unhandled exception into a synthetic error-status check entry."""
    return {
        "id": check_id,
        "label": label,
        "status": "error",
        "detail": f"Diagnostic failed: {type(exc).__name__}: {str(exc)[:120]}",
        "action": "Please report this — it should not happen",
    }


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


async def _get_bot_user_id(token: str, http) -> Optional[int]:
    """
    Resolve the bot's own user_id (getMe) so we can ask Telegram whether the
    bot is a member of each destination channel. Cached for 1 hour.
    """
    cached = _bot_self_cache.get(("bot_self", _hash_token(token)))
    if cached is not None:
        return cached
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        r = await http.get(url)
        bot_id = r.json().get("result", {}).get("id")
        if bot_id:
            _bot_self_cache.set(("bot_self", _hash_token(token)), bot_id)
        return bot_id
    except Exception:
        return None


async def _check_bot_in_chat(
    token: str, chat_id: str, http, *, cache_key: tuple,
) -> Optional[bool]:
    """
    Probe whether the bot is in a given chat with post permission.
    Returns True/False, or None if the probe was inconclusive (network error).

    Caches successes only via _membership_cache (60-second TTL).
    """
    cached = _membership_cache.get(cache_key)
    if cached is not None:
        return cached
    bot_id = await _get_bot_user_id(token, http)
    if not bot_id:
        return None
    try:
        url = (
            f"https://api.telegram.org/bot{token}/getChatMember"
            f"?chat_id={urllib.parse.quote(str(chat_id))}&user_id={bot_id}"
        )
        r = await http.get(url)
        result = r.json().get("result")
        if not result:
            return None
        status = result.get("status")
        if status not in ("member", "administrator", "creator"):
            _membership_cache.set(cache_key, False)
            return False
        if status == "administrator" and result.get("can_post_messages") is False:
            _membership_cache.set(cache_key, False)
            return False
        _membership_cache.set(cache_key, True)
        return True
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-check functions
# ---------------------------------------------------------------------------

async def check_telegram_bot(ws: Optional[Workspace], workspace_id: int, http) -> dict:
    """
    Verify the Bot API webhook is registered, points at our backend, and isn't
    backed up. Distinguishes 'no token', 'wrong URL', 'queue backlog', 'recent
    delivery error', and 'API unreachable'.
    """
    label = "Telegram Bot"
    token = ws.bot_token if ws and ws.bot_token else None
    if not token:
        return {
            "id": "bot", "label": label, "status": "error",
            "detail": "Bot token not set — leads cannot reach your CRM.",
            "action": "Settings → Telegram → Telegram Bot",
        }

    expected = f"{APP_BASE_URL}/webhook/{workspace_id}" if APP_BASE_URL else None
    cache_key = ("bot_webhook", workspace_id)
    info = _probe_cache.get(cache_key)
    if info is None:
        try:
            r = await http.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
            info = r.json().get("result", {})
            _probe_cache.set(cache_key, info)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return {
                "id": "bot", "label": label, "status": "warn",
                "detail": "Could not reach Telegram API right now (will retry).",
                "action": "If this persists more than 5 minutes, check VPS network/DNS",
            }

    webhook_url = info.get("url") or None
    pending = info.get("pending_update_count", 0) or 0
    last_err_date = info.get("last_error_date")
    last_err_msg = (info.get("last_error_message") or "")[:120]

    if not webhook_url:
        return {
            "id": "bot", "label": label, "status": "warn",
            "detail": "Token saved but webhook not registered.",
            "action": "Settings → Telegram → Telegram Bot → Register Webhook",
        }
    if expected and webhook_url != expected:
        return {
            "id": "bot", "label": label, "status": "warn",
            "detail": f"Webhook points to {webhook_url} (expected {expected}).",
            "action": "Settings → Telegram → Telegram Bot → Re-register Webhook",
        }
    if pending > 100:
        return {
            "id": "bot", "label": label, "status": "warn",
            "detail": f"{pending} updates queued — bot may be slow.",
            "action": "Investigate slow webhook handler",
        }
    if last_err_date:
        age = (datetime.utcnow() - datetime.utcfromtimestamp(last_err_date)).total_seconds()
        if age < 3600:
            return {
                "id": "bot", "label": label, "status": "warn",
                "detail": f"Telegram reported a delivery error: {last_err_msg}",
                "action": "Check VPS logs",
            }
    return {
        "id": "bot", "label": label, "status": "ok",
        "detail": "Token saved and webhook active.",
    }


async def check_operator_account(ws: Optional[Workspace], workspace_id: int) -> dict:
    """
    Verify the Telethon client is alive, connected, AND has an authorized
    session. The previous implementation only checked dict membership; this
    awaits is_user_authorized() so a session revoked by Telegram is detected
    immediately (instead of after the next process restart).
    """
    label = "Operator Account"
    from app.services import telethon_client as _tc

    client = _tc.get_client(workspace_id)
    has_session = bool(ws and ws.telethon_session)

    if client is None:
        if has_session:
            return {
                "id": "operator", "label": label, "status": "warn",
                "detail": "Session saved but client not running — server may need a restart.",
                "action": "Contact support if this persists",
            }
        return {
            "id": "operator", "label": label, "status": "error",
            "detail": "Not connected — you cannot DM leads from inside the CRM.",
            "action": "Settings → Telegram → Operator Account",
        }

    try:
        connected = client.is_connected()
    except Exception as e:
        return {
            "id": "operator", "label": label, "status": "warn",
            "detail": f"Telethon raised on is_connected(): {type(e).__name__}",
            "action": "Restart the server if this persists",
        }
    if not connected:
        return {
            "id": "operator", "label": label, "status": "warn",
            "detail": "Telethon socket disconnected (will reconnect automatically).",
            "action": "If this persists for more than 5 minutes, restart the server",
        }

    try:
        authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=5.0)
    except asyncio.TimeoutError:
        return {
            "id": "operator", "label": label, "status": "warn",
            "detail": "Telethon did not respond within 5 seconds.",
            "action": "Restart the server if this persists",
        }
    except Exception as e:
        return {
            "id": "operator", "label": label, "status": "warn",
            "detail": f"Telethon raised: {type(e).__name__}: {str(e)[:80]}",
            "action": "Re-link the operator account",
        }

    if not authorized:
        return {
            "id": "operator", "label": label, "status": "warn",
            "detail": "Telegram rejected the session — re-link the operator account.",
            "action": "Settings → Telegram → Operator Account → reconnect",
        }

    return {
        "id": "operator", "label": label, "status": "ok",
        "detail": "Telethon session connected and authorized.",
    }


async def check_signal_forwarding(
    ws: Optional[Workspace], workspace_id: int, http, db: Session,
) -> dict:
    """
    Three layers, short-circuit on the first conclusive result:

    1. Config gate — error/warn if source, destinations, or bot_token missing.
    2. Observed-success bypass — ok if last forward < 5 min ago.
    3. Per-destination getChatMember probe — warn listing the bad destinations.
    """
    label = "Signal Forwarding"
    from app.services import forwarding as _fwd

    source_id = ws.source_channel_id if ws else None
    token = ws.bot_token if ws and ws.bot_token else None
    destinations = _fwd.get_destinations_for_org(workspace_id, db) if ws else []

    if not source_id:
        return {
            "id": "forwarding", "label": label, "status": "error",
            "detail": "Source channel not configured — nothing to mirror.",
            "action": "Settings → Telegram → Signal Forwarding",
        }
    if not destinations:
        return {
            "id": "forwarding", "label": label, "status": "warn",
            "detail": "Source set, but no destination channels yet.",
            "action": "Settings → Telegram → Signal Forwarding",
        }
    if not token:
        return {
            "id": "forwarding", "label": label, "status": "warn",
            "detail": "Bot token missing — cannot deliver to destinations.",
            "action": "Settings → Telegram → Telegram Bot",
        }

    # Layer 2: observed-success bypass
    if ws.last_signal_forwarded_at:
        age = (datetime.utcnow() - ws.last_signal_forwarded_at).total_seconds()
        if age < 300:
            mins = int(age // 60)
            ago = f"{int(age)}s ago" if mins == 0 else f"{mins}m ago"
            return {
                "id": "forwarding", "label": label, "status": "ok",
                "detail": f"Forwarded a signal {ago} — pipeline alive.",
            }

    # Layer 3: per-destination probe in parallel
    async def probe(dest):
        return await _check_bot_in_chat(
            token, dest, http,
            cache_key=("forwarding_membership", workspace_id, str(dest)),
        )

    results = await asyncio.gather(*(probe(d) for d in destinations))
    bad = [str(d) for d, r in zip(destinations, results) if r is False]
    inconclusive = [str(d) for d, r in zip(destinations, results) if r is None]

    if bad:
        listed = ", ".join(bad[:3])
        more = f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""
        return {
            "id": "forwarding", "label": label, "status": "warn",
            "detail": f"Bot can't post in: {listed}{more}.",
            "action": "Add the bot to those channels as an admin with post permission",
        }
    if all(r is None for r in results):
        return {
            "id": "forwarding", "label": label, "status": "warn",
            "detail": "Could not verify destinations right now (Telegram unreachable).",
            "action": "Retry; if persistent, check VPS network/DNS",
        }
    if inconclusive:
        verified = len(results) - len(inconclusive)
        return {
            "id": "forwarding", "label": label, "status": "ok",
            "detail": f"Verified {verified} of {len(results)} destinations; rest will retry.",
        }
    return {
        "id": "forwarding", "label": label, "status": "ok",
        "detail": f"Source channel set; bot has access to all {len(destinations)} destinations.",
    }


async def _meta_probe(
    meta_token: str, account_id: str, path: str, http,
) -> tuple[str, int, Optional[str]]:
    """
    Probe a /act_<id>/<path> endpoint. Returns (status, count, error_msg).
      status='ok'           — rows returned
      status='warn'         — Meta accepted the call but returned no rows
      status='error'        — Meta returned a structured {error:...} response
      status='unreachable'  — network/timeout failure
    Caches everything except 'unreachable' for 5 min.
    """
    cache_key = ("meta_probe", _hash_token(meta_token), account_id, path)
    cached = _probe_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        sep = "&" if "?" in path else "?"
        url = (
            f"{GRAPH_BASE}/act_{account_id}/{path}{sep}"
            f"limit=5&access_token={urllib.parse.quote(meta_token)}"
        )
        r = await http.get(url)
        data = r.json()
    except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
        return ("unreachable", 0, None)
    if "error" in data:
        out = ("error", 0, (data["error"].get("message") or "")[:120])
        _probe_cache.set(cache_key, out)
        return out
    rows = data.get("data", []) or []
    out = ("ok", len(rows), None) if rows else ("warn", 0, None)
    _probe_cache.set(cache_key, out)
    return out


async def check_meta(ws: Optional[Workspace], http) -> dict:
    """
    Five-stage Meta health probe:

      1. Token saved?
      2. Token accepted by /me?
      3. ads_management permission granted?
      4. Ad account ID configured?
      5. Live data flowing — campaigns + creatives + recent insights all present?

    Stage 5 hits three Graph endpoints in parallel:
      - /act_<id>/campaigns — at least one campaign exists
      - /act_<id>/adcreatives — at least one creative exists
      - /act_<id>/insights?date_preset=last_3d — non-empty impressions in the
        last 3 days (proves ads are actively delivering)

    Any of those returning empty/error is reported in the detail so the
    dashboard tells the user exactly which piece of the pipeline is dark.
    """
    label = "Meta Ads"
    meta_token = ws.meta_access_token if ws else None
    if not meta_token:
        return {
            "id": "meta", "label": label, "status": "warn",
            "detail": "Not connected — campaign analytics and CAPI events won't run.",
            "action": "Settings → Meta Ads",
        }

    cache_key = ("meta_me", _hash_token(meta_token))
    data = _probe_cache.get(cache_key)
    if data is None:
        try:
            url = (
                f"{GRAPH_BASE}/me?fields=id,name,permissions"
                f"&access_token={urllib.parse.quote(meta_token)}"
            )
            r = await http.get(url)
            data = r.json()
            _probe_cache.set(cache_key, data)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return {
                "id": "meta", "label": label, "status": "warn",
                "detail": "Could not reach Meta Graph API right now (will retry).",
                "action": "If this persists, check VPS network/DNS",
            }

    if "error" in data:
        msg = data["error"].get("message", "Token rejected by Meta")
        return {
            "id": "meta", "label": label, "status": "error",
            "detail": f"Meta rejected the access token: {msg}",
            "action": "Settings → Meta Ads — regenerate token",
        }

    perms_block = data.get("permissions", {}).get("data", []) or []
    granted = {p.get("permission") for p in perms_block if p.get("status") == "granted"}
    if "ads_management" not in granted:
        return {
            "id": "meta", "label": label, "status": "error",
            "detail": "Token missing ads_management — CAPI events will be rejected; ads cannot optimise on conversion.",
            "action": "Settings → Meta Ads — regenerate token with ads_management scope",
        }

    raw_account = (ws.meta_ad_account_id or "").strip() if ws else ""
    account_id = raw_account[4:] if raw_account.startswith("act_") else raw_account
    if not account_id:
        return {
            "id": "meta", "label": label, "status": "warn",
            "detail": "Token connected, but ad account ID not set — can't verify campaigns or ads are running.",
            "action": "Settings → Meta Ads — set ad account ID",
        }

    campaigns, creatives, insights = await asyncio.gather(
        _meta_probe(meta_token, account_id,
                    "campaigns?fields=id,name,effective_status", http),
        _meta_probe(meta_token, account_id,
                    "adcreatives?fields=id,name", http),
        _meta_probe(meta_token, account_id,
                    "insights?date_preset=last_3d&level=ad&fields=impressions,spend", http),
    )

    for probe_label, (status, _count, msg) in (
        ("campaigns", campaigns),
        ("ad creatives", creatives),
        ("insights", insights),
    ):
        if status == "error":
            return {
                "id": "meta", "label": label, "status": "error",
                "detail": f"Meta refused the {probe_label} request: {msg or 'unknown error'}",
                "action": "Settings → Meta Ads — verify token scopes and ad account ID",
            }

    problems: list[str] = []
    if campaigns[0] == "warn":
        problems.append("no campaigns visible")
    elif campaigns[0] == "unreachable":
        problems.append("could not list campaigns right now")
    if creatives[0] == "warn":
        problems.append("no ad creatives visible")
    elif creatives[0] == "unreachable":
        problems.append("could not list creatives right now")
    if insights[0] == "warn":
        problems.append("no impressions in the last 3 days — ads not delivering")
    elif insights[0] == "unreachable":
        problems.append("could not load insights right now")

    if problems:
        return {
            "id": "meta", "label": label, "status": "warn",
            "detail": "Data not flowing: " + "; ".join(problems) + ".",
            "action": "Verify campaigns are active and Meta has produced impressions",
        }

    detail = (
        f"Connected · {campaigns[1]} campaigns, {creatives[1]} creatives, "
        f"impressions in last 3 days"
    )
    if ws and ws.landing_page_url:
        detail += " · landing page set"
    return {
        "id": "meta", "label": label, "status": "ok",
        "detail": detail + ".",
    }


async def check_vip_channel(
    ws: Optional[Workspace], workspace_id: int, db: Session, http,
) -> Optional[dict]:
    """
    Affiliate-specific check. Verifies (a) the affiliate row has a
    vip_channel_id set AND (b) the bot is actually a member of that channel
    with post permission.

    Returns None for workspaces with no Affiliate row — the orchestrator drops
    None entries so non-affiliate workspaces don't see a "VIP Channel" row.
    """
    label = "VIP Channel"
    aff = db.query(Affiliate).filter(Affiliate.affiliate_workspace_id == workspace_id).first()
    if not aff:
        return None

    if not aff.vip_channel_id:
        return {
            "id": "vip_channel", "label": label, "status": "warn",
            "detail": "Not linked — VIP members won't receive signals.",
            "action": "Dashboard checklist → VIP Channel",
        }

    token = ws.bot_token if ws and ws.bot_token else None
    if not token:
        return {
            "id": "vip_channel", "label": label, "status": "warn",
            "detail": f"Linked: {aff.vip_channel_id}; cannot verify membership without bot token.",
            "action": "Settings → Telegram → Telegram Bot",
        }

    ok_status = await _check_bot_in_chat(
        token, aff.vip_channel_id, http,
        cache_key=("vip_member", aff.id, str(aff.vip_channel_id)),
    )
    if ok_status is True:
        return {
            "id": "vip_channel", "label": label, "status": "ok",
            "detail": f"Linked: {aff.vip_channel_id}; bot has post access.",
        }
    if ok_status is False:
        return {
            "id": "vip_channel", "label": label, "status": "warn",
            "detail": f"Linked: {aff.vip_channel_id} but bot is not a member or can't post.",
            "action": "Add the bot to the VIP channel as an admin with post permission",
        }
    return {
        "id": "vip_channel", "label": label, "status": "warn",
        "detail": f"Linked: {aff.vip_channel_id}; could not verify bot membership right now.",
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# (id, label) — order is preserved in the response
_CHECKS_META = [
    ("bot",         "Telegram Bot"),
    ("operator",    "Operator Account"),
    ("forwarding",  "Signal Forwarding"),
    ("meta",        "Meta Ads"),
    ("vip_channel", "VIP Channel"),
]


async def run_all_checks(ws: Optional[Workspace], workspace_id: int, db: Session) -> dict:
    """
    Run every check in parallel via asyncio.gather (return_exceptions=True so
    individual failures don't crash the endpoint). Compose the response payload.
    """
    # Module-level lookup so tests can monkey-patch check_* and we still see it.
    import sys as _sys
    self_mod = _sys.modules[__name__]

    async with httpx.AsyncClient(timeout=5.0) as http:
        coroutines = [
            self_mod.check_telegram_bot(ws, workspace_id, http),
            self_mod.check_operator_account(ws, workspace_id),
            self_mod.check_signal_forwarding(ws, workspace_id, http, db),
            self_mod.check_meta(ws, http),
            self_mod.check_vip_channel(ws, workspace_id, db, http),
        ]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

    checks: list[dict] = []
    for i, r in enumerate(results):
        check_id, label = _CHECKS_META[i]
        if r is None:
            continue  # check_vip_channel returns None for non-affiliate workspaces
        if isinstance(r, BaseException):
            checks.append(_exception_to_check(r, check_id, label))
        else:
            checks.append(r)

    has_error = any(c["status"] == "error" for c in checks)
    has_warn  = any(c["status"] == "warn"  for c in checks)
    overall = "critical" if has_error else ("degraded" if has_warn else "healthy")
    return {"overall": overall, "checks": checks}
