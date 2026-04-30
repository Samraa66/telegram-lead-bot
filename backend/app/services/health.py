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
# Per-check functions — added in subsequent tasks
# ---------------------------------------------------------------------------
# (check_telegram_bot in Task 7)
# (check_operator_account in Task 8)
# (check_signal_forwarding in Task 9)
# (check_meta in Task 10)
# (check_vip_channel in Task 11)
# (run_all_checks in Task 12)
