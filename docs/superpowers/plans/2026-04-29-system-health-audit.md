# System Health Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every weak/config-only check in `/health/workspace` with a real liveness probe, and ship comprehensive HTTP-mocked tests so the dashboard becomes a regression net for any future PR that touches Telegram, Telethon, signal forwarding, or Meta.

**Architecture:** Extract the inline check logic from `main.py:health_workspace` into a new `services/health.py` module with one pure async function per check (`check_telegram_bot`, `check_operator_account`, `check_signal_forwarding`, `check_meta`, `check_vip_channel`) plus a `run_all_checks` orchestrator. The endpoint becomes async, runs probes in parallel via `asyncio.gather(..., return_exceptions=True)`, and uses an in-memory `TTLCache` so dashboard refreshes don't burn rate-limit budget. The forwarding pipeline gets a "last successful forward" timestamp on Workspace so we can skip per-destination probes when there's evidence the pipeline is alive.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + `httpx` async client + Telethon (`is_connected()`, `is_user_authorized()`) + script-style tests (`backend/scripts/test_*.py`).

---

## File map

**Modify:**
- `backend/requirements.txt` — add `httpx`
- `backend/app/database/models.py` — add `Workspace.last_signal_forwarded_at` column
- `backend/app/database/__init__.py` — `_ensure_columns()` adds the new column
- `backend/app/services/forwarding.py` — write the timestamp after first successful destination copy
- `backend/app/main.py` — `/health/workspace` becomes `async def`, body delegates to `services.health.run_all_checks`

**Create:**
- `backend/app/services/health_cache.py` — `TTLCache` class + module-level cache instances
- `backend/app/services/health.py` — five `check_*` functions + `_exception_to_check` + `_get_bot_user_id` + `_check_bot_in_chat` + `run_all_checks` orchestrator
- `backend/scripts/test_health_mocks.py` — shared `MockHttpClient` + `MockResponse` + `mock_telethon_client` helpers
- `backend/scripts/test_health_cache.py` — TTLCache unit tests
- `backend/scripts/test_health_telegram_bot.py` — `check_telegram_bot` tests
- `backend/scripts/test_health_operator.py` — `check_operator_account` tests
- `backend/scripts/test_health_signal_forwarding.py` — `check_signal_forwarding` tests
- `backend/scripts/test_health_meta.py` — `check_meta` tests
- `backend/scripts/test_health_vip_channel.py` — `check_vip_channel` tests
- `backend/scripts/test_health_orchestrator.py` — `run_all_checks` tests (overall verdict, exception isolation, parallel timing)

---

## Task 1: Add `httpx` to runtime requirements

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add `httpx` to requirements.txt.**

Open `backend/requirements.txt`. Append `httpx` on its own line. The full file should now read:

```
fastapi
uvicorn
gunicorn
aiofiles
apscheduler
python-dotenv
requests
sqlalchemy
psycopg2-binary
python-telegram-bot
telethon
python-jose[cryptography]
slowapi
httpx
```

- [ ] **Step 2: Smoke-check that httpx is importable in the venv.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -c "import httpx; print(httpx.__version__)"
```

Expected: a version string like `0.28.1`. If not installed, run `.venv/bin/pip install httpx` first.

- [ ] **Step 3: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/requirements.txt
git commit -m "chore: pin httpx as a runtime dependency for async health probes"
```

---

## Task 2: Add `Workspace.last_signal_forwarded_at` column

**Files:**
- Modify: `backend/app/database/models.py`
- Modify: `backend/app/database/__init__.py`

- [ ] **Step 1: Add the column to the Workspace model.**

In `backend/app/database/models.py`, locate the `Workspace` class and find the existing `last_backfill_summary` line (added in Spec A). Add the new column immediately after it (still inside the class):

```python
    last_backfill_summary = Column(Text, nullable=True)  # JSON: {contacts_created, messages_replayed, skipped}
    # Last time the signal-forwarding pipeline successfully copied a signal to at least
    # one destination. Read by services/health.py:check_signal_forwarding for the
    # observed-success bypass.
    last_signal_forwarded_at = Column(DateTime, nullable=True)
```

- [ ] **Step 2: Add the column to `_ensure_columns`.**

In `backend/app/database/__init__.py`, find the `ws_needed` list inside the `if _table_exists("workspaces"):` block. After the existing `last_backfill_summary` entry (added in Spec A), append:

```python
            ("last_signal_forwarded_at", "TIMESTAMP"),
```

- [ ] **Step 3: Smoke-test the column shows up.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
DATABASE_URL=sqlite:///:memory: .venv/bin/python -c "
from app.database import init_db, engine
from sqlalchemy import inspect
init_db()
cols = {c['name'] for c in inspect(engine).get_columns('workspaces')}
assert 'last_signal_forwarded_at' in cols, f'missing column: {cols}'
print('ok')
"
```

Expected output: `ok`.

- [ ] **Step 4: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/database/models.py backend/app/database/__init__.py
git commit -m "feat(models): add Workspace.last_signal_forwarded_at"
```

---

## Task 3: Write `last_signal_forwarded_at` in forwarding pipeline

**Files:**
- Modify: `backend/app/services/forwarding.py`

- [ ] **Step 1: Locate the successful-copy site.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
grep -n "def copy_signal_for_org\|copy_message" backend/app/services/forwarding.py | head
```

This identifies the function we'll modify and the inner copy call that signals success.

- [ ] **Step 2: Read the current implementation to find the right place to add the write.**

Read `backend/app/services/forwarding.py` start to end (it's small, < 200 lines). Identify the loop where each destination is copied to. The write goes AFTER the first success of any destination — not inside the per-destination loop, and only if at least one succeeded.

- [ ] **Step 3: Write the timestamp on first success.**

In `backend/app/services/forwarding.py`, modify `copy_signal_for_org` so that after the per-destination loop finishes, if at least one destination succeeded, it updates `Workspace.last_signal_forwarded_at`. Concrete pattern (match to actual code structure):

```python
# (inside copy_signal_for_org, after the destinations loop)
if any_success:
    from datetime import datetime
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws:
        ws.last_signal_forwarded_at = datetime.utcnow()
        db.commit()
```

If `copy_signal_for_org` doesn't have an existing `any_success` boolean, track it: initialise `any_success = False` before the loop, set it to `True` after a successful `copy_message` call.

If the function uses `await` (it should — `copy_message` calls Bot API), the write must happen in the same async context after the gather.

- [ ] **Step 4: Smoke-test the write doesn't break anything by importing the module.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
APP_ENV=development .venv/bin/python -c "from app.services.forwarding import copy_signal_for_org; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/forwarding.py
git commit -m "feat(forwarding): record last_signal_forwarded_at on successful copy"
```

---

## Task 4: Implement `TTLCache` + tests

**Files:**
- Create: `backend/app/services/health_cache.py`
- Create: `backend/scripts/test_health_cache.py`

- [ ] **Step 1: Write the failing test.**

Create `backend/scripts/test_health_cache.py`:

```python
"""
Tests for TTLCache.
Run from backend/:  python -m scripts.test_health_cache
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

from app.services.health_cache import TTLCache

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_get_missing_returns_none():
    print("\n=== Test 1: missing key returns None ===")
    c = TTLCache(ttl_seconds=60)
    return check(f"get('x') is None (got {c.get(('x',))!r})", c.get(("x",)) is None)


def test_set_then_get_roundtrip():
    print("\n=== Test 2: set then get returns the value ===")
    c = TTLCache(ttl_seconds=60)
    c.set(("k",), 42)
    return check(f"get returns 42 (got {c.get(('k',))!r})", c.get(("k",)) == 42)


def test_expiry_returns_none():
    print("\n=== Test 3: expired entry returns None ===")
    c = TTLCache(ttl_seconds=0)  # immediately stale
    c.set(("k",), 42)
    time.sleep(0.01)
    return check(f"expired get is None (got {c.get(('k',))!r})", c.get(("k",)) is None)


def test_clear_wipes_everything():
    print("\n=== Test 4: clear() removes all entries ===")
    c = TTLCache(ttl_seconds=60)
    c.set(("a",), 1); c.set(("b",), 2)
    c.clear()
    ok1 = check(f"a is None (got {c.get(('a',))!r})", c.get(("a",)) is None)
    ok2 = check(f"b is None (got {c.get(('b',))!r})", c.get(("b",)) is None)
    return ok1 and ok2


def test_overwrite():
    print("\n=== Test 5: set overwrites existing value ===")
    c = TTLCache(ttl_seconds=60)
    c.set(("k",), 1)
    c.set(("k",), 2)
    return check(f"latest value wins (got {c.get(('k',))!r})", c.get(("k",)) == 2)


def main():
    results = [
        test_get_missing_returns_none(),
        test_set_then_get_roundtrip(),
        test_expiry_returns_none(),
        test_clear_wipes_everything(),
        test_overwrite(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_cache
```

Expected: `ImportError: cannot import name 'TTLCache' from 'app.services.health_cache'`.

- [ ] **Step 3: Implement TTLCache.**

Create `backend/app/services/health_cache.py`:

```python
"""
Process-local time-bounded cache for health probes.
Successes are cached; failures are not. Lost on process restart — fine,
next request just re-warms the entries.
"""
import time
from threading import Lock
from typing import Any, Optional


class TTLCache:
    """Thread-safe TTL cache. Keys are tuples. Values are arbitrary Python objects."""

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


# Module-level instances used by services/health.py
_probe_cache = TTLCache(ttl_seconds=300)         # 5-min default for most probes
_membership_cache = TTLCache(ttl_seconds=60)     # 1-min — destination access surfaces fixes fast
_bot_self_cache = TTLCache(ttl_seconds=3600)     # 1-hour — bot user_id rarely changes
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_cache
```

Expected: `Results: 5/5 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health_cache.py backend/scripts/test_health_cache.py
git commit -m "feat(health): TTLCache thread-safe in-memory cache + tests"
```

---

## Task 5: Shared mock helpers (`MockHttpClient`, mock Telethon client)

**Files:**
- Create: `backend/scripts/test_health_mocks.py`

- [ ] **Step 1: Write the mock module.**

Create `backend/scripts/test_health_mocks.py`:

```python
"""
Shared HTTP and Telethon mocks for health-check unit tests.
Imported by every test_health_<check>.py script.
"""
from typing import Optional


class MockResponse:
    """Stand-in for an httpx.Response. Only the methods we use."""
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class MockHttpClient:
    """
    Minimal httpx.AsyncClient stand-in. Pass a routes dict mapping URL prefix
    (or exact URL) -> (status_code, body). On each .get(), the first matching
    route wins. Calls are recorded in `.calls` for assertion.

    Special routes:
      - body == "TIMEOUT": raise httpx.TimeoutException on the call.
      - body == "NETWORK_ERROR": raise httpx.NetworkError on the call.
    """
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url: str, **kwargs):
        import httpx
        self.calls.append(url)
        for prefix, payload in self.routes.items():
            if url.startswith(prefix) or url == prefix:
                status, body = payload
                if body == "TIMEOUT":
                    raise httpx.TimeoutException("mocked timeout", request=None)
                if body == "NETWORK_ERROR":
                    raise httpx.NetworkError("mocked network error", request=None)
                return MockResponse(status, body)
        raise httpx.NetworkError(f"unmocked URL: {url}", request=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


class MockTelethonClient:
    """
    Stand-in for a Telethon TelegramClient. Configure each return value in
    the constructor.
    """
    def __init__(
        self,
        connected: bool = True,
        authorized: bool = True,
        authorize_raises: Optional[Exception] = None,
        authorize_delay_s: float = 0.0,
    ):
        self._connected = connected
        self._authorized = authorized
        self._authorize_raises = authorize_raises
        self._authorize_delay_s = authorize_delay_s

    def is_connected(self) -> bool:
        return self._connected

    async def is_user_authorized(self) -> bool:
        if self._authorize_delay_s:
            import asyncio
            await asyncio.sleep(self._authorize_delay_s)
        if self._authorize_raises:
            raise self._authorize_raises
        return self._authorized
```

- [ ] **Step 2: Smoke-check imports.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -c "
from scripts.test_health_mocks import MockHttpClient, MockResponse, MockTelethonClient
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/scripts/test_health_mocks.py
git commit -m "test(health): shared MockHttpClient and MockTelethonClient helpers"
```

---

## Task 6: `services/health.py` skeleton with shared helpers

**Files:**
- Create: `backend/app/services/health.py`

- [ ] **Step 1: Write the skeleton with shared types and helpers.**

Create `backend/app/services/health.py`:

```python
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
import json as _json
import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import APP_BASE_URL
from app.database.models import Workspace, Affiliate
from app.services.health_cache import (
    _bot_self_cache, _membership_cache, _probe_cache,
)

logger = logging.getLogger(__name__)

# Meta Graph API base — matches the existing constant used in main.py
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


async def _get_bot_user_id(token: str, http) -> Optional[int]:
    """
    Resolve the bot's own user_id (getMe) so we can ask Telegram whether the
    bot is a member of each destination channel. Cached for 1 hour.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    cached = _bot_self_cache.get(("bot_self", token_hash))
    if cached is not None:
        return cached
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        r = await http.get(url)
        bot_id = r.json().get("result", {}).get("id")
        if bot_id:
            _bot_self_cache.set(("bot_self", token_hash), bot_id)
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


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Per-check functions — added in subsequent tasks
# ---------------------------------------------------------------------------
# (check_telegram_bot in Task 7)
# (check_operator_account in Task 8)
# (check_signal_forwarding in Task 9)
# (check_meta in Task 10)
# (check_vip_channel in Task 11)
# (run_all_checks in Task 12)
```

- [ ] **Step 2: Smoke-check the module imports cleanly.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
APP_ENV=development .venv/bin/python -c "
from app.services.health import _exception_to_check, _get_bot_user_id, _check_bot_in_chat, _hash_token, GRAPH_BASE
e = _exception_to_check(RuntimeError('boom'), 'x', 'X')
assert e['status'] == 'error'
assert 'RuntimeError' in e['detail']
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health.py
git commit -m "feat(health): module skeleton + shared helpers (_exception_to_check, _get_bot_user_id, _check_bot_in_chat)"
```

---

## Task 7: `check_telegram_bot` + tests

**Files:**
- Modify: `backend/app/services/health.py`
- Create: `backend/scripts/test_health_telegram_bot.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_health_telegram_bot.py`:

```python
"""
Tests for check_telegram_bot.
Run from backend/:  python -m scripts.test_health_telegram_bot
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_BASE_URL", "https://test.example.com")

from datetime import datetime, timedelta
from app.database.models import Workspace
from app.services.health_cache import _probe_cache
from scripts.test_health_mocks import MockHttpClient

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _ws(bot_token="test_token"):
    ws = Workspace(id=42, name="t", bot_token=bot_token)
    return ws


def _expected(ws_id):
    return f"https://test.example.com/webhook/{ws_id}"


def test_ok_when_url_matches_no_errors():
    print("\n=== Test 1: ok when URL matches and no errors ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": _expected(42), "pending_update_count": 0}
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    return check(f"status=ok (got {result!r})", result["status"] == "ok")


def test_warn_url_mismatch():
    print("\n=== Test 2: warn when webhook URL doesn't match expected ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": "https://wrong.example.com/webhook/1", "pending_update_count": 0}
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions 'wrong'", "wrong.example.com" in result["detail"])
    return ok1 and ok2


def test_warn_pending_backlog():
    print("\n=== Test 3: warn when pending_update_count > 100 ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": _expected(42), "pending_update_count": 250}
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions queue/backlog", "250" in result["detail"] or "queue" in result["detail"].lower())
    return ok1 and ok2


def test_warn_recent_delivery_error():
    print("\n=== Test 4: warn when last_error_date is recent ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    recent_ts = int((datetime.utcnow() - timedelta(minutes=10)).timestamp())
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {
                "url": _expected(42),
                "pending_update_count": 0,
                "last_error_date": recent_ts,
                "last_error_message": "500 Internal Server Error",
            }
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions error", "500" in result["detail"] or "error" in result["detail"].lower())
    return ok1 and ok2


def test_error_when_no_token():
    print("\n=== Test 5: error when no bot_token ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws(bot_token=None)
    http = MockHttpClient({})
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_warn_on_network_failure():
    print("\n=== Test 6: warn (not 'webhook not registered') when Telegram unreachable ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, "TIMEOUT"),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(
        f"detail says 'could not reach' (got {result['detail']!r})",
        "could not reach" in result["detail"].lower() or "unreachable" in result["detail"].lower(),
    )
    return ok1 and ok2


def test_cache_hit_skips_second_call():
    print("\n=== Test 7: second call within TTL doesn't re-hit Telegram ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": _expected(42), "pending_update_count": 0}
        }),
    })
    asyncio.run(check_telegram_bot(ws, 42, http))
    asyncio.run(check_telegram_bot(ws, 42, http))
    return check(f"only 1 HTTP call made (got {len(http.calls)})", len(http.calls) == 1)


def main():
    results = [
        test_ok_when_url_matches_no_errors(),
        test_warn_url_mismatch(),
        test_warn_pending_backlog(),
        test_warn_recent_delivery_error(),
        test_error_when_no_token(),
        test_warn_on_network_failure(),
        test_cache_hit_skips_second_call(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_telegram_bot
```

Expected: `ImportError: cannot import name 'check_telegram_bot' from 'app.services.health'`.

- [ ] **Step 3: Implement check_telegram_bot.**

In `backend/app/services/health.py`, append after the helper functions section:

```python
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
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_telegram_bot
```

Expected: `Results: 7/7 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health.py backend/scripts/test_health_telegram_bot.py
git commit -m "feat(health): check_telegram_bot with backlog + error-date detection + tests"
```

---

## Task 8: `check_operator_account` + tests

**Files:**
- Modify: `backend/app/services/health.py`
- Create: `backend/scripts/test_health_operator.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_health_operator.py`:

```python
"""
Tests for check_operator_account.
Run from backend/:  python -m scripts.test_health_operator
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database.models import Workspace
from scripts.test_health_mocks import MockTelethonClient

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _patch_get_client(mock):
    """Monkey-patch app.services.telethon_client.get_client to return our mock."""
    from app.services import telethon_client as tc
    saved = tc.get_client
    tc.get_client = lambda ws_id: mock
    return saved


def _restore_get_client(saved):
    from app.services import telethon_client as tc
    tc.get_client = saved


def test_ok_when_connected_and_authorized():
    print("\n=== Test 1: ok when connected and authorized ===")
    from app.services.health import check_operator_account
    ws = Workspace(id=1, telethon_session="enc:v1:xxxx")
    saved = _patch_get_client(MockTelethonClient(connected=True, authorized=True))
    try:
        result = asyncio.run(check_operator_account(ws, 1))
    finally:
        _restore_get_client(saved)
    return check(f"status=ok (got {result['status']!r})", result["status"] == "ok")


def test_error_when_no_client_no_session():
    print("\n=== Test 2: error when no client object and no saved session ===")
    from app.services.health import check_operator_account
    ws = Workspace(id=1, telethon_session=None)
    saved = _patch_get_client(None)
    try:
        result = asyncio.run(check_operator_account(ws, 1))
    finally:
        _restore_get_client(saved)
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_warn_when_session_saved_but_no_client():
    print("\n=== Test 3: warn when session saved but client not running ===")
    from app.services.health import check_operator_account
    ws = Workspace(id=1, telethon_session="enc:v1:xxxx")
    saved = _patch_get_client(None)
    try:
        result = asyncio.run(check_operator_account(ws, 1))
    finally:
        _restore_get_client(saved)
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_warn_when_disconnected():
    print("\n=== Test 4: warn when client.is_connected() is False ===")
    from app.services.health import check_operator_account
    ws = Workspace(id=1, telethon_session="enc:v1:xxxx")
    saved = _patch_get_client(MockTelethonClient(connected=False, authorized=True))
    try:
        result = asyncio.run(check_operator_account(ws, 1))
    finally:
        _restore_get_client(saved)
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_warn_when_unauthorized():
    print("\n=== Test 5: warn when is_user_authorized() returns False ===")
    from app.services.health import check_operator_account
    ws = Workspace(id=1, telethon_session="enc:v1:xxxx")
    saved = _patch_get_client(MockTelethonClient(connected=True, authorized=False))
    try:
        result = asyncio.run(check_operator_account(ws, 1))
    finally:
        _restore_get_client(saved)
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions session/rejected/re-link", any(
        s in result["detail"].lower() for s in ("session", "rejected", "re-link")
    ))
    return ok1 and ok2


def test_warn_on_authorize_timeout():
    print("\n=== Test 6: warn when is_user_authorized() times out ===")
    from app.services.health import check_operator_account
    ws = Workspace(id=1, telethon_session="enc:v1:xxxx")
    saved = _patch_get_client(MockTelethonClient(connected=True, authorize_delay_s=10.0))
    try:
        result = asyncio.run(check_operator_account(ws, 1))
    finally:
        _restore_get_client(saved)
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def main():
    results = [
        test_ok_when_connected_and_authorized(),
        test_error_when_no_client_no_session(),
        test_warn_when_session_saved_but_no_client(),
        test_warn_when_disconnected(),
        test_warn_when_unauthorized(),
        test_warn_on_authorize_timeout(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_operator
```

Expected: `ImportError: cannot import name 'check_operator_account' from 'app.services.health'`.

- [ ] **Step 3: Implement check_operator_account.**

In `backend/app/services/health.py`, append after `check_telegram_bot`:

```python
async def check_operator_account(ws: Optional[Workspace], workspace_id: int) -> dict:
    """
    Verify the Telethon client is alive, connected, AND has an authorized
    session. The previous implementation only checked dict membership; this
    awaits is_user_authorized() so a session revoked by Telegram is detected
    immediately (instead of after the next process restart).
    """
    label = "Operator Account"
    from app.services.telethon_client import get_client

    client = get_client(workspace_id)
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
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_operator
```

Expected: `Results: 6/6 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health.py backend/scripts/test_health_operator.py
git commit -m "feat(health): check_operator_account with is_user_authorized probe + tests"
```

---

## Task 9: `check_signal_forwarding` + tests

**Files:**
- Modify: `backend/app/services/health.py`
- Create: `backend/scripts/test_health_signal_forwarding.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_health_signal_forwarding.py`:

```python
"""
Tests for check_signal_forwarding.
Run from backend/:  python -m scripts.test_health_signal_forwarding
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime, timedelta
from app.database import init_db, SessionLocal
from app.database.models import Workspace
from app.services.health_cache import _membership_cache, _bot_self_cache
from scripts.test_health_mocks import MockHttpClient

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _setup_ws(*, source=None, token=None, last_forward=None):
    init_db()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.source_channel_id = source
    ws.bot_token = token
    ws.last_signal_forwarded_at = last_forward
    db.commit()
    db.close()


def _patch_destinations(values: list):
    """Monkey-patch get_destinations_for_org to return a fixed list."""
    from app.services import forwarding
    saved = forwarding.get_destinations_for_org
    forwarding.get_destinations_for_org = lambda ws_id, db: values
    return saved


def _restore_destinations(saved):
    from app.services import forwarding
    forwarding.get_destinations_for_org = saved


def _clear():
    _membership_cache.clear()
    _bot_self_cache.clear()


def _bot_route(token, value):
    return {f"https://api.telegram.org/bot{token}/getMe": (200, value)}


def _member_route(token, chat_id, value):
    return {
        f"https://api.telegram.org/bot{token}/getChatMember?chat_id={chat_id}": (200, value),
    }


def test_error_no_source():
    print("\n=== Test 1: error when source_channel_id is unset ===")
    _clear()
    _setup_ws(source=None, token="t")
    saved = _patch_destinations([])
    from app.services.health import check_signal_forwarding
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_signal_forwarding(ws, 1, MockHttpClient({}), db))
    finally:
        db.close(); _restore_destinations(saved)
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_warn_no_destinations():
    print("\n=== Test 2: warn when source set but destinations empty ===")
    _clear()
    _setup_ws(source="ch_123", token="t")
    saved = _patch_destinations([])
    from app.services.health import check_signal_forwarding
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_signal_forwarding(ws, 1, MockHttpClient({}), db))
    finally:
        db.close(); _restore_destinations(saved)
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_warn_no_token():
    print("\n=== Test 3: warn when source + destinations set but no bot token ===")
    _clear()
    _setup_ws(source="ch_123", token=None)
    saved = _patch_destinations(["-100111"])
    from app.services.health import check_signal_forwarding
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_signal_forwarding(ws, 1, MockHttpClient({}), db))
    finally:
        db.close(); _restore_destinations(saved)
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_observed_success_bypass():
    print("\n=== Test 4: ok via observed-success bypass when last forward < 5 min ===")
    _clear()
    _setup_ws(source="ch_123", token="t", last_forward=datetime.utcnow() - timedelta(minutes=2))
    saved = _patch_destinations(["-100111"])
    from app.services.health import check_signal_forwarding
    db = SessionLocal()
    http = MockHttpClient({})  # no routes — proves bypass skipped probes
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_signal_forwarding(ws, 1, http, db))
    finally:
        db.close(); _restore_destinations(saved)
    ok1 = check(f"status=ok (got {result['status']!r})", result["status"] == "ok")
    ok2 = check(f"no HTTP calls made (got {len(http.calls)})", len(http.calls) == 0)
    return ok1 and ok2


def test_ok_when_all_destinations_reachable():
    print("\n=== Test 5: ok via probe when no recent forward and all destinations OK ===")
    _clear()
    _setup_ws(source="ch_123", token="t",
              last_forward=datetime.utcnow() - timedelta(hours=2))
    saved = _patch_destinations(["-100111"])
    from app.services.health import check_signal_forwarding
    routes = {}
    routes.update(_bot_route("t", {"result": {"id": 999}}))
    routes.update(_member_route("t", "-100111", {"result": {"status": "administrator", "can_post_messages": True}}))
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_signal_forwarding(ws, 1, MockHttpClient(routes), db))
    finally:
        db.close(); _restore_destinations(saved)
    return check(f"status=ok (got {result['status']!r})", result["status"] == "ok")


def test_warn_when_destination_unreachable_for_bot():
    print("\n=== Test 6: warn listing failed destinations ===")
    _clear()
    _setup_ws(source="ch_123", token="t",
              last_forward=datetime.utcnow() - timedelta(hours=2))
    saved = _patch_destinations(["-100111", "-100222"])
    from app.services.health import check_signal_forwarding
    routes = {}
    routes.update(_bot_route("t", {"result": {"id": 999}}))
    routes.update(_member_route("t", "-100111", {"result": {"status": "administrator", "can_post_messages": True}}))
    routes.update(_member_route("t", "-100222", {"result": {"status": "left"}}))
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_signal_forwarding(ws, 1, MockHttpClient(routes), db))
    finally:
        db.close(); _restore_destinations(saved)
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions -100222", "-100222" in result["detail"])
    return ok1 and ok2


def test_warn_when_all_probes_inconclusive():
    print("\n=== Test 7: warn when every destination probe is inconclusive ===")
    _clear()
    _setup_ws(source="ch_123", token="t",
              last_forward=datetime.utcnow() - timedelta(hours=2))
    saved = _patch_destinations(["-100111"])
    from app.services.health import check_signal_forwarding
    routes = {}
    routes.update(_bot_route("t", {"result": {"id": 999}}))
    routes.update(_member_route("t", "-100111", "TIMEOUT"))
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_signal_forwarding(ws, 1, MockHttpClient(routes), db))
    finally:
        db.close(); _restore_destinations(saved)
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_membership_cache_hit():
    print("\n=== Test 8: second call within TTL doesn't re-hit getChatMember ===")
    _clear()
    _setup_ws(source="ch_123", token="t",
              last_forward=datetime.utcnow() - timedelta(hours=2))
    saved = _patch_destinations(["-100111"])
    from app.services.health import check_signal_forwarding
    routes = {}
    routes.update(_bot_route("t", {"result": {"id": 999}}))
    routes.update(_member_route("t", "-100111", {"result": {"status": "administrator", "can_post_messages": True}}))
    http = MockHttpClient(routes)
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        asyncio.run(check_signal_forwarding(ws, 1, http, db))
        first_calls = len(http.calls)
        asyncio.run(check_signal_forwarding(ws, 1, http, db))
        second_calls = len(http.calls)
    finally:
        db.close(); _restore_destinations(saved)
    return check(f"second call adds 0 HTTP hits (1st={first_calls} 2nd={second_calls})",
                 first_calls == second_calls)


def main():
    results = [
        test_error_no_source(),
        test_warn_no_destinations(),
        test_warn_no_token(),
        test_observed_success_bypass(),
        test_ok_when_all_destinations_reachable(),
        test_warn_when_destination_unreachable_for_bot(),
        test_warn_when_all_probes_inconclusive(),
        test_membership_cache_hit(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_signal_forwarding
```

Expected: `ImportError: cannot import name 'check_signal_forwarding'`.

- [ ] **Step 3: Implement check_signal_forwarding.**

In `backend/app/services/health.py`, append after `check_operator_account`:

```python
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
    from app.services.forwarding import get_destinations_for_org

    source_id = ws.source_channel_id if ws else None
    token = ws.bot_token if ws and ws.bot_token else None
    destinations = get_destinations_for_org(workspace_id, db) if ws else []

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
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_signal_forwarding
```

Expected: `Results: 8/8 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health.py backend/scripts/test_health_signal_forwarding.py
git commit -m "feat(health): check_signal_forwarding 3-layer probe + tests"
```

---

## Task 10: `check_meta` + tests

**Files:**
- Modify: `backend/app/services/health.py`
- Create: `backend/scripts/test_health_meta.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_health_meta.py`:

```python
"""
Tests for check_meta.
Run from backend/:  python -m scripts.test_health_meta
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database.models import Workspace
from app.services.health_cache import _probe_cache
from scripts.test_health_mocks import MockHttpClient

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _ws(token="meta_t", landing=None):
    return Workspace(id=1, meta_access_token=token, landing_page_url=landing)


def _meta_url(token):
    return f"https://graph.facebook.com/v19.0/me?fields=id,name,permissions&access_token={token}"


def _granted(perms_list):
    return {"id": "1", "name": "x", "permissions": {"data": [
        {"permission": p, "status": "granted"} for p in perms_list
    ]}}


def test_warn_when_no_token():
    print("\n=== Test 1: warn when no Meta token saved ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(token=None)
    result = asyncio.run(check_meta(ws, MockHttpClient({})))
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_ok_when_token_valid_with_ads_management():
    print("\n=== Test 2: ok when token valid + ads_management granted ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(landing="https://lp.example.com")
    routes = {_meta_url("meta_t"): (200, _granted(["ads_management", "business_management"]))}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=ok (got {result['status']!r})", result["status"] == "ok")
    ok2 = check(f"detail mentions landing", "landing" in result["detail"].lower())
    return ok1 and ok2


def test_error_when_missing_ads_management():
    print("\n=== Test 3: error when token valid but missing ads_management ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws()
    routes = {_meta_url("meta_t"): (200, _granted(["public_profile"]))}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_error_when_token_rejected():
    print("\n=== Test 4: error when Meta returns {error:...} ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws()
    routes = {_meta_url("meta_t"): (200, {"error": {"message": "token expired"}})}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_warn_when_unreachable():
    print("\n=== Test 5: warn when Graph API unreachable ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws()
    routes = {_meta_url("meta_t"): (200, "TIMEOUT")}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail says could not reach", "could not reach" in result["detail"].lower() or "unreachable" in result["detail"].lower())
    return ok1 and ok2


def main():
    results = [
        test_warn_when_no_token(),
        test_ok_when_token_valid_with_ads_management(),
        test_error_when_missing_ads_management(),
        test_error_when_token_rejected(),
        test_warn_when_unreachable(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_meta
```

Expected: `ImportError: cannot import name 'check_meta'`.

- [ ] **Step 3: Implement check_meta.**

In `backend/app/services/health.py`, append after `check_signal_forwarding`:

```python
async def check_meta(ws: Optional[Workspace], http) -> dict:
    """
    Verify the Meta access token is valid AND has ads_management permission.
    Missing ads_management is critical because CAPI rejection kills
    conversion-based ad optimisation.
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

    detail = "Connected"
    if ws and ws.landing_page_url:
        detail += " · landing page set"
    else:
        detail += " · no landing page URL yet"
    return {
        "id": "meta", "label": label, "status": "ok",
        "detail": detail + ".",
    }
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_meta
```

Expected: `Results: 5/5 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health.py backend/scripts/test_health_meta.py
git commit -m "feat(health): check_meta with ads_management scope verification + tests"
```

---

## Task 11: `check_vip_channel` + tests

**Files:**
- Modify: `backend/app/services/health.py`
- Create: `backend/scripts/test_health_vip_channel.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_health_vip_channel.py`:

```python
"""
Tests for check_vip_channel.
Run from backend/:  python -m scripts.test_health_vip_channel
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import init_db, SessionLocal
from app.database.models import Workspace, Affiliate
from app.services.health_cache import _membership_cache, _bot_self_cache
from scripts.test_health_mocks import MockHttpClient

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _setup(*, vip_channel_id=None, token="t"):
    init_db()
    db = SessionLocal()
    db.query(Affiliate).delete()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.bot_token = token
    db.commit()
    aff = Affiliate(
        id=1, name="A", workspace_id=1, affiliate_workspace_id=1,
        vip_channel_id=vip_channel_id, is_active=True,
    )
    db.add(aff); db.commit()
    db.close()


def _clear():
    _membership_cache.clear()
    _bot_self_cache.clear()


def test_warn_not_linked():
    print("\n=== Test 1: warn when affiliate has no vip_channel_id ===")
    _clear()
    _setup(vip_channel_id=None)
    from app.services.health import check_vip_channel
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_vip_channel(ws, 1, db, MockHttpClient({})))
    finally:
        db.close()
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_ok_when_linked_and_bot_present():
    print("\n=== Test 2: ok when linked AND bot is in channel with post permission ===")
    _clear()
    _setup(vip_channel_id="-100777")
    from app.services.health import check_vip_channel
    routes = {
        "https://api.telegram.org/bott/getMe": (200, {"result": {"id": 999}}),
        "https://api.telegram.org/bott/getChatMember?chat_id=-100777": (200, {
            "result": {"status": "administrator", "can_post_messages": True}
        }),
    }
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_vip_channel(ws, 1, db, MockHttpClient(routes)))
    finally:
        db.close()
    return check(f"status=ok (got {result['status']!r})", result["status"] == "ok")


def test_warn_when_bot_not_member():
    print("\n=== Test 3: warn when linked but bot is not a channel member ===")
    _clear()
    _setup(vip_channel_id="-100777")
    from app.services.health import check_vip_channel
    routes = {
        "https://api.telegram.org/bott/getMe": (200, {"result": {"id": 999}}),
        "https://api.telegram.org/bott/getChatMember?chat_id=-100777": (200, {"result": {"status": "left"}}),
    }
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_vip_channel(ws, 1, db, MockHttpClient(routes)))
    finally:
        db.close()
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_warn_when_unreachable():
    print("\n=== Test 4: warn when Telegram unreachable ===")
    _clear()
    _setup(vip_channel_id="-100777")
    from app.services.health import check_vip_channel
    routes = {
        "https://api.telegram.org/bott/getMe": (200, {"result": {"id": 999}}),
        "https://api.telegram.org/bott/getChatMember?chat_id=-100777": (200, "TIMEOUT"),
    }
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(check_vip_channel(ws, 1, db, MockHttpClient(routes)))
    finally:
        db.close()
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def main():
    results = [
        test_warn_not_linked(),
        test_ok_when_linked_and_bot_present(),
        test_warn_when_bot_not_member(),
        test_warn_when_unreachable(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_vip_channel
```

Expected: `ImportError: cannot import name 'check_vip_channel'`.

- [ ] **Step 3: Implement check_vip_channel.**

In `backend/app/services/health.py`, append after `check_meta`:

```python
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
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_vip_channel
```

Expected: `Results: 4/4 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health.py backend/scripts/test_health_vip_channel.py
git commit -m "feat(health): check_vip_channel with bot-membership verification + tests"
```

---

## Task 12: `run_all_checks` orchestrator + tests

**Files:**
- Modify: `backend/app/services/health.py`
- Create: `backend/scripts/test_health_orchestrator.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_health_orchestrator.py`:

```python
"""
Tests for run_all_checks (orchestrator).
Run from backend/:  python -m scripts.test_health_orchestrator
"""
import sys, os, asyncio, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import init_db, SessionLocal
from app.database.models import Workspace

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _patch_checks(replacements: dict):
    """Replace check_* symbols on services.health with the given async callables."""
    from app.services import health
    saved = {}
    for name, fn in replacements.items():
        saved[name] = getattr(health, name)
        setattr(health, name, fn)
    return saved


def _restore(saved):
    from app.services import health
    for name, fn in saved.items():
        setattr(health, name, fn)


async def _ok(*a, **kw):
    return {"id": "x", "label": "X", "status": "ok", "detail": ""}

async def _warn(*a, **kw):
    return {"id": "x", "label": "X", "status": "warn", "detail": ""}

async def _err(*a, **kw):
    return {"id": "x", "label": "X", "status": "error", "detail": ""}

async def _none(*a, **kw):
    return None

async def _slow(*a, **kw):
    await asyncio.sleep(0.1)
    return {"id": "x", "label": "X", "status": "ok", "detail": ""}

async def _boom(*a, **kw):
    raise RuntimeError("boom")


def test_overall_healthy():
    print("\n=== Test 1: overall=healthy when every check is ok ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _ok,
        "check_operator_account": _ok,
        "check_signal_forwarding": _ok,
        "check_meta": _ok,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    return check(f"overall=healthy (got {result['overall']!r})", result["overall"] == "healthy")


def test_overall_degraded():
    print("\n=== Test 2: overall=degraded when any check is warn ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _ok,
        "check_operator_account": _warn,
        "check_signal_forwarding": _ok,
        "check_meta": _ok,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    return check(f"overall=degraded (got {result['overall']!r})", result["overall"] == "degraded")


def test_overall_critical():
    print("\n=== Test 3: overall=critical when any check is error ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _err,
        "check_operator_account": _ok,
        "check_signal_forwarding": _ok,
        "check_meta": _warn,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    return check(f"overall=critical (got {result['overall']!r})", result["overall"] == "critical")


def test_exception_in_one_check_does_not_crash_endpoint():
    print("\n=== Test 4: exception in one check yields synthetic error, others survive ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _boom,
        "check_operator_account": _ok,
        "check_signal_forwarding": _ok,
        "check_meta": _ok,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    bot = next((c for c in result["checks"] if c["id"] == "bot"), None)
    ok1 = check(f"bot check has status=error (got {bot})", bot is not None and bot["status"] == "error")
    ok2 = check(f"detail mentions RuntimeError", bot is not None and "RuntimeError" in bot["detail"])
    ok3 = check(f"other checks still present (got {len(result['checks'])} total)",
                len(result["checks"]) >= 4)
    return ok1 and ok2 and ok3


def test_checks_run_in_parallel():
    print("\n=== Test 5: 5 slow checks (100ms each) finish in <300ms when parallel ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _slow,
        "check_operator_account": _slow,
        "check_signal_forwarding": _slow,
        "check_meta": _slow,
        "check_vip_channel": _slow,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        t0 = time.monotonic()
        asyncio.run(run_all_checks(ws, 1, db))
        elapsed = time.monotonic() - t0
    finally:
        db.close(); _restore(saved)
    return check(f"elapsed < 0.3s (got {elapsed:.3f}s)", elapsed < 0.3)


def main():
    results = [
        test_overall_healthy(),
        test_overall_degraded(),
        test_overall_critical(),
        test_exception_in_one_check_does_not_crash_endpoint(),
        test_checks_run_in_parallel(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_orchestrator
```

Expected: `ImportError: cannot import name 'run_all_checks'`.

- [ ] **Step 3: Implement run_all_checks.**

In `backend/app/services/health.py`, append after `check_vip_channel`:

```python
# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# (label, fn-name) — order is preserved in the response
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

    # Use a single httpx.AsyncClient for the whole batch — reused across checks.
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
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_health_orchestrator
```

Expected: `Results: 5/5 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/health.py backend/scripts/test_health_orchestrator.py
git commit -m "feat(health): run_all_checks orchestrator with parallel gather + tests"
```

---

## Task 13: Wire `/health/workspace` endpoint to delegate

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Replace the inline check logic with a delegation to `run_all_checks`.**

In `backend/app/main.py`, find the `health_workspace` function (line 1753-ish). Replace its entire body — keeping the decorator and signature — with:

```python
@app.get("/health/workspace")
async def health_workspace(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin", "operator", "vip_manager", "affiliate")),
):
    """
    Aggregated health for the current workspace — one card worth of info showing
    which integrations are up, degraded, or down. Logic lives in
    services/health.py so each check is independently testable.
    """
    from app.services import health
    from app.database.models import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    return await health.run_all_checks(ws, workspace_id, db)
```

This shrinks main.py by ~130 lines — all the inline check logic moves out.

Note the function signature change: `def` → `async def`. FastAPI handles async route functions natively, no other code change needed.

- [ ] **Step 2: Smoke-test the endpoint.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
APP_ENV=development DATABASE_URL=sqlite:///:memory: .venv/bin/python -c "
import asyncio
from app.database import init_db, SessionLocal
from app.database.models import Workspace
init_db()

from app.services.health import run_all_checks
db = SessionLocal()
ws = db.query(Workspace).filter(Workspace.id == 1).first()
result = asyncio.run(run_all_checks(ws, 1, db))
db.close()

# We expect 4 or 5 checks (vip_channel may be None for non-affiliate workspace)
assert 'overall' in result
assert 'checks' in result
assert len(result['checks']) >= 4
print('overall:', result['overall'])
for c in result['checks']:
    print(f\"  {c['label']:25s} {c['status']:6s} {c['detail'][:60]}\")
print('ok')
"
```

Expected: a health report with 4 checks (no affiliate row exists so `vip_channel` is dropped). Most checks will be `error` or `warn` because no real bot/Telethon/Meta is configured in the in-memory DB. The important thing: it runs without crashing.

- [ ] **Step 3: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/main.py
git commit -m "refactor(api): /health/workspace delegates to services.health.run_all_checks"
```

---

## Task 14: Final integration smoke-test

**Files:**
- (No file changes — full-flow validation only.)

- [ ] **Step 1: Run every test script (Spec A + Spec A.5).**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend

set -e
for t in \
  test_app_meta \
  test_legacy_attribution \
  test_vip_name_promotion \
  test_ensure_contact_rename \
  test_backfill_persists_summary \
  test_pipeline \
  test_health_cache \
  test_health_telegram_bot \
  test_health_operator \
  test_health_signal_forwarding \
  test_health_meta \
  test_health_vip_channel \
  test_health_orchestrator \
; do
  echo "=== $t ==="
  .venv/bin/python -m scripts.$t 2>&1 | tail -3
done
```

Expected: every script ends with `Results: N/N test groups passed`.

- [ ] **Step 2: Cold-boot test on a fresh on-disk SQLite.**

```bash
rm -f /tmp/spec_a5_smoke.db
DATABASE_URL=sqlite:////tmp/spec_a5_smoke.db APP_ENV=development \
  /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend/.venv/bin/python -c "
from app.database import init_db, engine, _get_app_meta
from sqlalchemy import inspect
init_db()
cols = {c['name'] for c in inspect(engine).get_columns('workspaces')}
assert 'last_signal_forwarded_at' in cols, f'missing column'
print('cold-boot ok')
"
rm -f /tmp/spec_a5_smoke.db
```

Expected: `cold-boot ok`.

- [ ] **Step 3: Frontend type-check + build (no changes expected — sanity only).**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/frontend
npx tsc --noEmit && npm run build
```

Expected: tsc exits 0; build succeeds.

- [ ] **Step 4: No commit needed for this task.** Smoke-test only. If anything failed, fix on the failing task — do not paper over with a "test fix" commit.

---

## Self-review notes

| Spec section | Tasks |
|---|---|
| Architecture (extracted module + async endpoint) | 6, 12, 13 |
| Schema (Workspace.last_signal_forwarded_at) | 2 |
| Forwarding pipeline writes timestamp | 3 |
| TTLCache module | 4 |
| Per-check helpers (`_get_bot_user_id`, `_check_bot_in_chat`, `_exception_to_check`) | 6 |
| `check_telegram_bot` | 7 |
| `check_operator_account` | 8 |
| `check_signal_forwarding` | 9 |
| `check_meta` | 10 |
| `check_vip_channel` | 11 |
| Orchestrator (`run_all_checks`) | 12 |
| Endpoint delegation | 13 |
| Test infrastructure (MockHttpClient) | 5 |
| Test coverage targets (~41 tests) | 4, 7, 8, 9, 10, 11, 12 |
| Final integration smoke-test | 14 |

No spec section is unaddressed.

## Out-of-scope reminders (for the engineer)

- Do **not** add a persistent health-event log. No `event_log` table, no trending. Live snapshot only.
- Do **not** add real-API contract tests in CI. Only HTTP-mocked unit tests.
- Do **not** touch the frontend. Endpoint shape stays identical.
- Do **not** add per-destination forwarding timestamps. The `getChatMember` probe gives per-channel resolution at health-check time.
