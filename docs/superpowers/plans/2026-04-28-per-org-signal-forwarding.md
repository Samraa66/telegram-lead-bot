# Per-Org Signal Forwarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make signal forwarding multi-tenant. Each org-owner workspace forwards from its own source channel via its own bot to its own affiliates' VIP channels. Remove env-based fallbacks entirely.

**Architecture:** Refactor `services/forwarding.py` to take `workspace_id` and `bot_token` explicitly (drop env imports, drop platform-wide aggregation). Extend `services/telethon_client.py` with a per-workspace signal handler that registers when `workspace_role='owner'` and `source_channel_id` is set. Delete `handlers/signals.py` and its webhook call site. Branch the frontend onboarding wizard's Step 3 by `org_role` so org owners set `source_channel_id` while sub-affiliates set `vip_channel_id` (and are told to add the *tenant's* bot, not their own).

**Tech Stack:** FastAPI + SQLAlchemy + Telethon (backend); React + Vite + TypeScript + Tailwind (frontend). Tests are script-based in `backend/scripts/test_*.py` matching the existing `test_pipeline.py` style — in-memory SQLite, custom PASS/FAIL prints, run via `python -m scripts.test_<name>`.

**Spec:** See `docs/superpowers/specs/2026-04-28-per-org-signal-forwarding-design.md` for full design rationale.

---

## File Structure

### Backend changes

| File | Change | Responsibility |
|---|---|---|
| `backend/app/services/forwarding.py` | **Rewrite** (smaller) | Per-org destination resolution; copy via explicit `bot_token` arg |
| `backend/app/services/telethon_client.py` | **Extend** | Add `_make_signal_handler` factory; register inside `start_workspace_client` |
| `backend/app/handlers/signals.py` | **Delete** | No longer needed; Telethon-per-org replaces it |
| `backend/app/main.py` | **Modify** (3 small edits) | Drop signals import + call site (Task 8); add `PATCH /workspace/me/source-channel` (Task 9); cycle Telethon on Settings→Telegram source-channel save (Task 10); expose tenant bot username (Task 11) |
| `backend/scripts/test_forwarding.py` | **Create** | Tests for `get_destinations_for_org`, `copy_message`, `copy_signal_for_org` |
| `backend/scripts/test_signal_handler.py` | **Create** | Tests for `_make_signal_handler` factory + registration condition |
| `backend/scripts/test_workspace_source_endpoint.py` | **Create** | Tests for `PATCH /workspace/me/source-channel` |

### Frontend changes

| File | Change | Responsibility |
|---|---|---|
| `frontend/src/pages/OnboardingPage.tsx` | **Modify** | Branch Step 3 by `org_role` — source-channel UI for workspace owners, VIP-channel UI for sub-affiliates |
| `frontend/src/api/auth.ts` | **Modify** | Expose `parent_bot_username` in stored user (read from `/auth/me`) for sub-affiliates' wizard step |

### Environment

| File | Change | Responsibility |
|---|---|---|
| `backend/.env` (VPS only — not in repo) | **Comment out** `SOURCE_CHANNEL_ID`, `DESTINATION_CHANNEL_IDS`, `BOT_TOKEN`, `WEBHOOK_SECRET` | Eliminate legacy fallback so tests prove the DB-first path works |

---

## Task 1: Test fixtures for forwarding

**Files:**
- Create: `backend/scripts/test_forwarding.py` (header + fixtures only in this task)

**Goal:** Set up the in-memory test harness. No assertions yet — that's Task 2 onward.

- [ ] **Step 1: Create the test file with imports and fixtures**

```python
"""
Local forwarding test — runs in-memory (SQLite). No Telegram, no real bot.

Tests:
  1. get_destinations_for_org returns affiliates from the right org tree only
  2. copy_message takes bot_token as an explicit arg
  3. copy_signal_for_org skips when bot_token is NULL
  4. copy_signal_for_org loops all destinations and continues on per-channel failure

Run from backend/:
    python -m scripts.test_forwarding
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base, Workspace, Affiliate, Organization

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label, condition):
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


# ---------------------------------------------------------------------------
# In-memory DB
# ---------------------------------------------------------------------------
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)


def make_org_tree(db):
    """
    Build a two-org tree:
      Org 1: workspace 1 (owner) → workspaces 2, 3 (affiliates A, B)
      Org 2: workspace 4 (owner) → workspaces 5 (affiliate C)
    Returns dict of names → workspace ids.
    """
    db.add(Organization(id=1, name="OrgOne"))
    db.add(Organization(id=2, name="OrgTwo"))

    db.add(Workspace(id=1, name="OrgOne-root", org_id=1, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=1,
                     bot_token="botA-token", source_channel_id="-1001111"))
    db.add(Workspace(id=2, name="OrgOne-AffA", org_id=1, workspace_role="affiliate",
                     parent_workspace_id=1, root_workspace_id=1))
    db.add(Workspace(id=3, name="OrgOne-AffB", org_id=1, workspace_role="affiliate",
                     parent_workspace_id=1, root_workspace_id=1))
    db.add(Workspace(id=4, name="OrgTwo-root", org_id=2, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=4,
                     bot_token="botB-token", source_channel_id="-1002222"))
    db.add(Workspace(id=5, name="OrgTwo-AffC", org_id=2, workspace_role="affiliate",
                     parent_workspace_id=4, root_workspace_id=4))

    # Affiliate rows tied to the affiliate workspaces
    db.add(Affiliate(id=10, name="AffA", workspace_id=1, affiliate_workspace_id=2,
                     vip_channel_id="-100AAA", is_active=True))
    db.add(Affiliate(id=11, name="AffB", workspace_id=1, affiliate_workspace_id=3,
                     vip_channel_id="-100BBB", is_active=True))
    db.add(Affiliate(id=12, name="AffC", workspace_id=4, affiliate_workspace_id=5,
                     vip_channel_id="-100CCC", is_active=True))
    db.commit()
    return {"orgA_root": 1, "orgB_root": 4}


if __name__ == "__main__":
    print("Forwarding tests")
    print("(no assertions yet — fixtures only)")
```

- [ ] **Step 2: Run the file to verify imports and fixtures load cleanly**

Run from `backend/`:
```bash
python -m scripts.test_forwarding
```
Expected: prints "Forwarding tests" + "(no assertions yet — fixtures only)" with no exceptions. If imports fail, fix before proceeding.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/test_forwarding.py
git commit -m "test: scaffold forwarding test fixtures (org tree, affiliates)"
```

---

## Task 2: `get_destinations_for_org` — tests + implementation

**Files:**
- Modify: `backend/scripts/test_forwarding.py`
- Modify: `backend/app/services/forwarding.py`

**Goal:** New function `get_destinations_for_org(workspace_id, db)` returns active-affiliate `vip_channel_id`s belonging to that org's tree.

- [ ] **Step 1: Append failing tests to `test_forwarding.py`**

Add inside `if __name__ == "__main__":`, replacing the placeholder:

```python
if __name__ == "__main__":
    from app.services.forwarding import get_destinations_for_org

    db = Session()
    ids = make_org_tree(db)

    # OrgA's destinations = AffA + AffB (workspaces 2, 3)
    print("Test 1: get_destinations_for_org returns own org's affiliates")
    dests_a = sorted(get_destinations_for_org(ids["orgA_root"], db))
    check("OrgA destinations match [-100AAA, -100BBB]", dests_a == ["-100AAA", "-100BBB"])

    # OrgB's destinations = AffC only (workspace 5)
    print("\nTest 2: orgs are isolated")
    dests_b = get_destinations_for_org(ids["orgB_root"], db)
    check("OrgB destinations match ['-100CCC']", dests_b == ["-100CCC"])

    # Inactive affiliate is excluded
    print("\nTest 3: inactive affiliates excluded")
    aff_a = db.query(Affiliate).filter(Affiliate.id == 10).first()
    aff_a.is_active = False
    db.commit()
    dests_a2 = get_destinations_for_org(ids["orgA_root"], db)
    check("OrgA now has only AffB", dests_a2 == ["-100BBB"])
    aff_a.is_active = True  # reset
    db.commit()

    # NULL vip_channel_id excluded
    print("\nTest 4: affiliates without vip_channel_id excluded")
    aff_b = db.query(Affiliate).filter(Affiliate.id == 11).first()
    aff_b.vip_channel_id = None
    db.commit()
    dests_a3 = get_destinations_for_org(ids["orgA_root"], db)
    check("OrgA now has only AffA", dests_a3 == ["-100AAA"])
    aff_b.vip_channel_id = "-100BBB"  # reset
    db.commit()

    # Org with no affiliates returns empty list
    print("\nTest 5: empty list when no affiliates")
    db.add(Organization(id=3, name="OrgEmpty"))
    db.add(Workspace(id=6, name="OrgEmpty-root", org_id=3, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=6))
    db.commit()
    check("OrgEmpty destinations are []", get_destinations_for_org(6, db) == [])

    db.close()
    print("\nDone.")
```

- [ ] **Step 2: Run tests — expect ImportError on `get_destinations_for_org`**

Run from `backend/`:
```bash
python -m scripts.test_forwarding
```
Expected: `ImportError: cannot import name 'get_destinations_for_org' from 'app.services.forwarding'`

- [ ] **Step 3: Replace `forwarding.py` with the new minimal implementation**

Overwrite `backend/app/services/forwarding.py` entirely:

```python
"""
Per-org signal forwarding.

Each org-owner workspace has its own source channel + bot. Signals are
copied from the source to all active affiliates in that org's tree, using
the org's own bot token. No env fallback. No platform-wide aggregation.
"""

import logging
from typing import List, Optional

import requests
from sqlalchemy.orm import Session

from app.database.models import Affiliate, Workspace

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def get_destinations_for_org(workspace_id: int, db: Session) -> List[str]:
    """
    Return vip_channel_ids of all active affiliates whose workspace
    is in the org tree rooted at workspace_id.
    """
    rows = (
        db.query(Affiliate.vip_channel_id)
        .join(Workspace, Affiliate.affiliate_workspace_id == Workspace.id)
        .filter(
            Workspace.root_workspace_id == workspace_id,
            Affiliate.is_active.is_(True),
            Affiliate.vip_channel_id.isnot(None),
        )
        .all()
    )
    return [ch for (ch,) in rows if ch]
```

(Other functions get added in later tasks. The old functions still exist for now — Task 5 deletes them.)

Wait — overwriting wholesale will break Task 5's deletion test (no callers to remove). Instead, **append** `get_destinations_for_org` and the `Session`/model imports to the existing file without deleting old functions yet. Update the file as follows:

Open `backend/app/services/forwarding.py` and:
1. At the top of imports section, add `from sqlalchemy.orm import Session` and `from app.database.models import Affiliate, Workspace`.
2. After the existing `_parse_csv` helper (before `get_static_destination_channels`), insert the new function:

```python
def get_destinations_for_org(workspace_id: int, db: Session) -> List[str]:
    """
    Return vip_channel_ids of all active affiliates whose workspace
    is in the org tree rooted at workspace_id.
    """
    rows = (
        db.query(Affiliate.vip_channel_id)
        .join(Workspace, Affiliate.affiliate_workspace_id == Workspace.id)
        .filter(
            Workspace.root_workspace_id == workspace_id,
            Affiliate.is_active.is_(True),
            Affiliate.vip_channel_id.isnot(None),
        )
        .all()
    )
    return [ch for (ch,) in rows if ch]
```

- [ ] **Step 4: Run tests — expect 5 PASS**

```bash
python -m scripts.test_forwarding
```
Expected output ends with five `[PASS]` lines.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/test_forwarding.py backend/app/services/forwarding.py
git commit -m "feat(forwarding): add get_destinations_for_org for per-org affiliate lookup"
```

---

## Task 3: `copy_message` refactor — bot_token as explicit arg

**Files:**
- Modify: `backend/scripts/test_forwarding.py`
- Modify: `backend/app/services/forwarding.py`

**Goal:** `copy_message` takes `bot_token` as a parameter instead of reading from env. Returns False when token is empty.

- [ ] **Step 1: Append tests to `test_forwarding.py`**

Insert before the final `db.close()`:

```python
    print("\nTest 6: copy_message returns False when bot_token is empty")
    from app.services.forwarding import copy_message
    result = copy_message("-100SRC", 42, "-100DST", bot_token="")
    check("empty bot_token → False", result is False)

    print("\nTest 7: copy_message uses the bot_token in URL")
    captured_url = {"value": None}
    def fake_post(url, json=None, timeout=None):
        captured_url["value"] = url
        resp = MagicMock()
        resp.status_code = 200
        return resp
    with patch("app.services.forwarding.requests.post", side_effect=fake_post):
        ok = copy_message("-100SRC", 42, "-100DST", bot_token="my-token-XYZ")
    check("returns True on 200", ok is True)
    check("URL contains the bot_token", "my-token-XYZ" in (captured_url["value"] or ""))
```

- [ ] **Step 2: Run tests — expect Test 6/7 to fail (signature mismatch)**

```bash
python -m scripts.test_forwarding
```
Expected: tests 1–5 PASS. Test 6 fails with `TypeError: copy_message() got an unexpected keyword argument 'bot_token'` (current signature reads from env).

- [ ] **Step 3: Replace `copy_message` in `forwarding.py`**

Find the existing `def copy_message(...)` (around line 105). Replace its signature and body with:

```python
def copy_message(
    from_chat_id: str,
    message_id: int,
    destination_chat_id: str,
    bot_token: str,
) -> bool:
    """
    Copy a message between chats using the given bot's token.
    Returns True on success, False on any failure (logged per-channel).
    """
    if not bot_token:
        logger.error("copy_message called with empty bot_token; cannot copy")
        return False
    url = f"{TELEGRAM_API_BASE}{bot_token}/copyMessage"
    payload = {
        "chat_id": destination_chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("Copied signal to channel %s", destination_chat_id)
            return True
        logger.error(
            "Failed copying signal to channel %s: %s %s",
            destination_chat_id, r.status_code, r.text,
        )
        return False
    except Exception as e:
        logger.exception("Error copying to channel %s: %s", destination_chat_id, e)
        return False
```

Also remove the import line `from app.config import BOT_TOKEN, DESTINATION_CHANNEL_IDS` at the top (Task 5 will check for orphan callers, so we leave the old `copy_signal_to_all_destinations` callers alone for now — but they refer to `BOT_TOKEN` indirectly through the OLD `copy_message`. Since we just changed signatures, the OLD `copy_signal_to_all_destinations` will break at call time but isn't called anymore from production code yet — Task 8 deletes it).

Actually, simpler: **also remove `copy_signal_to_all_destinations`** in this step since it depends on the old signature and is only called from `handlers/signals.py:75` which we delete in Task 8. To verify nothing else calls it:

```bash
grep -rn "copy_signal_to_all_destinations" backend/app --include="*.py" | grep -v __pycache__
```

Expected: only `handlers/signals.py:12,75` references. Delete the function from `forwarding.py`.

- [ ] **Step 4: Run tests — expect all 7 PASS**

```bash
python -m scripts.test_forwarding
```
Expected: 7 PASS lines.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/test_forwarding.py backend/app/services/forwarding.py
git commit -m "refactor(forwarding): copy_message takes bot_token as explicit arg, drop env"
```

---

## Task 4: `copy_signal_for_org` orchestration

**Files:**
- Modify: `backend/scripts/test_forwarding.py`
- Modify: `backend/app/services/forwarding.py`

**Goal:** New function `copy_signal_for_org(workspace_id, source_chat_id, message_id, db)` reads workspace's bot token, looks up destinations, loops `copy_message` per destination, continues on per-channel failure.

- [ ] **Step 1: Append tests**

```python
    print("\nTest 8: copy_signal_for_org skips when bot_token is NULL")
    from app.services.forwarding import copy_signal_for_org
    db.add(Workspace(id=7, name="NoBot", org_id=1, workspace_role="owner",
                     root_workspace_id=7, source_channel_id="-100777", bot_token=None))
    db.commit()
    with patch("app.services.forwarding.requests.post") as mock_post:
        copy_signal_for_org(7, "-100777", 42, db)
        check("requests.post not called", mock_post.call_count == 0)

    print("\nTest 9: copy_signal_for_org loops all destinations using workspace's bot")
    captured_calls = []
    def fake_post_orgA(url, json=None, timeout=None):
        captured_calls.append((url, json["chat_id"]))
        resp = MagicMock()
        resp.status_code = 200
        return resp
    with patch("app.services.forwarding.requests.post", side_effect=fake_post_orgA):
        copy_signal_for_org(ids["orgA_root"], "-1001111", 99, db)
    check("posted to 2 destinations (AffA + AffB)", len(captured_calls) == 2)
    check("uses OrgA's bot token in URL", all("botA-token" in u for u, _ in captured_calls))
    captured_chat_ids = sorted([c for _, c in captured_calls])
    check("destinations are AffA + AffB channels",
          captured_chat_ids == ["-100AAA", "-100BBB"])

    print("\nTest 10: per-channel failure does not abort the loop")
    call_log = []
    def fake_post_partial_fail(url, json=None, timeout=None):
        call_log.append(json["chat_id"])
        resp = MagicMock()
        # First destination fails, second succeeds
        resp.status_code = 400 if json["chat_id"] == "-100AAA" else 200
        resp.text = "{}"
        return resp
    with patch("app.services.forwarding.requests.post", side_effect=fake_post_partial_fail):
        copy_signal_for_org(ids["orgA_root"], "-1001111", 100, db)
    check("both destinations attempted despite first failure", len(call_log) == 2)
```

- [ ] **Step 2: Run — expect ImportError or AttributeError on `copy_signal_for_org`**

```bash
python -m scripts.test_forwarding
```
Expected: tests 1–7 PASS, then ImportError.

- [ ] **Step 3: Implement `copy_signal_for_org` in `forwarding.py`**

Append after `copy_message`:

```python
def copy_signal_for_org(
    workspace_id: int,
    source_chat_id: str,
    message_id: int,
    db: Session,
) -> None:
    """
    Orchestrate signal copy for one org:
      1. Fetch the org's bot_token from its workspace row
      2. Fetch destinations (active affiliates in the org tree)
      3. Loop copy_message — log per-channel failures, never abort the loop
    """
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws or not ws.bot_token:
        logger.warning(
            "copy_signal_for_org: ws=%s has no bot_token, skipping signal",
            workspace_id,
        )
        return

    destinations = get_destinations_for_org(workspace_id, db)
    if not destinations:
        logger.info(
            "copy_signal_for_org: ws=%s has no active affiliate destinations",
            workspace_id,
        )
        return

    logger.info(
        "Forwarding signal for ws=%s to %d channel(s)",
        workspace_id, len(destinations),
    )
    for dest_id in destinations:
        copy_message(
            from_chat_id=source_chat_id,
            message_id=message_id,
            destination_chat_id=dest_id,
            bot_token=ws.bot_token,
        )
```

- [ ] **Step 4: Run — expect all 10 PASS**

```bash
python -m scripts.test_forwarding
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/test_forwarding.py backend/app/services/forwarding.py
git commit -m "feat(forwarding): add copy_signal_for_org orchestrator"
```

---

## Task 5: Delete legacy forwarding functions + verify no callers

**Files:**
- Modify: `backend/app/services/forwarding.py`

**Goal:** Remove the now-unused `get_static_destination_channels`, `get_effective_source_channel_id`, `get_all_destination_channels`, and the `BOT_TOKEN` / `DESTINATION_CHANNEL_IDS` env imports.

- [ ] **Step 1: Verify no production code calls the legacy functions**

```bash
cd backend
grep -rn "get_static_destination_channels\|get_effective_source_channel_id\|get_all_destination_channels" app --include="*.py" | grep -v __pycache__ | grep -v "services/forwarding.py:"
```
Expected: only `handlers/signals.py` references (which is deleted in Task 8). If any other file references these, STOP — those callers need migration first; flag and check with the user before proceeding.

- [ ] **Step 2: Delete the three legacy functions and config import**

Edit `backend/app/services/forwarding.py`:
1. Delete `from app.config import BOT_TOKEN, DESTINATION_CHANNEL_IDS` (top of file).
2. Delete `def _parse_csv(...)` if no longer used.
3. Delete `def get_static_destination_channels(...)`.
4. Delete `def get_effective_source_channel_id(...)`.
5. Delete `def get_all_destination_channels(...)`.

The file should now contain only: imports, `TELEGRAM_API_BASE`, `get_destinations_for_org`, `copy_message`, `copy_signal_for_org`.

- [ ] **Step 3: Re-run forwarding tests to confirm nothing broke**

```bash
python -m scripts.test_forwarding
```
Expected: 10 PASS lines.

- [ ] **Step 4: Confirm Python imports cleanly**

```bash
python -c "from app.services import forwarding; print(dir(forwarding))"
```
Expected: lists `copy_message`, `copy_signal_for_org`, `get_destinations_for_org`. No legacy names.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/forwarding.py
git commit -m "refactor(forwarding): drop legacy env-fallback functions"
```

---

## Task 6: `_make_signal_handler` factory in telethon_client.py

**Files:**
- Create: `backend/scripts/test_signal_handler.py`
- Modify: `backend/app/services/telethon_client.py`

**Goal:** Add a per-workspace signal handler factory that, when triggered by a Telethon `NewMessage` event, calls `copy_signal_for_org`.

- [ ] **Step 1: Create the test file**

```python
"""
Test the per-workspace signal handler factory.

Run from backend/:
    python -m scripts.test_signal_handler
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import asyncio

from app.services.telethon_client import _make_signal_handler

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label, condition):
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


async def run():
    print("Test 1: handler closure captures workspace_id")
    handler = _make_signal_handler(workspace_id=42)
    check("returns a coroutine function", asyncio.iscoroutinefunction(handler))

    print("\nTest 2: handler calls copy_signal_for_org with workspace_id and event ids")
    fake_event = MagicMock()
    fake_event.chat_id = -1009999
    fake_event.message.id = 777

    captured = {}
    def fake_copy(workspace_id, source_chat_id, message_id, db):
        captured["ws"] = workspace_id
        captured["src"] = source_chat_id
        captured["msg"] = message_id

    with patch("app.services.telethon_client.copy_signal_for_org", side_effect=fake_copy), \
         patch("app.services.telethon_client.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock()
        mock_sl.return_value.close = MagicMock()
        await handler(fake_event)

    check("workspace_id passed through", captured.get("ws") == 42)
    check("source_chat_id passed through", captured.get("src") == "-1009999")
    check("message_id passed through", captured.get("msg") == 777)


if __name__ == "__main__":
    print("Signal handler tests")
    asyncio.run(run())
    print("\nDone.")
```

- [ ] **Step 2: Run — expect ImportError on `_make_signal_handler`**

```bash
python -m scripts.test_signal_handler
```
Expected: `ImportError: cannot import name '_make_signal_handler'`.

- [ ] **Step 3: Add the factory to `telethon_client.py`**

Open `backend/app/services/telethon_client.py`. After `_make_inbound_handler` (around line 97) and before `send_as_operator` (around line 186), insert:

```python
# ---------------------------------------------------------------------------
# Signal handler — listens to the workspace's source channel and forwards
# ---------------------------------------------------------------------------

def _make_signal_handler(workspace_id: int):
    """
    Closure that fires on new messages in the workspace's source channel.
    Calls copy_signal_for_org which uses the workspace's own bot token
    and routes to that workspace's affiliates only.
    """
    async def handler(event):
        from app.services.forwarding import copy_signal_for_org
        from app.database import SessionLocal

        source_chat_id = str(event.chat_id)
        message_id = event.message.id

        db = SessionLocal()
        try:
            copy_signal_for_org(
                workspace_id=workspace_id,
                source_chat_id=source_chat_id,
                message_id=message_id,
                db=db,
            )
        except Exception as e:
            logger.exception(
                "Signal handler failed: ws=%s msg_id=%s: %s",
                workspace_id, message_id, e,
            )
        finally:
            db.close()
    return handler
```

- [ ] **Step 4: Run — expect 4 PASS**

```bash
python -m scripts.test_signal_handler
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/test_signal_handler.py backend/app/services/telethon_client.py
git commit -m "feat(telethon): add _make_signal_handler factory"
```

---

## Task 7: Register signal handler inside `start_workspace_client`

**Files:**
- Modify: `backend/app/services/telethon_client.py`

**Goal:** When a workspace's Telethon client starts, also register the signal handler IF that workspace is `workspace_role='owner'` AND has `source_channel_id` set.

- [ ] **Step 1: Read `start_workspace_client` to locate the inbound/outgoing handler registration block**

```bash
grep -n "add_event_handler\|start_workspace_client" backend/app/services/telethon_client.py | head -20
```
Identify the function body (around line 223) and the existing `client.add_event_handler(...)` calls for inbound/outgoing.

- [ ] **Step 2: Modify `start_workspace_client` to conditionally register the signal handler**

Inside `start_workspace_client`, after the existing inbound/outgoing handlers are added (and after the workspace row is loaded in that function — if it isn't loaded yet, load it via `db.query(Workspace).filter(Workspace.id == workspace_id).first()`), add:

```python
        # Signal handler — only for org-owner workspaces with a source channel set.
        # Allows tenants to forward their own signal feed to their own affiliates.
        if ws and ws.workspace_role == "owner" and ws.source_channel_id:
            try:
                source_id_int = int(ws.source_channel_id)
            except (TypeError, ValueError):
                logger.warning(
                    "ws=%s source_channel_id=%r is not a valid int; signal handler not registered",
                    workspace_id, ws.source_channel_id,
                )
            else:
                from telethon import events
                client.add_event_handler(
                    _make_signal_handler(workspace_id),
                    events.NewMessage(chats=[source_id_int]),
                )
                logger.info(
                    "Registered signal handler for ws=%s on source=%s",
                    workspace_id, source_id_int,
                )
```

NOTE: `ws` and the DB session need to be in scope here. Read the surrounding code in `start_workspace_client` to confirm the variable name is `ws` and the session lifecycle. If the function doesn't already query the workspace row, add a `SessionLocal()` query at the start of the function and close it at the end (mirror the pattern used in handler factories).

- [ ] **Step 3: Add a startup test that exercises the conditional**

Append to `backend/scripts/test_signal_handler.py` (before the final `print("\nDone.")`):

```python
    print("\nTest 3: handler registration is gated on workspace_role + source_channel_id")
    # We test the *condition* logic, not Telethon itself.
    from app.database.models import Workspace

    def should_register(ws):
        return bool(ws and ws.workspace_role == "owner" and ws.source_channel_id)

    check("owner + source set → register", should_register(
        Workspace(workspace_role="owner", source_channel_id="-100123")) is True)
    check("affiliate + source set → no register", should_register(
        Workspace(workspace_role="affiliate", source_channel_id="-100123")) is False)
    check("owner + no source → no register", should_register(
        Workspace(workspace_role="owner", source_channel_id=None)) is False)
    check("None workspace → no register", should_register(None) is False)
```

- [ ] **Step 4: Run — expect 7 PASS total (4 from before + 3 new)**

```bash
python -m scripts.test_signal_handler
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/test_signal_handler.py backend/app/services/telethon_client.py
git commit -m "feat(telethon): register signal handler for owner workspaces with source_channel_id"
```

---

## Task 8: Delete `handlers/signals.py` and remove its call site

**Files:**
- Delete: `backend/app/handlers/signals.py`
- Modify: `backend/app/main.py` (lines 35, ~242)

**Goal:** Remove the dead webhook-side signal handler. Telethon-per-org handles signal capture now.

- [ ] **Step 1: Verify only main.py imports from `handlers/signals.py`**

```bash
grep -rn "from app.handlers.signals\|from app.handlers import signals\|process_signal_update" backend/app --include="*.py" | grep -v __pycache__
```
Expected: only `main.py:35`, `main.py:242`, and `handlers/signals.py:44` (the function definition itself). If any other file references it, flag and stop.

- [ ] **Step 2: Edit `backend/app/main.py`**

Remove line 35:
```python
from app.handlers.signals import process_signal_update
```

Find the call site near line 242 (inside the workspace webhook handler):
```python
            await loop.run_in_executor(None, process_signal_update, body)
```
Delete this line (and the surrounding `if`/`try` block ONLY if it has no other purpose — read 5 lines of context to confirm). The comment explaining "process channel posts as signals" should also be removed.

- [ ] **Step 3: Delete the signals handler file**

```bash
rm backend/app/handlers/signals.py
```

- [ ] **Step 4: Boot smoke test — service starts without import errors**

```bash
cd backend
python -c "from app.main import app; print('imports ok')"
```
Expected: prints `imports ok`. If `ModuleNotFoundError: No module named 'app.handlers.signals'` appears, an import was missed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git rm backend/app/handlers/signals.py
git commit -m "refactor: remove webhook-side signal handler (Telethon-per-org replaces it)"
```

---

## Task 9: New endpoint `PATCH /workspace/me/source-channel`

**Files:**
- Create: `backend/scripts/test_workspace_source_endpoint.py`
- Modify: `backend/app/main.py`

**Goal:** New endpoint for org owners to set/update their workspace's `source_channel_id`. Cycles the Telethon client after writing so the new channel takes effect immediately.

- [ ] **Step 1: Create the test file**

```python
"""
Test PATCH /workspace/me/source-channel — writes source_channel_id and
cycles the Telethon client.

Run from backend/:
    python -m scripts.test_workspace_source_endpoint
"""

import os
import sys
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DEVELOPER_USERNAME"] = "dev"
os.environ["DEVELOPER_PASSWORD"] = "devpw"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base, Workspace, Organization
from app.main import app
from app.database import SessionLocal as RealSessionLocal
from app import database as db_module
from app.auth import create_access_token

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label, condition):
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


# Swap real engine for in-memory
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
TestSession = sessionmaker(bind=engine)
db_module.SessionLocal = TestSession  # type: ignore

# Seed
with TestSession() as db:
    db.add(Organization(id=1, name="OrgOne"))
    db.add(Workspace(id=10, name="OrgOne-root", org_id=1, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=10,
                     bot_token="botA"))
    db.commit()

# Token for workspace owner of ws 10
token = create_access_token({
    "sub": "owner10",
    "role": "affiliate",
    "workspace_id": 10,
    "org_id": 1,
    "org_role": "workspace_owner",
})

client = TestClient(app)

print("Test 1: PATCH writes source_channel_id and cycles Telethon")
cycle_calls = []
async def fake_stop(ws_id):
    cycle_calls.append(("stop", ws_id))
async def fake_start(ws_id, *args, **kwargs):
    cycle_calls.append(("start", ws_id))

with patch("app.services.telethon_client.stop_workspace_client", side_effect=fake_stop), \
     patch("app.services.telethon_client.start_workspace_client", side_effect=fake_start):
    resp = client.patch(
        "/workspace/me/source-channel",
        json={"source_channel_id": "-1003333"},
        headers={"Authorization": f"Bearer {token}"},
    )

check("status 200", resp.status_code == 200)

with TestSession() as db:
    ws = db.query(Workspace).filter(Workspace.id == 10).first()
    check("DB row updated", ws.source_channel_id == "-1003333")

check("stop_workspace_client called", any(c[0] == "stop" for c in cycle_calls))
check("start_workspace_client called", any(c[0] == "start" for c in cycle_calls))

print("\nTest 2: rejects non-workspace-owner")
aff_token = create_access_token({
    "sub": "aff",
    "role": "affiliate",
    "workspace_id": 11,
    "org_id": 1,
    "org_role": "affiliate",
})
resp = client.patch(
    "/workspace/me/source-channel",
    json={"source_channel_id": "-100ZZZZ"},
    headers={"Authorization": f"Bearer {aff_token}"},
)
check("non-owner gets 403", resp.status_code == 403)

print("\nDone.")
```

- [ ] **Step 2: Run — expect 404 on PATCH (endpoint doesn't exist yet)**

```bash
python -m scripts.test_workspace_source_endpoint
```
Expected: Test 1 fails — `status 200` is False, response is 404.

- [ ] **Step 3: Add the endpoint to `main.py`**

Locate a logical home — near the other `/workspace/...` or `/settings/...` endpoints, or near `create_org_workspace` (around line 478). Insert:

```python
class WorkspaceSourceChannelRequest(BaseModel):
    source_channel_id: str


@app.patch("/workspace/me/source-channel")
async def update_workspace_source_channel(
    req: WorkspaceSourceChannelRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_workspace_owner),
):
    """
    Set the org owner's source channel. Cycles their Telethon client so the
    new channel's signal handler activates without a service restart.
    """
    from app.services.telethon_client import stop_workspace_client, start_workspace_client
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH

    ws_id = current_user["workspace_id"]
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws.source_channel_id = req.source_channel_id.strip()
    db.commit()

    # Cycle the Telethon client so the new source channel handler activates
    if ws.telethon_session:
        await stop_workspace_client(ws_id)
        await start_workspace_client(ws_id, ws.telethon_session, TELEGRAM_API_ID, TELEGRAM_API_HASH)

    return {"ok": True, "source_channel_id": ws.source_channel_id}
```

If `Workspace`, `Session`, `BaseModel`, or `HTTPException` aren't already imported at the top of `main.py`, verify they are. (Most are.)

- [ ] **Step 4: Run — expect both PASS**

```bash
python -m scripts.test_workspace_source_endpoint
```
Expected: 5 PASS lines (status 200, DB updated, stop called, start called, non-owner 403).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/test_workspace_source_endpoint.py backend/app/main.py
git commit -m "feat: PATCH /workspace/me/source-channel — owner sets source, cycles Telethon"
```

---

## Task 10: Audit existing source_channel_id write sites and add Telethon cycle

**Files:**
- Modify: `backend/app/main.py`

**Goal:** Find every endpoint that writes `Workspace.source_channel_id` and ensure it cycles the Telethon client after the write. Today only Task 9's new endpoint does this. The Settings → Telegram → Signal Forwarding section also writes this field (per `d222b47`) and almost certainly skips the cycle.

- [ ] **Step 1: Find existing write sites**

```bash
grep -rn "source_channel_id\s*=" backend/app/main.py | grep -v "==" | grep -v "is None"
```
Expected: 1+ existing endpoints (Settings → Telegram save). For each one not already cycling Telethon, list the line numbers.

- [ ] **Step 2: Read 30 lines of context around each write site**

For each line N from Step 1:
```bash
sed -n "$((N-15)),$((N+15))p" backend/app/main.py
```
Confirm whether `stop_workspace_client` / `start_workspace_client` is already called. If yes — skip. If no — Step 3.

- [ ] **Step 3: For each endpoint that writes source_channel_id without cycling, add the cycle**

After the existing `db.commit()` in that endpoint, insert (matching the pattern from Task 9):

```python
    from app.services.telethon_client import stop_workspace_client, start_workspace_client
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
    if ws.telethon_session:
        await stop_workspace_client(ws_id)
        await start_workspace_client(ws_id, ws.telethon_session, TELEGRAM_API_ID, TELEGRAM_API_HASH)
```

Make the endpoint `async def` if it isn't already. If the endpoint also writes `destination_channel_ids` or other unrelated fields, the cycle is still cheap — keep it.

- [ ] **Step 4: Manual verification (no test for this — endpoint shape varies)**

Boot the service, log in as a workspace owner, change source channel via Settings → Telegram → Signal Forwarding, watch logs:
```bash
sudo journalctl -u telegrambot -f | grep -E "Stopping|Starting|signal handler"
```
Expected: log lines showing stop+start cycle on save.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "fix: cycle Telethon on all source_channel_id writes so handler picks up changes"
```

---

## Task 11: Expose tenant's bot username for sub-affiliate wizard

**Files:**
- Modify: `backend/app/main.py` (extend `/auth/me` response)
- Modify: `frontend/src/api/auth.ts`

**Goal:** Sub-affiliates need to add the *tenant's* bot (their parent's bot) as admin in their VIP channel — not their own bot. The frontend wizard needs to display the tenant's bot username during Step 3.

- [ ] **Step 1: Find the `/auth/me` endpoint in `main.py`**

```bash
grep -n "/auth/me\|def me\b" backend/app/main.py
```

- [ ] **Step 2: Read the existing `/auth/me` handler to find the response shape**

```bash
grep -n "/auth/me" backend/app/main.py
```

Open `backend/app/main.py` at that line. Identify the variable name of the dict being returned (commonly `data`, `response`, or returned directly via `return {...}`). Note its line range.

- [ ] **Step 3: Extend the response with `parent_bot_username`**

Inside the `/auth/me` handler, before the `return` statement, insert this block. If the handler currently does `return {...}` directly, refactor first into `data = {...}` then `data["parent_bot_username"] = parent_bot_username` then `return data`.

```python
    # Resolve the tenant's bot username for sub-affiliate onboarding UI.
    # Org owners themselves don't need it (their wizard branches to source-channel).
    parent_bot_username = None
    if current_user.get("org_role") != "workspace_owner":
        ws = db.query(Workspace).filter(Workspace.id == current_user.get("workspace_id")).first()
        if ws and ws.parent_workspace_id:
            parent = db.query(Workspace).filter(Workspace.id == ws.parent_workspace_id).first()
            if parent and parent.bot_token:
                import requests as _r
                try:
                    r = _r.get(
                        f"https://api.telegram.org/bot{parent.bot_token}/getMe",
                        timeout=5,
                    )
                    if r.status_code == 200:
                        parent_bot_username = r.json().get("result", {}).get("username")
                except Exception:
                    pass
    data["parent_bot_username"] = parent_bot_username
```

(Replace `data` with the actual variable name from Step 2 if different. Replace `current_user` with the actual current-user dict variable used by the handler — usually from `Depends(get_current_user)`.)

- [ ] **Step 3: Update `frontend/src/api/auth.ts`**

In the `getStoredUser` interface and read paths, add `parent_bot_username?: string | null`. Find:

```typescript
export function getStoredUser(): { username: string; role: Role; workspace_id: number; ... onboarding_complete: boolean } | null {
```

Add `parent_bot_username?: string | null` to both the type and the return-default object.

In the login response handler (where `auth.ts` saves user data after login), persist `parent_bot_username` from the response.

- [ ] **Step 4: Boot test — call `/auth/me` as a sub-affiliate, expect field present**

(Manual — no automated test here because it requires a running Telegram bot for `getMe`. Skip if no bot is available; the field will just be `null`, which is acceptable fallback.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py frontend/src/api/auth.ts
git commit -m "feat: expose parent_bot_username on /auth/me for sub-affiliate wizard"
```

---

## Task 12: Branch onboarding wizard Step 3 by org_role

**Files:**
- Modify: `frontend/src/pages/OnboardingPage.tsx`

**Goal:** When the wizard reaches Step 3, branch on `getStoredUser().org_role`:
- `workspace_owner` → "Connect your signal source channel" UI; PATCH to `/workspace/me/source-channel`.
- anything else (affiliate sub-affiliate) → existing "Link your VIP channel" UI, but the displayed bot username comes from `parent_bot_username` instead of "the bot you created in step 1".

- [ ] **Step 1: Read the existing `StepChannel` component (lines ~260-345)**

Confirm its current structure: detected channels picker, manual input, submit handler that PATCHes `/affiliate/me/checklist`.

- [ ] **Step 2: Replace `StepChannel` with a branched version**

Rename the existing `StepChannel` to `StepVipChannel` (its current behavior — for sub-affiliates). Add a new `StepSourceChannel` (for workspace owners). Add a top-level `StepChannel` that picks based on `org_role`.

```tsx
// Step 3 — branched
function StepChannel({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const user = getStoredUser();
  if (user?.org_role === "workspace_owner") {
    return <StepSourceChannel onDone={onDone} onSkip={onSkip} />;
  }
  return <StepVipChannel onDone={onDone} onSkip={onSkip} />;
}

// For workspace owners — paste source channel ID
function StepSourceChannel({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const [channelId, setChannelId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!channelId.trim()) return;
    setLoading(true); setError(null);
    try {
      await api("PATCH", "/workspace/me/source-channel", { source_channel_id: channelId.trim() });
      onDone();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Connect your Signal Source channel</h2>
        <p className="text-sm text-muted-foreground mt-1">
          The Telegram channel that posts your trade signals. Each new post here will be copied
          to every active affiliate's VIP channel automatically. Your Telegram user must be a
          member or admin of this channel.
        </p>
      </div>

      <div className="surface-card p-4 space-y-2 text-xs text-muted-foreground">
        <p className="eyebrow text-foreground">How it works</p>
        <ol className="list-decimal list-inside space-y-1 leading-relaxed">
          <li>Open the channel in Telegram and copy its ID (starts with <code>-100</code>) or username</li>
          <li>Paste it below and save</li>
          <li>Every new post will be mirrored into your affiliates' channels</li>
        </ol>
      </div>

      <div className="space-y-1.5">
        <label className="eyebrow">Source channel ID or @username</label>
        <input
          value={channelId}
          onChange={(e) => setChannelId(e.target.value)}
          placeholder="-1001234567890 or @yoursignals"
          className="w-full px-3 py-2.5 rounded-lg border border-border bg-secondary/40 text-sm"
        />
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={loading || !channelId.trim()}
          onClick={handleSubmit}
          className="flex-1 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm disabled:opacity-50"
        >
          {loading ? "Saving…" : "Save and continue"}
        </button>
        <button
          type="button"
          onClick={onSkip}
          className="px-4 py-2.5 rounded-lg border border-border text-sm"
        >
          Skip
        </button>
      </div>
    </div>
  );
}

// Existing flow renamed — same logic, with one copy change
function StepVipChannel({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const parentBotUsername = getStoredUser()?.parent_bot_username;
  const botLabel = parentBotUsername ? `@${parentBotUsername}` : "your sponsor's bot";

  // ... rest of body is the existing StepChannel unchanged, EXCEPT one line:
  //
  // FIND in the "How it works" <ol>:
  //     <li>Search for <span className="font-medium text-foreground">the bot you created in step 1</span> ...
  //
  // REPLACE that <li>'s text with:
  //     <li>Search for <span className="font-medium text-foreground">{botLabel}</span> and add it as admin (with permission to post messages)</li>
  //
  // Everything else (detected channels picker, manual input, submit handler PATCHing /affiliate/me/checklist) stays identical.
}
```

Concretely, the rename + edit:
1. Cut the entire body of the existing `StepChannel` function (lines ~260-345 of `OnboardingPage.tsx`).
2. Paste it into the new `StepVipChannel` function defined above.
3. At the top of `StepVipChannel`, add the two `const` lines (`parentBotUsername`, `botLabel`).
4. Replace the one `<li>` matching the FIND text above with the REPLACE text.
5. Do not change `handleSubmit` — sub-affiliates still PATCH `/affiliate/me/checklist`.

- [ ] **Step 3: Type-check**

```bash
cd frontend
npx tsc --noEmit
```
Expected: 0 errors. If `org_role` or `parent_bot_username` aren't on the user type, return to Task 11 and confirm `auth.ts` was updated.

- [ ] **Step 4: Build**

```bash
npm run build
```
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/OnboardingPage.tsx
git commit -m "feat(onboarding): branch wizard Step 3 by org_role (source vs VIP)"
```

---

## Task 13: Comment out env vars on VPS + verify dormant state

**Files:**
- Modify: `backend/.env` on VPS only (not in repo)

**Goal:** Eliminate the legacy fallback so the test in Task 14 proves the DB-first path actually works. This is a config change on the VPS, not a code commit.

- [ ] **Step 1: SSH to VPS and back up `.env`**

```bash
ssh root@<vps>
cp ~/telegram-lead-bot/backend/.env ~/backups/pre-reset-20260428-131403/.env.task13-backup
```

- [ ] **Step 2: Comment the four legacy vars**

```bash
nano ~/telegram-lead-bot/backend/.env
```

Prepend `#` to each of:
- `SOURCE_CHANNEL_ID=...`
- `DESTINATION_CHANNEL_IDS=...`
- `BOT_TOKEN=...`
- `WEBHOOK_SECRET=...`

Leave alone: `DATABASE_URL`, `SECRET_KEY`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `APP_BASE_URL`, all `*_USERNAME`/`*_PASSWORD`.

- [ ] **Step 3: Pull latest code, rebuild frontend, restart service**

```bash
cd ~/telegram-lead-bot
git pull
cd frontend && npm run build && cd ..
sudo systemctl restart telegrambot
sleep 5
sudo systemctl status telegrambot --no-pager | head -15
```

- [ ] **Step 4: Verify dormancy**

```bash
sudo journalctl -u telegrambot -n 50 --no-pager | grep -iE "signal|forward|telethon|webhook"
```
Expected: no "Forwarding signal …" or "Copied signal …" lines. Telethon clients may start (existing inbound/outgoing handlers), but no signal handler registers because workspace 1 has NULL `source_channel_id` (per spec, no migration was performed).

- [ ] **Step 5: No commit needed (env edits are out-of-repo).**

---

## Task 14: End-to-end manual verification

**Files:** none (manual workflow on VPS)

**Goal:** Prove the refactor works by onboarding a fresh tenant and watching their signal forward to their affiliates only.

- [ ] **Step 1: Sameer logs in as `developer`**

Browser → https://telelytics.org → log in with developer credentials.

- [ ] **Step 2: Invite a tenant via existing affiliate-creation endpoint with `parent_workspace_id=1`**

`/affiliates` page → "Add Affiliate" form → fill name + login username. Backend returns invite URL. Copy it.

- [ ] **Step 3: Open invite URL in incognito → tenant signs up**

The tenant sets a password. JWT issued with `org_role=workspace_owner`, `workspace_id=N` (next available id). Wizard runs.

- [ ] **Step 4: Tenant completes wizard**

- Step 1: pastes BotFather token → registers webhook
- Step 2: OTP login with their Telegram user → Telethon session saved
- Step 3 (branched): "Connect your Signal Source channel" → pastes source channel ID

After finish, the tenant's Telethon client has the signal handler registered (verified in journalctl: `Registered signal handler for ws=N on source=...`).

- [ ] **Step 5: Tenant invites two sub-affiliates via `/affiliates` page**

Each invite URL goes to a separate browser/incognito window. Each sub-affiliate signs up, completes wizard:
- Step 1: their own bot
- Step 2: their own Telethon
- Step 3 (VIP branch): VIP channel — instructional text now reads "add `@<tenant_bot>` as admin"

The sub-affiliate adds the tenant's bot as admin in their VIP channel, pastes channel ID.

- [ ] **Step 6: Post a test message in the tenant's source channel**

Use the tenant's Telegram user account → post any text in the source channel.

- [ ] **Step 7: Watch logs**

```bash
sudo journalctl -u telegrambot -f | grep -E "Forwarding signal|Copied signal|signal handler"
```

Expected lines (within ~2 seconds of the source post):
- `Forwarding signal for ws=N to 2 channel(s)`
- `Copied signal to channel <vip_aff_1>`
- `Copied signal to channel <vip_aff_2>`

The bot token used in URL: tenant's, not env's. Workspace 1 emits no signal traffic (it has NULL `source_channel_id`).

- [ ] **Step 8: Tear down — leave system running for next session**

No commit. No code changes. If anything fails, see Rollback section in spec.

---

## Open follow-ups (not in this plan)

- **Lead-capture webhook still reads env `BOT_TOKEN` and `WEBHOOK_SECRET`** for workspace 1 fallback. Should be DB-first too. Separate task.
- **Backups cron is broken** (`/var/backups/telelytics/*.sql` are 707-byte empty dumps). Fix as a separate task; the dump we took manually is sufficient as rollback for this refactor.
- **`app/config.py` still defines `BOT_TOKEN`, `DESTINATION_CHANNEL_IDS`, `SOURCE_CHANNEL_ID` constants** read from env. After this refactor those constants are unused by `forwarding.py` but may still be read by the lead-capture webhook (above). Delete only when both refactors land.
