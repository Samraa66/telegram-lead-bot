# System Health Audit — Design Spec

**Date:** 2026-04-29
**Status:** Ready for review
**Type:** Refactor + small schema addition + extensive new tests

## Goal

Make the dashboard's `System Status` panel actually verify each integration's runtime state, not just whether config rows exist. After this work, the panel becomes a regression net for every PR that touches Telegram, Telethon, signal forwarding, or Meta — if any of these silently breaks, the panel turns yellow or red.

The current `/health/workspace` endpoint mixes real probes (Telegram `getWebhookInfo`, Meta `/me`) with config-only checks (Telethon "client object exists in dict", forwarding "destinations list non-empty") that report `NOMINAL` even when the underlying integration is dead. This spec replaces every weak check with a real liveness probe, separates "upstream unreachable" from "upstream rejected," and ships unit-test coverage for every branch.

## Non-goals

- **Adding a persistent health-history log.** No `event_log` table, no trending. Live snapshot only. Easy to add later; YAGNI for now.
- **Contract tests against real Telegram/Meta APIs in CI.** All tests use HTTP-layer mocks (`MockHttpClient`). A real-API contract suite would need test credentials we don't have in CI; the audit-driven mocks catch our parser logic, which is where 99% of regression risk lives.
- **Frontend changes.** The endpoint response shape stays identical. The dashboard automatically gets the more accurate verdict.
- **Per-destination forwarding history.** Per-channel state is tracked via the `getChatMember` probe at health-check time, not stored. Health remains a live signal, not an audit log.
- **Background warmer / push notifications.** No timer that pre-warms the cache, no Slack alerts. The dashboard is pulled when someone looks at it.
- **Touching anything outside the five existing checks.** No new "Database connection," "Disk space," etc. We are upgrading what exists, not expanding scope.

## Context

The current `health_workspace` function in `backend/app/main.py:1753-1881` is ~130 lines of inline checks. Audit findings (from the 2026-04-29 conversation):

| Check | Current behaviour | Real or weak |
|---|---|---|
| Telegram Bot | `getWebhookInfo` round-trip; compare URL strings | **Real** (with caveats: silent exception swallow, ignores `pending_update_count` and `last_error_*`) |
| Operator Account | `get_client(ws_id) is not None` — checks process-local dict | **Weak** — does not verify `is_user_authorized()` or `is_connected()` |
| Signal Forwarding | source set + bot token set + destinations list non-empty | **Weak** — pure config read; no proof the bot is in any channel or that anything has been forwarded |
| Meta Ads | `/me` round-trip | **Real** for token validity only; doesn't verify `ads_management` permission |
| VIP Channel | `Affiliate.vip_channel_id IS NOT NULL` | **Weak** — pure DB read |

Concrete failure modes the panel hides today:
1. Telethon session revoked by Telegram → dashboard says NOMINAL forever (until process restart).
2. Bot kicked from a destination channel → dashboard says NOMINAL; signals silently fail to deliver.
3. Telethon source-channel handler never bound (partial start failure) → dashboard says NOMINAL; new signals never forward.
4. Webhook accumulates `pending_update_count: 4000` and `last_error_message: 500 Internal Server Error` → dashboard says NOMINAL.
5. Telegram API itself unreachable from VPS → dashboard says "webhook not registered" (misleading: not the actual problem).
6. Meta token has narrow scopes (no `ads_management`) → CAPI fires get rejected, dashboard says NOMINAL.

This spec fixes all six.

## Architecture

The endpoint becomes a thin orchestrator. Check logic moves into a new module so each check is independently testable.

```
main.py:health_workspace               <- async; orchestrates the run
  └─ services/health.py                <- new module, per-check functions
       ├─ check_telegram_bot
       ├─ check_operator_account       <- awaits Telethon
       ├─ check_signal_forwarding
       ├─ check_meta
       └─ check_vip_channel
  └─ services/health_cache.py          <- new module, TTLCache class
```

### Endpoint signature

```python
@app.get("/health/workspace")
async def health_workspace(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin", "operator", "vip_manager", "affiliate")),
):
    from app.services import health
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    async with httpx.AsyncClient(timeout=5.0) as http:
        results = await asyncio.gather(
            health.check_telegram_bot(ws, workspace_id, http),
            health.check_operator_account(ws, workspace_id),
            health.check_signal_forwarding(ws, workspace_id, http, db),
            health.check_meta(ws, http),
            health.check_vip_channel(ws, db, http),
            return_exceptions=True,
        )
    checks = [
        r if isinstance(r, dict)
          else health._exception_to_check(r, _META[i][0], _META[i][1])
        for i, r in enumerate(results)
    ]
    has_error = any(c["status"] == "error" for c in checks)
    has_warn  = any(c["status"] == "warn"  for c in checks)
    overall = "critical" if has_error else ("degraded" if has_warn else "healthy")
    return {"overall": overall, "checks": checks}
```

`return_exceptions=True` is load-bearing: a single check raising never crashes the endpoint or hides the other four checks.

### Why async

The current sync endpoint serialises 5+ external HTTP calls. With timeouts up to 5s each, a slow run is 25+ seconds. The async version with `asyncio.gather` runs them in parallel — the whole endpoint returns in `max(individual_call_time)`, typically 1-2 seconds.

`httpx.AsyncClient` replaces the existing blocking `urllib.request.urlopen`. `httpx` is already a dev dependency via FastAPI's optional test client; this spec makes it a runtime dependency by adding it to `requirements.txt`.

### Schema additions

One column on `workspaces`:

```sql
ALTER TABLE workspaces ADD COLUMN last_signal_forwarded_at TIMESTAMP;
```

Written by `services/forwarding.py:copy_signal_for_org` after the first successful destination copy of each batch. Read by `check_signal_forwarding` for the observed-success bypass.

That is the only schema change.

### Cache module

`backend/app/services/health_cache.py`:

```python
import time
from threading import Lock
from typing import Any, Optional


class TTLCache:
    """Process-local time-bounded cache. Thread-safe for FastAPI concurrent requests."""
    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: tuple) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: tuple, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_probe_cache = TTLCache(ttl_seconds=300)              # 5-minute default for most probes
_membership_cache = TTLCache(ttl_seconds=60)          # 1-minute — destination membership refreshes fast so a fix surfaces quickly
_bot_self_cache = TTLCache(ttl_seconds=3600)          # 1-hour — bot user_id rarely changes
```

Successes only. A failed probe doesn't get cached — next request retries. Lost on restart, fine.

## Per-check details

### 1. `check_telegram_bot`

Probes `getWebhookInfo`, looks at four fields:

- **`url`** — must equal `f"{APP_BASE_URL}/webhook/{workspace_id}"`. Mismatch → `warn` with current vs expected.
- **`pending_update_count`** — if > 100, `warn` "X updates queued — bot may be slow."
- **`last_error_date`** — if within last hour, `warn` "Telegram reported a delivery error: <last_error_message>" (truncated to 120 chars).
- **HTTP/network failure** — `warn` with detail "Could not reach Telegram API right now (will retry)." Distinguishes from "no token saved" and from "webhook not registered." Fixes audit failure #5.

Cache key: `("bot_webhook", workspace_id)` TTL 5 min.

Outcome states:
- `ok` → token saved, URL matches, no recent errors, queue < 100.
- `warn` → URL mismatch / queue backlog / recent delivery error / API unreachable.
- `error` → no token at all.

### 2. `check_operator_account`

Three signals (replacing the current "is the dict entry non-None"):

```python
client = get_client(workspace_id)
if client is None:
    if ws.telethon_session:
        return warn("Session saved but client not running — server may need a restart")
    return error("Not connected — you cannot DM leads from inside the CRM")

if not client.is_connected():
    return warn("Telethon socket disconnected (will reconnect automatically)")

try:
    authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=5.0)
except asyncio.TimeoutError:
    return warn("Telethon did not respond within 5 seconds")

if not authorized:
    return warn("Telegram rejected the session — re-link the operator account",
                action="Settings → Telegram → Operator Account → reconnect")

return ok("Telethon session connected and authorized")
```

Catches the audit failure case where Telegram revokes the session but our process-local `_clients` dict still has the stale entry.

No caching — Telethon calls are local round-trips (~1 ms).

### 3. `check_signal_forwarding`

Three layers, in order, short-circuit on the first conclusive answer:

**Layer 1 — Config gate.**
- No source channel → `error`.
- No destinations → `warn`.
- No bot token → `warn`.

**Layer 2 — Observed-success bypass.**
```python
if ws.last_signal_forwarded_at:
    age_seconds = (datetime.utcnow() - ws.last_signal_forwarded_at).total_seconds()
    if age_seconds < 300:  # 5 minutes
        return ok(f"Forwarded a signal {humanize(age_seconds)} ago — pipeline alive")
```

**Layer 3 — Per-destination probe.**
Run only if no recent observed forward. For each destination, hit `getChatMember(chat_id, bot_user_id)` in parallel:

```python
bot_id = await _get_bot_user_id(token, http)  # cached 1h via _bot_self_cache
async def probe(dest):
    cache_key = ("forwarding_membership", workspace_id, dest)
    cached = _membership_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        url = f"https://api.telegram.org/bot{token}/getChatMember?chat_id={dest}&user_id={bot_id}"
        r = await http.get(url)
        result = r.json().get("result")
        ok = bool(result and result.get("status") in ("administrator", "member"))
        # Channels need can_post_messages specifically
        if ok and result.get("status") == "administrator":
            ok = result.get("can_post_messages", True)
        _membership_cache.set(cache_key, ok)
        return ok
    except Exception:
        return None  # treat as inconclusive — don't cache failure

results = await asyncio.gather(*(probe(d) for d in destinations))
bad = [d for d, r in zip(destinations, results) if r is False]
inconclusive = [d for d, r in zip(destinations, results) if r is None]
```

Outcome from layer 3, evaluated in order:
- Any `False` (regardless of other results) → `warn` "Bot can't post in: <chat_id_1>, <chat_id_2> (+N more)". Up to 3 channel IDs listed; "+N more" appended if there are more.
- All `True` → `ok` "Source channel set; bot has access to all N destinations."
- Mix of `True` + `None` (no failures, but some couldn't be verified) → `ok` with caveat "verified M of N destinations; rest will retry."
- All `None` (Telegram unreachable for every probe) → `warn` "Could not verify destinations right now."

Bot user_id helper, cached 1 hour:

```python
async def _get_bot_user_id(token: str, http) -> Optional[int]:
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    cached = _bot_self_cache.get(("bot_self", token_hash))
    if cached is not None:
        return cached
    try:
        r = await http.get(f"https://api.telegram.org/bot{token}/getMe")
        bot_id = r.json().get("result", {}).get("id")
        if bot_id:
            _bot_self_cache.set(("bot_self", token_hash), bot_id)
        return bot_id
    except Exception:
        return None
```

Hashing the token before using it as a cache key avoids storing the raw token in process memory beyond the cache TTL.

### 4. `check_meta`

Same `/me` call but with `fields=id,name,permissions` so we can verify the token has `ads_management`:

```python
url = f"{GRAPH_BASE}/me?fields=id,name,permissions&access_token={quote(meta_token)}"
r = await http.get(url)
data = r.json()
if "error" in data:
    return error(f"Meta rejected the access token: {data['error'].get('message', '')}")

perms = {p["permission"] for p in data.get("permissions", {}).get("data", []) if p.get("status") == "granted"}
if "ads_management" not in perms:
    return error("Token missing ads_management — CAPI events will be rejected; ads cannot optimise on conversion",
                 action="Settings → Meta Ads — regenerate token with ads_management scope")

detail = "Connected"
if ws.landing_page_url:
    detail += " · landing page set"
else:
    detail += " · no landing page URL yet"
return ok(detail + ".")
```

Cache key: `("meta_me", token_hash)` TTL 5 min.

Outcome states:
- `ok` → token valid AND has `ads_management` granted. Detail mentions whether `landing_page_url` is set.
- `error` → token valid but missing `ads_management`. Treated as critical because CAPI rejection kills conversion-based ad optimisation, and ads drive lead acquisition.
- `error` → token rejected by Meta entirely.
- `warn` → no token saved (existing behaviour — ads simply not connected yet).

### 5. `check_vip_channel`

Existing logic plus a `getChatMember` probe when `vip_channel_id` is set, re-using the same membership check helper as Signal Forwarding:

```python
if not aff:
    return None  # no row to render — orchestrator drops None entries
if not aff.vip_channel_id:
    return warn("Not linked — VIP members won't receive signals")

ok_status = await _check_bot_in_chat(token, aff.vip_channel_id, http, workspace_id)
if ok_status is True:
    return ok(f"Linked: {aff.vip_channel_id}; bot has post access")
if ok_status is False:
    return warn(f"Linked: {aff.vip_channel_id} but bot is not a member or can't post",
                action="Add the bot to the VIP channel as an admin with post permission")
return warn(f"Linked: {aff.vip_channel_id}; could not verify bot membership right now")
```

`_check_bot_in_chat` is the same membership probe used by `check_signal_forwarding`, factored to a private helper to avoid duplication.

## Error handling

Three principles:

1. **Per-check exceptions never crash the endpoint.** `asyncio.gather(..., return_exceptions=True)` plus `_exception_to_check` synthesises a synthetic error entry for any exception:

   ```python
   def _exception_to_check(exc, check_id, label):
       return {
           "id": check_id, "label": label, "status": "error",
           "detail": f"Diagnostic failed: {type(exc).__name__}: {str(exc)[:120]}",
           "action": "Please report this — it should not happen",
       }
   ```

2. **Distinguish "upstream unreachable" from "upstream rejected."** Every external call uses a typed exception branch:

   ```python
   try:
       r = await http.get(url)
   except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
       return warn("Could not reach <upstream> right now")
   ```

   Never the silent `except Exception: pass` that the current code uses. Fixes audit failure #5.

3. **Cache successes only, never failures.** A 502 from Telegram doesn't get cached; the next request retries. Successes get the full TTL. Standard pattern, prevents "stuck on a stale error" bugs.

## Testing

### Convention

Same script-style as the rest of the repo (`backend/scripts/test_*.py`, runnable as `python -m scripts.<name>`). Each script is self-contained, exits 0/1.

### Test files

```
backend/scripts/
  test_health_cache.py             — TTLCache unit tests
  test_health_telegram_bot.py      — check_telegram_bot
  test_health_operator.py          — check_operator_account
  test_health_signal_forwarding.py — check_signal_forwarding
  test_health_meta.py              — check_meta
  test_health_vip_channel.py       — check_vip_channel
  test_health_orchestrator.py      — endpoint-level integration
  test_health_mocks.py             — shared MockHttpClient (imported by the others)
```

### Shared mock helper

`backend/scripts/test_health_mocks.py`:

```python
class MockHttpClient:
    """Minimal httpx.AsyncClient stand-in. Exact-URL routing or prefix routing.
    Each route returns a (status_code, json_body) tuple."""
    def __init__(self, routes: dict[str, tuple[int, dict]]):
        self.routes = routes
        self.calls: list[str] = []  # each call's URL — for assertions

    async def get(self, url, **kwargs):
        self.calls.append(url)
        for prefix, (status, body) in self.routes.items():
            if url.startswith(prefix) or url == prefix:
                resp = MockResponse(status, body)
                if status >= 400:
                    raise httpx.HTTPStatusError(...)  # or just return for mock
                return resp
        raise httpx.NetworkError(f"unmocked URL: {url}")

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None


class MockResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
    def json(self): return self._body
```

Plus a `mock_telethon_client(authorized=True, connected=True)` factory for `test_health_operator.py`.

### Coverage requirements

For each check, the test script must cover:

1. **Happy path** — every upstream returns OK, status is `ok`.
2. **Each warn-path** — every condition that produces `warn` (URL mismatch, queue backlog, missing permission, etc.).
3. **Each error-path** — missing config, hard rejection.
4. **Upstream unreachable** — simulate `httpx.TimeoutException`. Assert the response distinguishes it from "no config" and from "rejected." This is the audit-fix-#5 regression test.
5. **Cache hit** — call twice; assert the second call doesn't re-hit the mock (`MockHttpClient.calls` length stays the same).
6. **Cache expiry** — call, manually expire the entry, call again, assert the mock IS hit.

Concrete coverage targets:

| Test script | Test count |
|---|---|
| test_health_cache.py | 5 (set/get, expiry, clear, thread-safety, missing key) |
| test_health_telegram_bot.py | 7 (ok, URL mismatch, queue backlog, recent error, no token, network failure, cache hit) |
| test_health_operator.py | 6 (ok, no client, not connected, not authorized, timeout, no session) |
| test_health_signal_forwarding.py | 9 (config gates × 3, observed-success bypass, all destinations ok, some failed, all unreachable, cache hit, ok hit after destinations cached) |
| test_health_meta.py | 5 (ok, missing ads_management, rejected, no token, unreachable) |
| test_health_vip_channel.py | 4 (ok, not linked, bot not member, unreachable) |
| test_health_orchestrator.py | 5 (overall=healthy, =degraded, =critical, exception in one check survives, parallel-execution timing) |

Total: ~41 tests across 7 scripts.

### Orchestrator-level timing test

Verifies the endpoint actually runs probes in parallel. Each mock check sleeps 100ms; with 5 checks, the endpoint should return in ~100ms, not ~500ms:

```python
async def test_parallel_execution():
    async def slow_check(*args, **kwargs):
        await asyncio.sleep(0.1)
        return {"id": "x", "label": "x", "status": "ok", "detail": ""}
    ... patch all five checks to slow_check ...
    t0 = time.monotonic()
    response = await client.get("/health/workspace")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.3, f"checks ran serially (took {elapsed}s)"
```

### What is deliberately NOT tested

- **Real Telegram API contract.** No CI integration with real bot tokens / Telethon sessions. Pattern A from brainstorming.
- **Frontend rendering of the new detail strings.** No precedent for Vitest in this repo; same call as Spec A.
- **Persistent health log.** Out of scope.

## Migration / deployment notes

1. Deploy backend. On first boot, `_ensure_columns()` adds `Workspace.last_signal_forwarded_at` (nullable, no default) — no data migration needed.
2. The new code is fully backward-compatible: an old `Workspace` row with `last_signal_forwarded_at=NULL` simply skips the observed-success bypass and falls through to the per-destination probe.
3. `httpx` becomes a runtime dependency. Already installed in dev (FastAPI optional test client). On the VPS, `pip install -r requirements.txt` after merge picks it up.
4. No frontend deploy needed — endpoint shape is unchanged.

## Inventory of changes

**New files:**
- `backend/app/services/health.py` — five check functions plus shared helpers
- `backend/app/services/health_cache.py` — `TTLCache` + module-level cache instances
- `backend/scripts/test_health_*.py` — 7 new test scripts
- `backend/scripts/test_health_mocks.py` — `MockHttpClient` shared helper

**Modified files:**
- `backend/app/main.py` — `/health/workspace` becomes `async def`, delegates to `services.health`
- `backend/app/services/forwarding.py` — write `last_signal_forwarded_at` after first successful destination copy
- `backend/app/database/models.py` — add `Workspace.last_signal_forwarded_at`
- `backend/app/database/__init__.py` — `_ensure_columns` adds the new column
- `backend/requirements.txt` — pin `httpx` as a runtime dep

**No frontend changes.**

## Open questions

None — all four clarifying questions resolved during brainstorming. Locked decisions:

- Endpoint: `async def` with `httpx.AsyncClient` and `asyncio.gather`.
- Cache: in-memory `TTLCache`, 5-min default + observed-success bypass.
- Storage: derive inbound timestamps from `messages` (no new column); add `Workspace.last_signal_forwarded_at` for forwarding.
- Tests: HTTP-layer mocks via `MockHttpClient`; script-style; one script per check group; ~41 tests total covering happy / warn / error / unreachable / cache-hit / cache-expiry.
