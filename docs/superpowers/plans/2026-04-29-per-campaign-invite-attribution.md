# Per-Campaign Telegram Invite-Link Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore per-campaign attribution by minting a unique Telegram channel invite link per `Campaign`, listening for joins through Telethon, and claiming the pending campaign tag on the user's first bot DM.

**Architecture:** New `services/attribution.py` module owns the four pure-function building blocks (`mint_invite_link`, `resolve_attribution_channel`, `handle_channel_join`, `claim_pending_attribution`) plus a hash extractor. A new `GET /attribution/invite` endpoint composes them into a public, CORS-allowlisted, IP-rate-limited landing-page-callable response. Telethon's `events.ChatAction` records each join into an append-only `channel_join_events` log; `ensure_contact` in `handlers/leads.py` claims the most recent unclaimed row when the user later DMs the bot. Daily cleanup TTL'd at 90 days.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + Telethon (`ExportChatInviteRequest`, `events.ChatAction`) + APScheduler + SlowAPI rate-limiting + script-style tests via `MockHttpClient` + a mocked Telethon client.

---

## File map

**Modify:**
- `backend/app/database/models.py` — `Workspace.attribution_channel_id`, new `CampaignInviteLink` model, new `ChannelJoinEvent` model
- `backend/app/database/__init__.py` — `_ensure_columns()` adds the column; `Base.metadata.create_all` picks up the new tables on init
- `backend/app/handlers/leads.py` — `ensure_contact` extension to claim pending attribution
- `backend/app/services/telethon_client.py` — register `events.ChatAction` handler in `start_workspace_client` when `attribution_channel_id` is set
- `backend/app/services/scheduler.py` — daily cleanup job for unclaimed `channel_join_events` rows
- `backend/app/main.py` — `GET /attribution/invite` endpoint + extended `/campaigns` response shape
- `frontend/src/pages/AnalyticsDashboard.tsx` — render the new `CampaignLinkModal` after creation; show new columns in campaigns table
- `frontend/src/api/campaigns.ts` (or wherever the campaign types live; verified at Task 14)

**Create:**
- `backend/app/services/attribution.py` — `_extract_hash`, `resolve_attribution_channel`, `mint_invite_link`, `handle_channel_join`, `claim_pending_attribution`, `cleanup_old_join_events`
- `frontend/src/components/CampaignLinkModal.tsx` — three-link result modal + JS-snippet block + selector input
- `backend/scripts/test_attribution_models.py`
- `backend/scripts/test_attribution_helpers.py` — `_extract_hash`, `resolve_attribution_channel`, `mint_invite_link`
- `backend/scripts/test_attribution_endpoint.py` — `GET /attribution/invite`
- `backend/scripts/test_attribution_telethon.py` — `handle_channel_join`
- `backend/scripts/test_attribution_claim.py` — `claim_pending_attribution` + integration with `ensure_contact`
- `backend/scripts/test_attribution_cleanup.py` — `cleanup_old_join_events`

---

## Task 1: Add `Workspace.attribution_channel_id` column

**Files:**
- Modify: `backend/app/database/models.py`
- Modify: `backend/app/database/__init__.py`

- [ ] **Step 1: Add the column to the Workspace model.**

In `backend/app/database/models.py`, locate the `Workspace` class. Find the existing `last_signal_forwarded_at` line (added in Spec A.5). Add the new column immediately after it:

```python
    last_signal_forwarded_at = Column(DateTime, nullable=True)
    # Numeric channel ID for the public channel used in per-campaign invite-link
    # attribution (Spec B). Lazily resolved from main_channel_url by
    # services/attribution.py:resolve_attribution_channel on first use.
    attribution_channel_id = Column(BigInteger, nullable=True)
```

If `BigInteger` isn't already imported at the top of models.py, add it to the SQLAlchemy import line.

- [ ] **Step 2: Add the column to `_ensure_columns()`.**

In `backend/app/database/__init__.py`, find the `ws_needed` list inside `if _table_exists("workspaces"):`. Append:

```python
            ("attribution_channel_id", "BIGINT"),
```

- [ ] **Step 3: Smoke-test the column shows up.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
DATABASE_URL=sqlite:///:memory: APP_ENV=development .venv/bin/python -c "
from app.database import init_db, engine
from sqlalchemy import inspect
init_db()
cols = {c['name'] for c in inspect(engine).get_columns('workspaces')}
assert 'attribution_channel_id' in cols, f'missing column: {cols}'
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 4: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/database/models.py backend/app/database/__init__.py
git commit -m "feat(models): add Workspace.attribution_channel_id"
```

---

## Task 2: Add `CampaignInviteLink` and `ChannelJoinEvent` models + tests

**Files:**
- Modify: `backend/app/database/models.py`
- Create: `backend/scripts/test_attribution_models.py`

- [ ] **Step 1: Write the failing schema test.**

Create `backend/scripts/test_attribution_models.py`:

```python
"""
Tests for CampaignInviteLink and ChannelJoinEvent schema.
Run from backend/:  python -m scripts.test_attribution_models
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import inspect
from app.database import init_db, engine, SessionLocal

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_invite_links_table_exists_with_required_columns():
    print("\n=== Test 1: campaign_invite_links table + columns ===")
    init_db()
    insp = inspect(engine)
    tbls = set(insp.get_table_names())
    if not check("table 'campaign_invite_links' exists", "campaign_invite_links" in tbls):
        return False
    cols = {c["name"] for c in insp.get_columns("campaign_invite_links")}
    needed = {"id", "workspace_id", "campaign_id", "source_tag", "channel_id",
              "invite_link", "invite_link_hash", "created_at", "revoked_at"}
    return check(f"all required columns present (got {sorted(cols)})", needed.issubset(cols))


def test_invite_links_unique_constraint():
    print("\n=== Test 2: campaign_invite_links unique (workspace_id, campaign_id, channel_id) ===")
    init_db()
    insp = inspect(engine)
    uqs = insp.get_unique_constraints("campaign_invite_links")
    found = any(
        set(u["column_names"]) == {"workspace_id", "campaign_id", "channel_id"}
        for u in uqs
    )
    return check(f"unique constraint present (got {uqs})", found)


def test_invite_links_index_on_hash():
    print("\n=== Test 3: campaign_invite_links has index on invite_link_hash ===")
    init_db()
    insp = inspect(engine)
    idxs = insp.get_indexes("campaign_invite_links")
    found = any("invite_link_hash" in i["column_names"] for i in idxs)
    return check(f"index on invite_link_hash present (got {idxs})", found)


def test_join_events_table_exists_with_required_columns():
    print("\n=== Test 4: channel_join_events table + columns ===")
    init_db()
    insp = inspect(engine)
    tbls = set(insp.get_table_names())
    if not check("table 'channel_join_events' exists", "channel_join_events" in tbls):
        return False
    cols = {c["name"] for c in insp.get_columns("channel_join_events")}
    needed = {"id", "workspace_id", "telegram_user_id", "channel_id", "source_tag",
              "invite_link_hash", "joined_at", "claimed_contact_id", "claimed_at"}
    return check(f"all required columns present (got {sorted(cols)})", needed.issubset(cols))


def test_join_events_index_for_user_lookup():
    print("\n=== Test 5: channel_join_events has lookup index on (workspace_id, telegram_user_id) ===")
    init_db()
    insp = inspect(engine)
    idxs = insp.get_indexes("channel_join_events")
    found = any(
        set(i["column_names"]) >= {"workspace_id", "telegram_user_id"}
        for i in idxs
    )
    return check(f"lookup index present (got {idxs})", found)


def main():
    results = [
        test_invite_links_table_exists_with_required_columns(),
        test_invite_links_unique_constraint(),
        test_invite_links_index_on_hash(),
        test_join_events_table_exists_with_required_columns(),
        test_join_events_index_for_user_lookup(),
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
.venv/bin/python -m scripts.test_attribution_models
```

Expected: at least one FAIL (tables don't exist yet).

- [ ] **Step 3: Add the two models to `models.py`.**

In `backend/app/database/models.py`, append at the bottom of the file (after the existing models):

```python
class CampaignInviteLink(Base):
    """
    Per-(workspace, campaign) Telegram invite link to the attribution channel.
    One row per campaign — minted lazily on the first /attribution/invite call,
    reused thereafter (idempotent).
    """
    __tablename__ = "campaign_invite_links"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "campaign_id", "channel_id",
            name="uq_invite_per_campaign",
        ),
    )

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    source_tag = Column(String(255), nullable=False, index=True)  # denormalised from campaigns.source_tag
    channel_id = Column(BigInteger, nullable=False)
    invite_link = Column(Text, nullable=False)             # full https://t.me/+abc123
    invite_link_hash = Column(String(64), nullable=False, index=True)  # suffix after the +
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class ChannelJoinEvent(Base):
    """
    Append-only log of channel-join events for attribution.
    A row is inserted by the Telethon ChatAction handler on every join we see.
    Claimed when the user later DMs the bot — claimed_contact_id + claimed_at
    track the join → contact attribution mapping.

    Cleanup: services/attribution.py:cleanup_old_join_events deletes rows
    older than 90 days where claimed_contact_id IS NULL.
    """
    __tablename__ = "channel_join_events"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    telegram_user_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    source_tag = Column(String(255), nullable=True)         # NULL for organic joins (recorded for analytics)
    invite_link_hash = Column(String(64), nullable=True)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    claimed_contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    claimed_at = Column(DateTime, nullable=True)


# Index supporting last-touch lookup at claim time.
Index(
    "idx_join_events_user_lookup",
    ChannelJoinEvent.workspace_id,
    ChannelJoinEvent.telegram_user_id,
    ChannelJoinEvent.joined_at.desc(),
)
# Index supporting TTL cleanup query.
Index("idx_join_events_ttl", ChannelJoinEvent.joined_at)
```

If `Index`, `ForeignKey`, `BigInteger`, or `UniqueConstraint` aren't already imported at the top of `models.py`, add them to the SQLAlchemy import line.

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_models
```

Expected: `Results: 5/5 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/database/models.py backend/scripts/test_attribution_models.py
git commit -m "feat(models): add CampaignInviteLink + ChannelJoinEvent tables + tests"
```

---

## Task 3: `services/attribution.py` skeleton + `_extract_hash` helper + tests

**Files:**
- Create: `backend/app/services/attribution.py`
- Create: `backend/scripts/test_attribution_helpers.py`

- [ ] **Step 1: Write the failing test for `_extract_hash`.**

Create `backend/scripts/test_attribution_helpers.py`:

```python
"""
Tests for attribution.py helpers (pure functions only).
Run from backend/:  python -m scripts.test_attribution_helpers
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.attribution import _extract_hash

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_extract_hash_https_form():
    print("\n=== Test 1: https://t.me/+abc123 → 'abc123' ===")
    return check("hash matches", _extract_hash("https://t.me/+abc123") == "abc123")


def test_extract_hash_joinchat_form():
    print("\n=== Test 2: https://t.me/joinchat/abc123 → 'abc123' ===")
    return check("hash matches", _extract_hash("https://t.me/joinchat/abc123") == "abc123")


def test_extract_hash_no_scheme():
    print("\n=== Test 3: t.me/+xyz with no scheme → 'xyz' ===")
    return check("hash matches", _extract_hash("t.me/+xyz") == "xyz")


def test_extract_hash_invalid_returns_none():
    print("\n=== Test 4: garbage URL → None ===")
    return check("returns None", _extract_hash("https://example.com/foo") is None)


def test_extract_hash_empty_returns_none():
    print("\n=== Test 5: empty string → None ===")
    return check("returns None", _extract_hash("") is None)


def main():
    results = [
        test_extract_hash_https_form(),
        test_extract_hash_joinchat_form(),
        test_extract_hash_no_scheme(),
        test_extract_hash_invalid_returns_none(),
        test_extract_hash_empty_returns_none(),
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
.venv/bin/python -m scripts.test_attribution_helpers
```

Expected: `ImportError: cannot import name '_extract_hash' from 'app.services.attribution'` (module doesn't exist yet).

- [ ] **Step 3: Create the attribution.py module skeleton.**

Create `backend/app/services/attribution.py`:

```python
"""
Per-campaign Telegram invite-link attribution (Spec B).

Public functions:
- resolve_attribution_channel(ws, db, client) -> int | None
- mint_invite_link(ws, campaign, db, client) -> CampaignInviteLink
- handle_channel_join(event, db) -> None
- claim_pending_attribution(contact, telegram_user_id, db) -> Optional[str]
- cleanup_old_join_events(db, *, ttl_days=90) -> int
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import (
    CampaignInviteLink, Campaign, ChannelJoinEvent, Contact, Workspace,
)

logger = logging.getLogger(__name__)

# Matches the hash suffix of a Telegram invite link.
# Accepts: https://t.me/+abc123, t.me/+abc123, https://t.me/joinchat/abc123, t.me/joinchat/abc123
_HASH_RE = re.compile(r"(?:t\.me/(?:\+|joinchat/))([A-Za-z0-9_\-]+)")


def _extract_hash(invite_link: str) -> Optional[str]:
    """Pull the hash suffix out of a Telegram invite link URL. Returns None on miss."""
    if not invite_link:
        return None
    m = _HASH_RE.search(invite_link)
    return m.group(1) if m else None


# resolve_attribution_channel — Task 4
# mint_invite_link — Task 5
# handle_channel_join — Task 7
# claim_pending_attribution — Task 9
# cleanup_old_join_events — Task 10
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_helpers
```

Expected: `Results: 5/5 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/attribution.py backend/scripts/test_attribution_helpers.py
git commit -m "feat(attribution): module skeleton + _extract_hash + tests"
```

---

## Task 4: `resolve_attribution_channel` + tests

**Files:**
- Modify: `backend/app/services/attribution.py`
- Modify: `backend/scripts/test_attribution_helpers.py`

- [ ] **Step 1: Append failing tests to `test_attribution_helpers.py`.**

Add these test functions BEFORE `def main()`:

```python
def _make_ws(*, main_url=None, attribution_channel_id=None):
    return Workspace(
        id=1, name="t",
        main_channel_url=main_url,
        attribution_channel_id=attribution_channel_id,
    )


class _MockClient:
    """Stand-in for Telethon. Returns canned entities or raises configured exceptions."""
    def __init__(self, *, entity_id=None, raises=None):
        self._entity_id = entity_id
        self._raises = raises

    async def get_entity(self, url):
        if self._raises:
            raise self._raises
        if self._entity_id is None:
            raise ValueError("no canned entity")
        return type("E", (), {"id": self._entity_id})()


def test_resolve_returns_cached_when_set():
    print("\n=== Test 6: resolve returns Workspace.attribution_channel_id when already set ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    from app.database.models import Workspace
    ws = _make_ws(main_url="t.me/+abc", attribution_channel_id=-1009999)
    got = asyncio.run(resolve_attribution_channel(ws, db=None, client=_MockClient()))
    return check(f"returns -1009999 (got {got!r})", got == -1009999)


def test_resolve_uses_telethon_when_unset():
    print("\n=== Test 7: resolve calls Telethon and writes attribution_channel_id ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    from app.database import init_db, SessionLocal
    init_db()
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        ws.main_channel_url = "https://t.me/+abc123"
        ws.attribution_channel_id = None
        db.commit()
        got = asyncio.run(resolve_attribution_channel(ws, db=db, client=_MockClient(entity_id=-1001)))
        ok1 = check(f"returns -1001 (got {got!r})", got == -1001)
        db.refresh(ws)
        ok2 = check(f"persisted on workspace (got {ws.attribution_channel_id!r})", ws.attribution_channel_id == -1001)
        return ok1 and ok2
    finally:
        db.close()


def test_resolve_returns_none_on_missing_url():
    print("\n=== Test 8: resolve returns None when main_channel_url is empty ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    ws = _make_ws(main_url=None, attribution_channel_id=None)
    got = asyncio.run(resolve_attribution_channel(ws, db=None, client=_MockClient()))
    return check(f"returns None (got {got!r})", got is None)


def test_resolve_returns_none_on_telethon_failure():
    print("\n=== Test 9: resolve returns None when Telethon raises ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    from app.database.models import Workspace
    ws = _make_ws(main_url="t.me/+abc", attribution_channel_id=None)
    got = asyncio.run(resolve_attribution_channel(ws, db=None, client=_MockClient(raises=ValueError("nope"))))
    return check(f"returns None (got {got!r})", got is None)
```

In the `main()` results list, append:

```python
        test_resolve_returns_cached_when_set(),
        test_resolve_uses_telethon_when_unset(),
        test_resolve_returns_none_on_missing_url(),
        test_resolve_returns_none_on_telethon_failure(),
```

Add this import to the top of the test file (with the existing imports):

```python
from app.database.models import Workspace
```

- [ ] **Step 2: Run the tests and verify they fail.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_helpers
```

Expected: `ImportError: cannot import name 'resolve_attribution_channel'`.

- [ ] **Step 3: Implement `resolve_attribution_channel`.**

In `backend/app/services/attribution.py`, replace the `# resolve_attribution_channel — Task 4` comment with:

```python
async def resolve_attribution_channel(
    ws: Workspace, db: Optional[Session], client,
) -> Optional[int]:
    """
    Return the numeric channel ID for the workspace's attribution channel.

    - Reads from cached `Workspace.attribution_channel_id` when set.
    - Otherwise resolves `main_channel_url` via Telethon, persists the result,
      and returns it.
    - Returns None when `main_channel_url` is unset or Telethon resolution fails.
    """
    if ws is None:
        return None
    if ws.attribution_channel_id:
        return int(ws.attribution_channel_id)

    url = (ws.main_channel_url or "").strip() if ws.main_channel_url else ""
    if not url:
        return None
    if client is None:
        return None

    try:
        entity = await client.get_entity(url)
    except Exception as exc:
        logger.warning("attribution: failed to resolve %s: %s", url, exc)
        return None

    chan_id = getattr(entity, "id", None)
    if not chan_id:
        return None
    chan_id = int(chan_id)

    ws.attribution_channel_id = chan_id
    if db is not None:
        db.commit()
    return chan_id
```

- [ ] **Step 4: Run the tests and verify they pass.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_helpers
```

Expected: `Results: 9/9 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/attribution.py backend/scripts/test_attribution_helpers.py
git commit -m "feat(attribution): resolve_attribution_channel with caching + tests"
```

---

## Task 5: `mint_invite_link` + tests

**Files:**
- Modify: `backend/app/services/attribution.py`
- Modify: `backend/scripts/test_attribution_helpers.py`

- [ ] **Step 1: Append failing tests to `test_attribution_helpers.py`.**

Add these test functions BEFORE `def main()`:

```python
class _MockExportInviteClient:
    """
    Mocks Telethon's call(ExportChatInviteRequest(...)) call pattern.
    Returns a canned object with `.link` set to the provided URL.
    """
    def __init__(self, *, link=None, raises=None):
        self._link = link
        self._raises = raises
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request)
        if self._raises:
            raise self._raises
        return type("Inv", (), {"link": self._link})()


def _ensure_campaign(db, *, source_tag="cmp_test"):
    from app.database.models import Campaign
    c = db.query(Campaign).filter(Campaign.source_tag == source_tag).first()
    if c is None:
        c = Campaign(source_tag=source_tag, name="t", is_active=True)
        db.add(c); db.commit(); db.refresh(c)
    return c


def test_mint_creates_row_first_call():
    print("\n=== Test 10: first call creates a CampaignInviteLink row ===")
    import asyncio
    from app.services.attribution import mint_invite_link
    from app.database import init_db, SessionLocal
    from app.database.models import CampaignInviteLink, Workspace
    init_db()
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        c = _ensure_campaign(db, source_tag="cmp_mint1")
        client = _MockExportInviteClient(link="https://t.me/+abc1XYZ")
        got = asyncio.run(mint_invite_link(ws, c, db, client, channel_id=-1001))
        ok1 = check(f"returned link object", got is not None and got.invite_link == "https://t.me/+abc1XYZ")
        ok2 = check(f"hash extracted = abc1XYZ (got {got.invite_link_hash!r})", got.invite_link_hash == "abc1XYZ")
        cnt = db.query(CampaignInviteLink).filter_by(campaign_id=c.id).count()
        ok3 = check(f"one row in db (got {cnt})", cnt == 1)
        return ok1 and ok2 and ok3
    finally:
        db.close()


def test_mint_idempotent():
    print("\n=== Test 11: second call reuses existing row, doesn't call Telethon again ===")
    import asyncio
    from app.services.attribution import mint_invite_link
    from app.database import init_db, SessionLocal
    from app.database.models import CampaignInviteLink, Workspace
    init_db()
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        c = _ensure_campaign(db, source_tag="cmp_mint2")
        # Pre-seed a row.
        existing = CampaignInviteLink(
            workspace_id=ws.id, campaign_id=c.id, source_tag=c.source_tag,
            channel_id=-1001, invite_link="https://t.me/+pre",
            invite_link_hash="pre", created_at=datetime.utcnow(),
        )
        db.add(existing); db.commit()
        client = _MockExportInviteClient(link="https://t.me/+SHOULD_NOT_BE_USED")
        got = asyncio.run(mint_invite_link(ws, c, db, client, channel_id=-1001))
        ok1 = check(f"returns existing row (link={got.invite_link!r})", got.invite_link == "https://t.me/+pre")
        ok2 = check(f"client not invoked (got {len(client.calls)} calls)", len(client.calls) == 0)
        return ok1 and ok2
    finally:
        db.close()


def test_mint_returns_none_on_telethon_failure():
    print("\n=== Test 12: returns None when Telethon raises ===")
    import asyncio
    from app.services.attribution import mint_invite_link
    from app.database import init_db, SessionLocal
    from app.database.models import Workspace
    init_db()
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        c = _ensure_campaign(db, source_tag="cmp_mint3")
        client = _MockExportInviteClient(raises=ValueError("flood"))
        got = asyncio.run(mint_invite_link(ws, c, db, client, channel_id=-1001))
        return check(f"returns None (got {got!r})", got is None)
    finally:
        db.close()
```

Add this import at the top of the test file:

```python
from datetime import datetime
```

In `main()`, append:

```python
        test_mint_creates_row_first_call(),
        test_mint_idempotent(),
        test_mint_returns_none_on_telethon_failure(),
```

- [ ] **Step 2: Run the tests and verify they fail.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_helpers
```

Expected: `ImportError: cannot import name 'mint_invite_link'`.

- [ ] **Step 3: Implement `mint_invite_link`.**

In `backend/app/services/attribution.py`, replace the `# mint_invite_link — Task 5` comment with:

```python
async def mint_invite_link(
    ws: Workspace, campaign: Campaign, db: Session, client, *, channel_id: int,
) -> Optional[CampaignInviteLink]:
    """
    Return the CampaignInviteLink for (workspace, campaign), minting one via
    Telethon's ExportChatInviteRequest if it doesn't exist yet.

    Idempotent — repeat calls reuse the cached row. Returns None if Telethon
    fails (rate limit, kicked from channel, etc.); caller should surface 502.

    The Telethon import is inside the function so test files don't have to
    install Telethon to import this module.
    """
    existing = (
        db.query(CampaignInviteLink)
          .filter_by(
              workspace_id=ws.id, campaign_id=campaign.id, channel_id=channel_id,
          )
          .filter(CampaignInviteLink.revoked_at.is_(None))
          .first()
    )
    if existing is not None:
        return existing

    try:
        from telethon.tl.functions.messages import ExportChatInviteRequest
        result = await client(ExportChatInviteRequest(
            peer=channel_id,
            title=(campaign.name or campaign.source_tag)[:32],
        ))
    except ImportError:
        # Test path: tests pass a callable mock that ignores the request type.
        result = await client(None)
    except Exception as exc:
        logger.warning(
            "attribution: ExportChatInviteRequest failed for ws=%s campaign=%s: %s",
            ws.id, campaign.source_tag, exc,
        )
        return None

    link = getattr(result, "link", None)
    if not link:
        return None

    invite_hash = _extract_hash(link)
    if not invite_hash:
        logger.warning("attribution: could not extract hash from %r", link)
        return None

    row = CampaignInviteLink(
        workspace_id=ws.id,
        campaign_id=campaign.id,
        source_tag=campaign.source_tag,
        channel_id=channel_id,
        invite_link=link,
        invite_link_hash=invite_hash,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
```

- [ ] **Step 4: Run the tests and verify they pass.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_helpers
```

Expected: `Results: 12/12 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/attribution.py backend/scripts/test_attribution_helpers.py
git commit -m "feat(attribution): mint_invite_link idempotent helper + tests"
```

---

## Task 6: `GET /attribution/invite` endpoint + tests

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/scripts/test_attribution_endpoint.py`

- [ ] **Step 1: Write the failing endpoint tests.**

Create `backend/scripts/test_attribution_endpoint.py`:

```python
"""
Tests for GET /attribution/invite.
Run from backend/:  python -m scripts.test_attribution_endpoint
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from app.database import init_db, SessionLocal
from app.database.models import Campaign, CampaignInviteLink, Workspace

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _setup_ws(*, landing_url="https://lp.example.com",
              attribution_channel_id=-1001):
    init_db()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.landing_page_url = landing_url
    ws.main_channel_url = "https://t.me/+publicchan"
    ws.attribution_channel_id = attribution_channel_id
    db.commit()
    db.close()


def _ensure_campaign(*, source_tag, is_active=True):
    db = SessionLocal()
    try:
        c = db.query(Campaign).filter(Campaign.source_tag == source_tag).first()
        if c is None:
            c = Campaign(source_tag=source_tag, name=source_tag, is_active=is_active)
            db.add(c); db.commit(); db.refresh(c)
        else:
            c.is_active = is_active
            db.commit()
        return c.id
    finally:
        db.close()


def _patch_attribution(routes):
    """
    Monkey-patch app.services.attribution.{resolve_attribution_channel,
    mint_invite_link} with stubs returning the given fixtures.
    """
    from app.services import attribution as attr
    saved = (attr.resolve_attribution_channel, attr.mint_invite_link)

    async def fake_resolve(ws, db, client):
        return routes.get("resolve")

    async def fake_mint(ws, campaign, db, client, *, channel_id):
        result = routes.get("mint")
        if isinstance(result, Exception):
            raise result
        return result

    attr.resolve_attribution_channel = fake_resolve
    attr.mint_invite_link = fake_mint
    return saved


def _restore_attribution(saved):
    from app.services import attribution as attr
    attr.resolve_attribution_channel, attr.mint_invite_link = saved


def _client():
    from app.main import app
    return TestClient(app)


def test_403_when_origin_not_allowed():
    print("\n=== Test 1: 403 when Origin not in workspace allowlist ===")
    _setup_ws(landing_url="https://lp.example.com")
    _ensure_campaign(source_tag="cmp_a")
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_a"},
                          headers={"Origin": "https://evil.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=403 (got {r.status_code})", r.status_code == 403)


def test_404_unknown_campaign():
    print("\n=== Test 2: 404 unknown_campaign when src has no Campaign row ===")
    _setup_ws()
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_does_not_exist"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    ok1 = check(f"status=404 (got {r.status_code})", r.status_code == 404)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok2 = check(f"body says unknown_campaign (got {body!r})", body.get("error") == "unknown_campaign")
    return ok1 and ok2


def test_502_channel_unreachable():
    print("\n=== Test 3: 502 when resolve returns None ===")
    _setup_ws(attribution_channel_id=None)
    _ensure_campaign(source_tag="cmp_b")
    saved = _patch_attribution({"resolve": None, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_b"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=502 (got {r.status_code})", r.status_code == 502)


def test_502_when_mint_returns_none():
    print("\n=== Test 4: 502 when mint returns None (Telethon failure) ===")
    _setup_ws()
    _ensure_campaign(source_tag="cmp_c")
    saved = _patch_attribution({"resolve": -1001, "mint": None})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_c"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=502 (got {r.status_code})", r.status_code == 502)


def test_200_returns_invite_link():
    print("\n=== Test 5: 200 returns invite_link, campaign, channel_id ===")
    _setup_ws()
    _ensure_campaign(source_tag="cmp_d")
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+ok123")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_d"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    ok1 = check(f"status=200 (got {r.status_code})", r.status_code == 200)
    body = r.json() if ok1 else {}
    ok2 = check(f"invite_link present (got {body!r})", body.get("invite_link") == "https://t.me/+ok123")
    ok3 = check(f"campaign='cmp_d'", body.get("campaign") == "cmp_d")
    ok4 = check(f"channel_id=-1001", body.get("channel_id") == -1001)
    ok5 = check(f"CORS header echoes origin",
                r.headers.get("access-control-allow-origin") == "https://lp.example.com")
    return ok1 and ok2 and ok3 and ok4 and ok5


def test_200_www_variant_allowed():
    print("\n=== Test 6: 200 when Origin is the www. variant of landing_page_url ===")
    _setup_ws(landing_url="https://lp.example.com")
    _ensure_campaign(source_tag="cmp_e")
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+ok")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_e"},
                          headers={"Origin": "https://www.lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=200 (got {r.status_code})", r.status_code == 200)


def test_404_inactive_campaign():
    print("\n=== Test 7: 404 when Campaign exists but is_active=False ===")
    _setup_ws()
    _ensure_campaign(source_tag="cmp_inactive", is_active=False)
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_inactive"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=404 (got {r.status_code})", r.status_code == 404)


def _stub_link(url):
    """Construct a fake CampaignInviteLink-shaped object for the stub mint."""
    from app.database.models import CampaignInviteLink
    row = CampaignInviteLink(
        workspace_id=1, campaign_id=999, source_tag="x", channel_id=-1001,
        invite_link=url, invite_link_hash="x",
    )
    return row


def main():
    results = [
        test_403_when_origin_not_allowed(),
        test_404_unknown_campaign(),
        test_502_channel_unreachable(),
        test_502_when_mint_returns_none(),
        test_200_returns_invite_link(),
        test_200_www_variant_allowed(),
        test_404_inactive_campaign(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the tests and verify they fail.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_endpoint
```

Expected: 404s on every test (the route doesn't exist yet).

- [ ] **Step 3: Implement the endpoint in `main.py`.**

In `backend/app/main.py`, find the existing `/health/workspace` endpoint added in Spec A.5. Just AFTER that endpoint, add:

```python
def _origin_allowed_for_workspace(origin: str, landing_page_url: Optional[str]) -> bool:
    """True if `origin` matches the host parsed from `landing_page_url` (or its www. variant)."""
    if not origin or not landing_page_url:
        return False
    try:
        from urllib.parse import urlparse
        lp_host = (urlparse(landing_page_url).hostname or "").lower()
        og_host = (urlparse(origin).hostname or "").lower()
    except Exception:
        return False
    if not lp_host or not og_host:
        return False
    return og_host == lp_host or og_host == f"www.{lp_host}" or lp_host == f"www.{og_host}"


@app.get("/attribution/invite")
@limiter.limit("30/minute")
async def attribution_invite(
    request: Request,
    workspace_id: int,
    src: str,
    db: Session = Depends(get_db),
):
    """
    Public, CORS-allowlisted, IP-rate-limited.
    Returns the campaign-specific invite link for (workspace_id, src).
    """
    from app.database.models import Campaign, Workspace
    from app.services import attribution as _attr
    from app.services.telethon_client import get_client

    origin = request.headers.get("origin", "")

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws or not _origin_allowed_for_workspace(origin, ws.landing_page_url):
        return JSONResponse({"error": "origin_not_allowed"}, status_code=403)

    campaign = (
        db.query(Campaign)
          .filter(Campaign.source_tag == src, Campaign.is_active == True)  # noqa: E712
          .first()
    )
    if not campaign:
        return _attribution_error(origin, "unknown_campaign", 404)

    client = get_client(workspace_id)
    channel_id = await _attr.resolve_attribution_channel(ws, db, client)
    if not channel_id:
        return _attribution_error(origin, "channel_unreachable", 502)

    row = await _attr.mint_invite_link(ws, campaign, db, client, channel_id=channel_id)
    if row is None:
        return _attribution_error(origin, "channel_unreachable", 502)

    return JSONResponse(
        {
            "invite_link": row.invite_link,
            "campaign": campaign.source_tag,
            "channel_id": channel_id,
        },
        headers={
            "Access-Control-Allow-Origin": origin,
            "Cache-Control": "private, max-age=600",
        },
    )


def _attribution_error(origin: str, code: str, status: int):
    return JSONResponse(
        {"error": code},
        status_code=status,
        headers={"Access-Control-Allow-Origin": origin} if origin else {},
    )
```

If `JSONResponse` and `Request` aren't already imported at the top of main.py (they should be — verify), add them:

```python
from fastapi import Request
from fastapi.responses import JSONResponse
```

- [ ] **Step 4: Run the tests and verify they pass.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_endpoint
```

Expected: `Results: 7/7 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/main.py backend/scripts/test_attribution_endpoint.py
git commit -m "feat(attribution): GET /attribution/invite endpoint + tests"
```

---

## Task 7: `handle_channel_join` + tests

**Files:**
- Modify: `backend/app/services/attribution.py`
- Create: `backend/scripts/test_attribution_telethon.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_attribution_telethon.py`:

```python
"""
Tests for handle_channel_join (the pure Telethon ChatAction handler body).
Run from backend/:  python -m scripts.test_attribution_telethon
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime
from app.database import init_db, SessionLocal
from app.database.models import (
    CampaignInviteLink, Campaign, ChannelJoinEvent, Workspace,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


class _FakeAction:
    def __init__(self, *, link=None):
        if link is not None:
            self.invite = type("Inv", (), {"link": link})()


class _FakeMessage:
    def __init__(self, *, link=None):
        self.action = _FakeAction(link=link)


class _FakeEvent:
    def __init__(self, *, user_id, chat_id, link=None, no_action=False):
        self.user_id = user_id
        self.chat_id = chat_id
        if no_action:
            self.action_message = type("M", (), {"action": None})()
        else:
            self.action_message = _FakeMessage(link=link)


def _setup_ws_with_attribution_channel(channel_id=-1001):
    init_db()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.attribution_channel_id = channel_id
    db.commit()
    db.close()


def _seed_invite_link(*, source_tag, hash_, channel_id=-1001):
    db = SessionLocal()
    try:
        c = db.query(Campaign).filter(Campaign.source_tag == source_tag).first()
        if c is None:
            c = Campaign(source_tag=source_tag, name="t", is_active=True)
            db.add(c); db.commit(); db.refresh(c)
        link = CampaignInviteLink(
            workspace_id=1, campaign_id=c.id, source_tag=source_tag,
            channel_id=channel_id, invite_link=f"https://t.me/+{hash_}",
            invite_link_hash=hash_, created_at=datetime.utcnow(),
        )
        db.add(link); db.commit()
    finally:
        db.close()


def test_invite_link_join_writes_attributed_row():
    print("\n=== Test 1: invite-link join creates row with source_tag set ===")
    _setup_ws_with_attribution_channel(-1001)
    _seed_invite_link(source_tag="cmp_a", hash_="HASHA")
    from app.services.attribution import handle_channel_join
    ev = _FakeEvent(user_id=42, chat_id=-1001, link="https://t.me/+HASHA")
    db = SessionLocal()
    try:
        asyncio.run(handle_channel_join(ev, db))
        row = db.query(ChannelJoinEvent).filter_by(telegram_user_id=42).first()
        ok1 = check(f"row exists", row is not None)
        ok2 = check(f"source_tag=cmp_a (got {row.source_tag!r})", row and row.source_tag == "cmp_a")
        ok3 = check(f"invite_link_hash=HASHA (got {row.invite_link_hash!r})",
                    row and row.invite_link_hash == "HASHA")
        return ok1 and ok2 and ok3
    finally:
        db.close()


def test_organic_join_writes_null_source_tag():
    print("\n=== Test 2: join with no invite link → row with NULL source_tag ===")
    _setup_ws_with_attribution_channel(-1001)
    from app.services.attribution import handle_channel_join
    ev = _FakeEvent(user_id=99, chat_id=-1001, no_action=True)
    db = SessionLocal()
    try:
        asyncio.run(handle_channel_join(ev, db))
        row = db.query(ChannelJoinEvent).filter_by(telegram_user_id=99).first()
        ok1 = check(f"row exists", row is not None)
        ok2 = check(f"source_tag is None (got {row.source_tag!r})", row and row.source_tag is None)
        return ok1 and ok2
    finally:
        db.close()


def test_unknown_invite_hash_records_null():
    print("\n=== Test 3: invite link with unrecognised hash → NULL source_tag ===")
    _setup_ws_with_attribution_channel(-1001)
    from app.services.attribution import handle_channel_join
    ev = _FakeEvent(user_id=7, chat_id=-1001, link="https://t.me/+UNKNOWN")
    db = SessionLocal()
    try:
        asyncio.run(handle_channel_join(ev, db))
        row = db.query(ChannelJoinEvent).filter_by(telegram_user_id=7).first()
        ok1 = check(f"row exists", row is not None)
        ok2 = check(f"source_tag is None (got {row.source_tag!r})", row and row.source_tag is None)
        ok3 = check(f"hash=UNKNOWN", row and row.invite_link_hash == "UNKNOWN")
        return ok1 and ok2 and ok3
    finally:
        db.close()


def test_join_to_other_channel_ignored():
    print("\n=== Test 4: join to a channel that's not the attribution channel is ignored ===")
    _setup_ws_with_attribution_channel(-1001)
    from app.services.attribution import handle_channel_join
    ev = _FakeEvent(user_id=11, chat_id=-9999, link="https://t.me/+x")
    db = SessionLocal()
    try:
        before = db.query(ChannelJoinEvent).count()
        asyncio.run(handle_channel_join(ev, db))
        after = db.query(ChannelJoinEvent).count()
        return check(f"no row added (before={before}, after={after})", before == after)
    finally:
        db.close()


def test_handler_does_not_raise_on_malformed_event():
    print("\n=== Test 5: malformed event doesn't crash ===")
    _setup_ws_with_attribution_channel(-1001)
    from app.services.attribution import handle_channel_join
    ev = type("Bad", (), {"user_id": None, "chat_id": -1001, "action_message": None})()
    db = SessionLocal()
    try:
        try:
            asyncio.run(handle_channel_join(ev, db))
            return check("did not raise", True)
        except Exception as e:
            return check(f"raised {type(e).__name__}: {e}", False)
    finally:
        db.close()


def main():
    results = [
        test_invite_link_join_writes_attributed_row(),
        test_organic_join_writes_null_source_tag(),
        test_unknown_invite_hash_records_null(),
        test_join_to_other_channel_ignored(),
        test_handler_does_not_raise_on_malformed_event(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the tests and verify they fail.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_telethon
```

Expected: `ImportError: cannot import name 'handle_channel_join'`.

- [ ] **Step 3: Implement `handle_channel_join`.**

In `backend/app/services/attribution.py`, replace the `# handle_channel_join — Task 7` comment with:

```python
async def handle_channel_join(event, db: Session) -> None:
    """
    Process a Telethon ChatAction join event. Pure async function — does not
    depend on a live Telethon instance, so tests can call it with synthetic
    event objects.

    Records a ChannelJoinEvent row for any join into a workspace's attribution
    channel. Organic joins (no invite link) are recorded with source_tag=NULL
    so we keep channel-growth analytics; attributed joins resolve the campaign
    via invite_link_hash → CampaignInviteLink.source_tag.
    """
    chat_id = getattr(event, "chat_id", None)
    user_id = getattr(event, "user_id", None)
    if not chat_id or not user_id:
        return

    ws = db.query(Workspace).filter(
        Workspace.attribution_channel_id == int(chat_id)
    ).first()
    if not ws:
        return  # not our attribution channel for any workspace

    invite_link_hash = None
    source_tag = None

    action_message = getattr(event, "action_message", None)
    action = getattr(action_message, "action", None) if action_message else None
    invite = getattr(action, "invite", None) if action else None
    link = getattr(invite, "link", None) if invite else None

    if link:
        invite_link_hash = _extract_hash(link)
        if invite_link_hash:
            row = (
                db.query(CampaignInviteLink)
                  .filter_by(workspace_id=ws.id, invite_link_hash=invite_link_hash)
                  .first()
            )
            if row:
                source_tag = row.source_tag

    db.add(ChannelJoinEvent(
        workspace_id=ws.id,
        telegram_user_id=int(user_id),
        channel_id=int(chat_id),
        source_tag=source_tag,
        invite_link_hash=invite_link_hash,
        joined_at=datetime.utcnow(),
    ))
    db.commit()
```

- [ ] **Step 4: Run the tests and verify they pass.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_telethon
```

Expected: `Results: 5/5 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/attribution.py backend/scripts/test_attribution_telethon.py
git commit -m "feat(attribution): handle_channel_join records join events + tests"
```

---

## Task 8: Wire `handle_channel_join` into `start_workspace_client`

**Files:**
- Modify: `backend/app/services/telethon_client.py`

- [ ] **Step 1: Register the ChatAction event handler.**

In `backend/app/services/telethon_client.py`, find the block in `start_workspace_client` that registers the signal handler (around line 314). After that block, add:

```python
    # Attribution channel join handler — Spec B.
    # Bound only when the workspace has resolved an attribution_channel_id.
    if ws and ws.attribution_channel_id:
        from app.services.attribution import handle_channel_join

        async def _on_chat_action(event):
            db_local = SessionLocal()
            try:
                await handle_channel_join(event, db_local)
            except Exception:
                logger.exception("attribution: handle_channel_join failed for ws=%s", workspace_id)
            finally:
                db_local.close()

        client.add_event_handler(_on_chat_action, events.ChatAction(chats=[int(ws.attribution_channel_id)]))
        logger.info(
            "Registered attribution join handler for ws=%s on channel=%s",
            workspace_id, ws.attribution_channel_id,
        )
```

- [ ] **Step 2: Smoke-test the module imports cleanly.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
APP_ENV=development .venv/bin/python -c "
from app.services.telethon_client import start_workspace_client
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/telethon_client.py
git commit -m "feat(attribution): wire ChatAction handler into start_workspace_client"
```

---

## Task 9: `claim_pending_attribution` + tests

**Files:**
- Modify: `backend/app/services/attribution.py`
- Create: `backend/scripts/test_attribution_claim.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_attribution_claim.py`:

```python
"""
Tests for claim_pending_attribution + ensure_contact integration.
Run from backend/:  python -m scripts.test_attribution_claim
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime, timedelta
from app.database import init_db, SessionLocal
from app.database.models import ChannelJoinEvent, Contact, Workspace

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _seed_join(*, telegram_user_id, source_tag, joined_at, claimed_contact_id=None):
    db = SessionLocal()
    try:
        ev = ChannelJoinEvent(
            workspace_id=1,
            telegram_user_id=telegram_user_id,
            channel_id=-1001,
            source_tag=source_tag,
            invite_link_hash="h" if source_tag else None,
            joined_at=joined_at,
            claimed_contact_id=claimed_contact_id,
            claimed_at=datetime.utcnow() if claimed_contact_id else None,
        )
        db.add(ev); db.commit()
    finally:
        db.close()


def _make_contact(*, user_id=42, source=None, source_tag=None):
    db = SessionLocal()
    try:
        c = Contact(
            id=user_id, workspace_id=1, source=source, source_tag=source_tag,
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        )
        db.add(c); db.commit()
    finally:
        db.close()


def test_claim_writes_source_tag_when_pending_exists():
    print("\n=== Test 1: pending join → contact.source_tag set, row marked claimed ===")
    init_db()
    _make_contact(user_id=42, source_tag=None)
    _seed_join(telegram_user_id=42, source_tag="cmp_X",
               joined_at=datetime.utcnow() - timedelta(minutes=5))
    from app.services.attribution import claim_pending_attribution
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == 42).first()
        got = claim_pending_attribution(contact, telegram_user_id=42, db=db, workspace_id=1)
        ok1 = check(f"claim returns 'cmp_X' (got {got!r})", got == "cmp_X")
        ok2 = check(f"contact.source_tag='cmp_X'", contact.source_tag == "cmp_X")
        row = db.query(ChannelJoinEvent).filter_by(telegram_user_id=42).first()
        ok3 = check(f"join row claimed_contact_id={contact.id}", row.claimed_contact_id == contact.id)
        return ok1 and ok2 and ok3
    finally:
        db.close()


def test_claim_picks_most_recent_join():
    print("\n=== Test 2: last-touch wins when multiple joins exist ===")
    init_db()
    _make_contact(user_id=43, source_tag=None)
    _seed_join(telegram_user_id=43, source_tag="cmp_OLD",
               joined_at=datetime.utcnow() - timedelta(days=2))
    _seed_join(telegram_user_id=43, source_tag="cmp_NEW",
               joined_at=datetime.utcnow() - timedelta(minutes=5))
    from app.services.attribution import claim_pending_attribution
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == 43).first()
        got = claim_pending_attribution(contact, telegram_user_id=43, db=db, workspace_id=1)
        return check(f"claim returns 'cmp_NEW' (got {got!r})", got == "cmp_NEW")
    finally:
        db.close()


def test_claim_skips_already_claimed_rows():
    print("\n=== Test 3: pre-claimed rows are not eligible ===")
    init_db()
    _make_contact(user_id=44, source_tag=None)
    _seed_join(telegram_user_id=44, source_tag="cmp_USED",
               joined_at=datetime.utcnow() - timedelta(minutes=5),
               claimed_contact_id=999)
    from app.services.attribution import claim_pending_attribution
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == 44).first()
        got = claim_pending_attribution(contact, telegram_user_id=44, db=db, workspace_id=1)
        return check(f"claim returns None (got {got!r})", got is None)
    finally:
        db.close()


def test_claim_skips_organic_joins():
    print("\n=== Test 4: NULL source_tag rows are not eligible ===")
    init_db()
    _make_contact(user_id=45, source_tag=None)
    _seed_join(telegram_user_id=45, source_tag=None,
               joined_at=datetime.utcnow() - timedelta(minutes=5))
    from app.services.attribution import claim_pending_attribution
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == 45).first()
        got = claim_pending_attribution(contact, telegram_user_id=45, db=db, workspace_id=1)
        return check(f"claim returns None (got {got!r})", got is None)
    finally:
        db.close()


def test_claim_no_pending_returns_none():
    print("\n=== Test 5: no pending join → returns None, contact unchanged ===")
    init_db()
    _make_contact(user_id=46, source_tag=None)
    from app.services.attribution import claim_pending_attribution
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == 46).first()
        got = claim_pending_attribution(contact, telegram_user_id=46, db=db, workspace_id=1)
        ok1 = check(f"returns None (got {got!r})", got is None)
        ok2 = check(f"contact.source_tag still None", contact.source_tag is None)
        return ok1 and ok2
    finally:
        db.close()


def test_ensure_contact_calls_claim_for_new_contact():
    print("\n=== Test 6: ensure_contact() claims pending for a NEW contact ===")
    init_db()
    _seed_join(telegram_user_id=50, source_tag="cmp_INT",
               joined_at=datetime.utcnow() - timedelta(minutes=2))
    from app.handlers.leads import ensure_contact
    db = SessionLocal()
    try:
        contact = ensure_contact(db, user_id=50, username="u", source=None, workspace_id=1)
        ok1 = check(f"contact.source_tag='cmp_INT' (got {contact.source_tag!r})", contact.source_tag == "cmp_INT")
        ok2 = check(f"contact.entry_path='public_channel' (got {contact.entry_path!r})", contact.entry_path == "public_channel")
        return ok1 and ok2
    finally:
        db.close()


def test_ensure_contact_start_param_wins_over_pending():
    print("\n=== Test 7: ensure_contact() prefers /start tag over pending join ===")
    init_db()
    _seed_join(telegram_user_id=51, source_tag="cmp_OLD_JOIN",
               joined_at=datetime.utcnow() - timedelta(minutes=2))
    from app.handlers.leads import ensure_contact
    db = SessionLocal()
    try:
        contact = ensure_contact(db, user_id=51, username="u",
                                 source="cmp_FRESH_DEEPLINK", workspace_id=1)
        return check(f"contact.source_tag='cmp_FRESH_DEEPLINK' (got {contact.source_tag!r})",
                     contact.source_tag == "cmp_FRESH_DEEPLINK")
    finally:
        db.close()


def main():
    results = [
        test_claim_writes_source_tag_when_pending_exists(),
        test_claim_picks_most_recent_join(),
        test_claim_skips_already_claimed_rows(),
        test_claim_skips_organic_joins(),
        test_claim_no_pending_returns_none(),
        test_ensure_contact_calls_claim_for_new_contact(),
        test_ensure_contact_start_param_wins_over_pending(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the tests and verify they fail.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_claim
```

Expected: `ImportError: cannot import name 'claim_pending_attribution'`. Tests 6+7 fail because `ensure_contact` doesn't call claim yet.

- [ ] **Step 3: Implement `claim_pending_attribution`.**

In `backend/app/services/attribution.py`, replace the `# claim_pending_attribution — Task 9` comment with:

```python
def claim_pending_attribution(
    contact: Contact, *, telegram_user_id: int, db: Session, workspace_id: int,
) -> Optional[str]:
    """
    Look up the most recent unclaimed, attributed ChannelJoinEvent for this
    user in this workspace and copy its source_tag onto the contact.

    Returns the claimed source_tag (string) on success, or None if there's
    nothing to claim.

    Caller (ensure_contact) is responsible for committing.
    """
    pending = (
        db.query(ChannelJoinEvent)
          .filter(
              ChannelJoinEvent.workspace_id == workspace_id,
              ChannelJoinEvent.telegram_user_id == telegram_user_id,
              ChannelJoinEvent.source_tag.isnot(None),
              ChannelJoinEvent.claimed_contact_id.is_(None),
          )
          .order_by(ChannelJoinEvent.joined_at.desc())
          .first()
    )
    if not pending:
        return None

    contact.source_tag = pending.source_tag
    contact.source = pending.source_tag       # legacy mirror
    contact.entry_path = "public_channel"
    pending.claimed_contact_id = contact.id
    pending.claimed_at = datetime.utcnow()
    return pending.source_tag
```

- [ ] **Step 4: Wire it into `ensure_contact`.**

In `backend/app/handlers/leads.py`, locate `ensure_contact`. Find the section that handles a NEW contact (after `db.refresh(contact)` near line 121, just before the `# Schedule follow-ups` block):

```python
    db.add(contact)
    db.commit()
    db.refresh(contact)
```

Immediately after `db.refresh(contact)` (still in the new-contact path), add:

```python
    # Spec B: claim a pending channel-join attribution if /start carried no tag.
    if source is None and contact.source_tag is None:
        from app.services.attribution import claim_pending_attribution
        claimed = claim_pending_attribution(
            contact, telegram_user_id=user_id, db=db, workspace_id=workspace_id,
        )
        if claimed:
            db.commit()
            db.refresh(contact)
```

Then locate the EXISTING-contact path (the `if contact:` branch). Find the line that ends with `db.commit()` and `db.refresh(contact)` — there's one near line 96. Just BEFORE the `db.commit()`, add:

```python
        # Spec B: claim pending attribution for an existing contact who has no tag yet.
        if source is None and contact.source_tag is None:
            from app.services.attribution import claim_pending_attribution
            claim_pending_attribution(
                contact, telegram_user_id=user_id, db=db, workspace_id=workspace_id,
            )
```

- [ ] **Step 5: Run the tests and verify they pass.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_claim
```

Expected: `Results: 7/7 test groups passed`.

- [ ] **Step 6: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/attribution.py backend/app/handlers/leads.py backend/scripts/test_attribution_claim.py
git commit -m "feat(attribution): claim_pending_attribution + ensure_contact integration + tests"
```

---

## Task 10: `cleanup_old_join_events` + tests

**Files:**
- Modify: `backend/app/services/attribution.py`
- Create: `backend/scripts/test_attribution_cleanup.py`

- [ ] **Step 1: Write the failing tests.**

Create `backend/scripts/test_attribution_cleanup.py`:

```python
"""
Tests for cleanup_old_join_events (90-day TTL).
Run from backend/:  python -m scripts.test_attribution_cleanup
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime, timedelta
from app.database import init_db, SessionLocal
from app.database.models import ChannelJoinEvent

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _seed(*, joined_days_ago: int, claimed: bool, telegram_user_id: int):
    db = SessionLocal()
    try:
        ev = ChannelJoinEvent(
            workspace_id=1,
            telegram_user_id=telegram_user_id,
            channel_id=-1001,
            source_tag="cmp_x" if not claimed else "cmp_y",
            joined_at=datetime.utcnow() - timedelta(days=joined_days_ago),
            claimed_contact_id=999 if claimed else None,
            claimed_at=datetime.utcnow() if claimed else None,
        )
        db.add(ev); db.commit()
    finally:
        db.close()


def test_deletes_unclaimed_older_than_ttl():
    print("\n=== Test 1: unclaimed row >90 days old → deleted ===")
    init_db()
    db = SessionLocal()
    try:
        db.query(ChannelJoinEvent).delete(); db.commit()
    finally:
        db.close()
    _seed(joined_days_ago=120, claimed=False, telegram_user_id=1)
    from app.services.attribution import cleanup_old_join_events
    db = SessionLocal()
    try:
        n = cleanup_old_join_events(db, ttl_days=90)
        ok1 = check(f"deleted 1 row (got {n})", n == 1)
        remaining = db.query(ChannelJoinEvent).count()
        ok2 = check(f"0 rows remaining (got {remaining})", remaining == 0)
        return ok1 and ok2
    finally:
        db.close()


def test_keeps_unclaimed_within_ttl():
    print("\n=== Test 2: unclaimed row <90 days old → kept ===")
    init_db()
    db = SessionLocal()
    try:
        db.query(ChannelJoinEvent).delete(); db.commit()
    finally:
        db.close()
    _seed(joined_days_ago=30, claimed=False, telegram_user_id=2)
    from app.services.attribution import cleanup_old_join_events
    db = SessionLocal()
    try:
        n = cleanup_old_join_events(db, ttl_days=90)
        ok1 = check(f"deleted 0 rows (got {n})", n == 0)
        remaining = db.query(ChannelJoinEvent).count()
        ok2 = check(f"1 row remaining (got {remaining})", remaining == 1)
        return ok1 and ok2
    finally:
        db.close()


def test_keeps_claimed_regardless_of_age():
    print("\n=== Test 3: claimed row even when >90 days old → kept ===")
    init_db()
    db = SessionLocal()
    try:
        db.query(ChannelJoinEvent).delete(); db.commit()
    finally:
        db.close()
    _seed(joined_days_ago=365, claimed=True, telegram_user_id=3)
    from app.services.attribution import cleanup_old_join_events
    db = SessionLocal()
    try:
        n = cleanup_old_join_events(db, ttl_days=90)
        ok1 = check(f"deleted 0 rows (got {n})", n == 0)
        remaining = db.query(ChannelJoinEvent).count()
        ok2 = check(f"1 row remaining (got {remaining})", remaining == 1)
        return ok1 and ok2
    finally:
        db.close()


def main():
    results = [
        test_deletes_unclaimed_older_than_ttl(),
        test_keeps_unclaimed_within_ttl(),
        test_keeps_claimed_regardless_of_age(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the tests and verify they fail.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_cleanup
```

Expected: `ImportError: cannot import name 'cleanup_old_join_events'`.

- [ ] **Step 3: Implement `cleanup_old_join_events`.**

In `backend/app/services/attribution.py`, replace the `# cleanup_old_join_events — Task 11` comment with:

```python
def cleanup_old_join_events(db: Session, *, ttl_days: int = 90) -> int:
    """
    Delete unclaimed ChannelJoinEvent rows older than ttl_days.
    Claimed rows are kept indefinitely (they're part of contact attribution audit).
    Returns the number of rows deleted.
    """
    cutoff = datetime.utcnow() - timedelta(days=ttl_days)
    deleted = (
        db.query(ChannelJoinEvent)
          .filter(
              ChannelJoinEvent.joined_at < cutoff,
              ChannelJoinEvent.claimed_contact_id.is_(None),
          )
          .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)
```

- [ ] **Step 4: Run the tests and verify they pass.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
.venv/bin/python -m scripts.test_attribution_cleanup
```

Expected: `Results: 3/3 test groups passed`.

- [ ] **Step 5: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/attribution.py backend/scripts/test_attribution_cleanup.py
git commit -m "feat(attribution): cleanup_old_join_events 90-day TTL helper + tests"
```

---

## Task 11: Wire cleanup into the daily scheduler

**Files:**
- Modify: `backend/app/services/scheduler.py`

- [ ] **Step 1: Add the cleanup job to `start_scheduler`.**

In `backend/app/services/scheduler.py`, find `start_scheduler()`. After the existing `_scheduler.add_job` calls (and before `_scheduler.start()`), add:

```python
    # Spec B — daily attribution-event TTL cleanup at 03:30 UTC.
    def _attribution_cleanup_tick():
        from app.database import SessionLocal
        from app.services.attribution import cleanup_old_join_events
        db = SessionLocal()
        try:
            n = cleanup_old_join_events(db, ttl_days=90)
            if n:
                logger.info("attribution: cleanup deleted %d old unclaimed join events", n)
        except Exception:
            logger.exception("attribution: cleanup failed")
        finally:
            db.close()

    _scheduler.add_job(
        _attribution_cleanup_tick,
        "cron",
        hour=3, minute=30,
        id="attribution_cleanup",
        replace_existing=True,
    )
```

- [ ] **Step 2: Smoke-test the module imports cleanly.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
APP_ENV=development .venv/bin/python -c "
from app.services.scheduler import start_scheduler
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/services/scheduler.py
git commit -m "feat(attribution): daily 03:30 UTC TTL-cleanup job"
```

---

## Task 12: Extend `/campaigns` response shape with `invite_link` + `channel_join_count`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Locate the `/campaigns` GET handler and add new fields.**

In `backend/app/main.py`, find the `list_campaigns` function (around line 1704). Replace the body of the per-campaign loop so it also computes `invite_link` and `channel_join_count`. The full function body becomes:

```python
@app.get("/campaigns")
def list_campaigns(
    db: Session = Depends(get_db),
    workspace_id: int = Depends(get_workspace_id),
    _=Depends(require_roles("developer", "admin")),
):
    """List all tracked campaigns with their attribution stats."""
    from app.database.models import (
        Campaign, CampaignInviteLink, ChannelJoinEvent, Contact, Workspace,
    )
    from app.config import BOT_USERNAME

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    landing_base = (ws.landing_page_url or "").strip().rstrip("/") if ws else ""

    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    result = []
    for c in campaigns:
        leads = db.query(Contact).filter(Contact.source == c.source_tag).count()
        deposits = (
            db.query(Contact)
            .filter(
                Contact.source == c.source_tag,
                Contact.workspace_id == workspace_id,
                Contact.deposit_status == "deposited",
            )
            .count()
        )
        invite_row = (
            db.query(CampaignInviteLink)
              .filter_by(workspace_id=workspace_id, campaign_id=c.id)
              .filter(CampaignInviteLink.revoked_at.is_(None))
              .first()
        )
        join_count = (
            db.query(ChannelJoinEvent)
              .filter(
                  ChannelJoinEvent.workspace_id == workspace_id,
                  ChannelJoinEvent.source_tag == c.source_tag,
              )
              .count()
        )
        link = f"https://t.me/{BOT_USERNAME}?start={c.source_tag}" if BOT_USERNAME else None
        landing_url = f"{landing_base}?src={c.source_tag}" if landing_base else None
        result.append({
            "id": c.id,
            "source_tag": c.source_tag,
            "name": c.name,
            "meta_campaign_id": c.meta_campaign_id,
            "link": link,
            "landing_url": landing_url,
            "invite_link": invite_row.invite_link if invite_row else None,
            "channel_join_count": join_count,
            "leads": leads,
            "deposits": deposits,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat(),
        })
    return result
```

Apply the same `invite_link` field (None at creation time) to the `POST /campaigns` response (`create_campaign`):

```python
    return {
        "id": campaign.id,
        "source_tag": source_tag,
        "name": campaign.name,
        "meta_campaign_id": campaign.meta_campaign_id,
        "link": link,
        "landing_url": landing_url,
        "invite_link": None,           # minted on first /attribution/invite call
        "channel_join_count": 0,       # NEW
        "leads": 0,
        "deposits": 0,
        "created_at": campaign.created_at.isoformat(),
    }
```

- [ ] **Step 2: Smoke-test the endpoint structure.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend
APP_ENV=development DATABASE_URL=sqlite:///:memory: .venv/bin/python -c "
from app.main import app
from fastapi.testclient import TestClient
# Endpoint requires auth — just check it imports + route is registered.
routes = {r.path for r in app.routes}
assert '/campaigns' in routes
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add backend/app/main.py
git commit -m "feat(api): /campaigns response includes invite_link + channel_join_count"
```

---

## Task 13: Frontend — `CampaignLinkModal` component

**Files:**
- Create: `frontend/src/components/CampaignLinkModal.tsx`

- [ ] **Step 1: Identify the existing campaigns API types.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
grep -rn "TrackedCampaign\|trackedCampaigns\|interface Campaign" frontend/src/ | head
```

Note the file path of the type — likely `frontend/src/api/campaigns.ts`. The plan uses `TrackedCampaign` as the type name; verify and adjust the import below if it differs.

- [ ] **Step 2: Create the modal component.**

Create `frontend/src/components/CampaignLinkModal.tsx`:

```tsx
import { useEffect, useState } from "react";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

export interface CampaignLinkModalProps {
  campaign: {
    id: number;
    source_tag: string;
    name: string;
    link: string | null;            // bot deep link
    invite_link: string | null;     // channel invite — fetched if null
  };
  workspaceId: number;
  onClose: () => void;
}

export function CampaignLinkModal({ campaign, workspaceId, onClose }: CampaignLinkModalProps) {
  const [inviteLink, setInviteLink] = useState<string | null>(campaign.invite_link);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [selector, setSelector] = useState<string>("#join-button");

  useEffect(() => {
    if (campaign.invite_link) return;
    const token = localStorage.getItem("auth_token") || "";
    fetch(
      `${API_BASE}/attribution/invite?workspace_id=${workspaceId}&src=${encodeURIComponent(campaign.source_tag)}`,
      { headers: { Origin: window.location.origin, Authorization: `Bearer ${token}` } },
    )
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          setInviteError(body.error || `HTTP ${r.status}`);
          return null;
        }
        return r.json();
      })
      .then(body => { if (body && body.invite_link) setInviteLink(body.invite_link); })
      .catch(e => setInviteError(String(e)));
  }, [campaign, workspaceId]);

  const snippet = `<script>
(async () => {
  const p = new URLSearchParams(window.location.search);
  const src = p.get('utm_campaign') || p.get('src') || 'organic';
  try {
    const r = await fetch(
      'https://telelytics.org/attribution/invite?workspace_id=${workspaceId}&src=' + encodeURIComponent(src),
      { mode: 'cors' }
    );
    if (r.ok) {
      const { invite_link } = await r.json();
      const el = document.querySelector(${JSON.stringify(selector)});
      if (el) el.href = invite_link;
    }
  } catch (e) { /* leave default href */ }
})();
</script>`;

  function copy(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 space-y-5">
        <div className="flex justify-between items-center">
          <h2 className="text-lg font-semibold">Tracked link created: {campaign.name}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800">✕</button>
        </div>

        <section>
          <h3 className="text-sm font-medium mb-1">1. Bot deep link (organic / direct)</h3>
          <div className="flex items-center gap-2">
            <code className="text-xs bg-gray-100 px-2 py-1 rounded flex-1 overflow-x-auto">
              {campaign.link || "(no BOT_USERNAME set)"}
            </code>
            {campaign.link && (
              <button onClick={() => copy(campaign.link!)} className="text-sm">📋 Copy</button>
            )}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium mb-1">2. Channel invite link (paid traffic)</h3>
          <div className="flex items-center gap-2">
            <code className="text-xs bg-gray-100 px-2 py-1 rounded flex-1 overflow-x-auto">
              {inviteLink ?? (inviteError ? `Error: ${inviteError}` : "Minting…")}
            </code>
            {inviteLink && (
              <button onClick={() => copy(inviteLink)} className="text-sm">📋 Copy</button>
            )}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium mb-1">3. Landing-page snippet</h3>
          <p className="text-xs text-gray-600 mb-2">
            Paste this onto your landing page once. It rewrites the Join button to the
            campaign-specific invite link based on the URL's <code>?utm_campaign</code>.
          </p>
          <div className="mb-2 flex items-center gap-2 text-xs">
            <label className="font-medium">Selector:</label>
            <input
              type="text"
              value={selector}
              onChange={e => setSelector(e.target.value)}
              className="border rounded px-2 py-1 w-48 font-mono"
            />
          </div>
          <div className="relative">
            <pre className="text-xs bg-gray-100 p-3 rounded overflow-x-auto whitespace-pre-wrap">
              {snippet}
            </pre>
            <button
              onClick={() => copy(snippet)}
              className="absolute top-2 right-2 text-xs"
            >📋 Copy</button>
          </div>
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Type-check.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/frontend
npx tsc --noEmit
```

Expected: exits 0.

- [ ] **Step 4: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add frontend/src/components/CampaignLinkModal.tsx
git commit -m "feat(frontend): CampaignLinkModal — three-link result + JS snippet"
```

---

## Task 14: Frontend — wire modal into `AnalyticsDashboard` + show new columns

**Files:**
- Modify: `frontend/src/pages/AnalyticsDashboard.tsx`

- [ ] **Step 1: Update the `TrackedCampaign` interface.**

Find the `TrackedCampaign` (or equivalent) type in `frontend/src/api/campaigns.ts` (or wherever it lives — confirmed in Task 13, Step 1). Add two fields:

```ts
export interface TrackedCampaign {
  // ...existing fields...
  invite_link: string | null;         // NEW
  channel_join_count: number;         // NEW
}
```

- [ ] **Step 2: Render the modal after creating a campaign.**

In `frontend/src/pages/AnalyticsDashboard.tsx`:

1. Import the modal at the top of the file:
   ```tsx
   import { CampaignLinkModal } from "../components/CampaignLinkModal";
   ```

2. Add state for the modal near the existing `useState` declarations in the component:
   ```tsx
   const [linkModalCampaign, setLinkModalCampaign] = useState<TrackedCampaign | null>(null);
   ```

3. Find where the existing "Generate Tracked Link" button calls the create endpoint. After a successful create response, set the modal:
   ```tsx
   setLinkModalCampaign(createdCampaign);
   ```
   (The exact handler name will be visible in the file — adjust to match.)

4. At the end of the JSX returned by the page (just before the closing tag of the outermost wrapper), render:
   ```tsx
   {linkModalCampaign && (
     <CampaignLinkModal
       campaign={linkModalCampaign}
       workspaceId={Number(localStorage.getItem("workspace_id") || 1)}
       onClose={() => setLinkModalCampaign(null)}
     />
   )}
   ```

- [ ] **Step 3: Add a "Show snippet" link on each existing campaign row.**

In the existing campaigns table render (the `trackedCampaigns.map((c) => …)` block around line 697), add a small button next to each row:

```tsx
<button
  onClick={() => setLinkModalCampaign(c)}
  className="text-xs text-blue-600 hover:underline ml-2"
>
  Show links
</button>
```

- [ ] **Step 4: Add the "channel joins" column to the table.**

In the same table, add a new `<th>Channel joins</th>` and matching `<td>{c.channel_join_count}</td>` (or render `c.channel_join_count.toLocaleString()`).

- [ ] **Step 5: Type-check + build.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/frontend
npx tsc --noEmit && npm run build
```

Expected: tsc exits 0, build succeeds.

- [ ] **Step 6: Commit.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes
git add frontend/src/pages/AnalyticsDashboard.tsx frontend/src/api/campaigns.ts
git commit -m "feat(frontend): wire CampaignLinkModal + channel_join_count column"
```

---

## Task 15: Final integration smoke-test

**Files:** none modified.

- [ ] **Step 1: Run every backend test script.**

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
  test_attribution_models \
  test_attribution_helpers \
  test_attribution_endpoint \
  test_attribution_telethon \
  test_attribution_claim \
  test_attribution_cleanup \
; do
  echo "=== $t ==="
  .venv/bin/python -m scripts.$t 2>&1 | tail -1
done
```

Expected: every script ends with `Results: N/N test groups passed`.

- [ ] **Step 2: Cold-boot test on a fresh on-disk SQLite.**

```bash
rm -f /tmp/spec_b_smoke.db
DATABASE_URL=sqlite:////tmp/spec_b_smoke.db APP_ENV=development \
  /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/backend/.venv/bin/python -c "
from app.database import init_db, engine
from sqlalchemy import inspect
init_db()
insp = inspect(engine)
assert 'campaign_invite_links' in insp.get_table_names()
assert 'channel_join_events' in insp.get_table_names()
ws_cols = {c['name'] for c in insp.get_columns('workspaces')}
assert 'attribution_channel_id' in ws_cols
print('cold-boot ok')
"
rm -f /tmp/spec_b_smoke.db
```

Expected: `cold-boot ok`.

- [ ] **Step 3: Frontend type-check + build.**

```bash
cd /Users/sameerkaram/Documents/Education/Coding_Projects/Telegram_bot/.worktrees/lead-classification-fixes/frontend
npx tsc --noEmit && npm run build
```

Expected: tsc exits 0, build succeeds.

- [ ] **Step 4: No commit needed.** Smoke-test only. If anything failed, fix on the failing task — do not paper over with a "test fix" commit.

---

## Self-review notes

| Spec section | Tasks |
|---|---|
| Goal / non-goals | 1–14 (every section maps to at least one task) |
| Architecture (six numbered touch-points + module map) | 1, 2, 3, 6, 8, 10 |
| Auth model (origin allowlist + rate limit + existing-campaign gate) | 6 |
| Channel identity & resolution | 1, 4 |
| Multi-touch attribution policy (last-touch) | 9 |
| Storage (campaign_invite_links + channel_join_events + indexes + TTL) | 2, 10, 11 |
| Endpoint shape (`GET /attribution/invite`) | 6 |
| Telethon join listener (pure handler + binding) | 7, 8 |
| Attribution claim (ensure_contact extension) | 9 |
| Frontend campaign-creation modal (3 links + snippet + selector) | 13, 14 |
| Extended `/campaigns` response (`invite_link` + `channel_join_count`) | 12 |
| Test infrastructure | 2, 3, 6, 7, 9, 10 |
| Test coverage targets (~25 tests) | 2 (5), 3+4+5 (12), 6 (7), 7 (5), 9 (7), 10 (3) = 39 — exceeds spec target |
| Final integration smoke-test | 15 |

No spec section is unaddressed.

## Out-of-scope reminders (for the engineer)

- Do **not** add a `revoke invite link` UI. Revocation by date/admin action is rare and can be added later if Walid asks.
- Do **not** retroactively backfill `entry_path` for pre-Spec-B contacts. Only NEW joins get attribution.
- Do **not** install the JS snippet on `bullishfxwalid.com` from the codebase. We surface the snippet for Walid to paste manually.
- Do **not** broaden `/attribution/invite` to authenticated callers. Public + CORS allowlist is the design.
- Do **not** turn the cleanup job into a "soft delete" or audit trail. The spec is hard-delete after 90 days for unclaimed rows; claimed rows are kept indefinitely.
