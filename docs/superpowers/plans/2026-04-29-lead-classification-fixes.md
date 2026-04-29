# Lead Classification Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three small, independent fixes — VIP-name re-detection on rename, a "Sync Telegram history" UI button, and a two-column source-attribution schema (`entry_path` + `source_tag`) with a one-time legacy migration. Together these unblock Walid's existing book of leads and lay the foundation for Spec B (per-campaign invite-link attribution).

**Architecture:** Schema-first — add the two new `Contact` columns, two `Workspace` columns, and an `app_meta` table; run an idempotent migration that tags existing rows `entry_path='legacy_pre_attribution'` and recovers any historical `/start` payloads. Then add a pure `name_matches_vip_marker` regex helper plus a side-effecting `maybe_promote_to_member_stage` helper, and call them from `_initial_stage_for_contact` (initial create), `ensure_contact` (rename hook), and `backfill.py` (per-dialog). Frontend gets a single new card in Settings → Telegram that calls the existing backfill endpoint and displays the persisted last-run summary.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + script-style tests (`backend/scripts/test_*.py` invoked via `python -m scripts.test_X`). Frontend: React + TypeScript + Tailwind. SQLite locally, PostgreSQL in prod — `_ensure_columns()` carries DDL for both dialects.

---

## File map

**Modify:**
- `backend/app/database/models.py` — add four columns + new `AppMeta` model
- `backend/app/database/__init__.py` — extend `_ensure_columns`, add `_get_app_meta` / `_set_app_meta`, add `_run_legacy_attribution_migration_v1`, wire it into `init_db`
- `backend/app/services/pipeline.py` — add `_compile_markers`, `name_matches_vip_marker`, `maybe_promote_to_member_stage`
- `backend/app/handlers/leads.py` — refactor `_initial_stage_for_contact`, hook rename detection in `ensure_contact` update branch, mirror `source` writes to `source_tag`
- `backend/app/services/telethon_client.py` — mirror `source` writes to `source_tag`
- `backend/app/services/backfill.py` — call `maybe_promote_to_member_stage` per dialog, persist last-run summary
- `backend/app/main.py` — extend `GET /settings/telethon/status` with backfill summary fields
- `frontend/src/pages/SettingsPage.tsx` — add "Sync Telegram history" card to the Telegram tab

**Create:**
- `backend/scripts/test_app_meta.py` — tests for the meta KV helpers
- `backend/scripts/test_legacy_attribution.py` — tests for the migration
- `backend/scripts/test_vip_name_promotion.py` — tests for the helpers
- `backend/scripts/test_ensure_contact_rename.py` — tests for the rename hook
- `backend/scripts/test_backfill_persists_summary.py` — tests for the workspace persistence

---

## Task 1: Add models for the new columns and `AppMeta` table

**Files:**
- Modify: `backend/app/database/models.py:38-87` (Contact), `backend/app/database/models.py:181-260` (Workspace area). Append a new `AppMeta` model anywhere after `Workspace`.

- [ ] **Step 1: Add `entry_path` and `source_tag` columns to the `Contact` model.**

In `backend/app/database/models.py`, locate the `Contact` class (`class Contact(Base):` near line 38). Find the existing `source` column (around line 52) and add the two new columns immediately after it:

```python
    source = Column(String(255), nullable=True)  # campaign tag from /start param  (legacy — being deprecated; mirror of source_tag)
    source_tag = Column(String(255), nullable=True)  # campaign tag (replaces source)
    entry_path = Column(String(64), nullable=True)   # controlled vocab — 'legacy_pre_attribution', 'landing_page', 'public_channel', 'affiliate', 'direct', 'unknown'
```

- [ ] **Step 2: Add `last_backfill_at` and `last_backfill_summary` columns to the `Workspace` model.**

Locate the `Workspace` class. Find the `vip_marker_phrases = Column(Text, nullable=True)` line (around 234-235) and add after it (still inside the class):

```python
    last_backfill_at = Column(DateTime, nullable=True)
    last_backfill_summary = Column(Text, nullable=True)  # JSON: {contacts_created, messages_replayed, skipped}
```

- [ ] **Step 3: Add the `AppMeta` model at the bottom of the file (after the last existing class).**

```python
class AppMeta(Base):
    """Single-row-per-key store for one-time migration flags and similar bookkeeping."""

    __tablename__ = "app_meta"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 4: Smoke-check models import cleanly.**

Run from `backend/`:

```bash
source .venv/bin/activate
python -c "from app.database.models import Contact, Workspace, AppMeta; print('ok')"
```

Expected output: `ok`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/database/models.py
git commit -m "feat(models): add Contact.entry_path/source_tag, Workspace.last_backfill_*, AppMeta"
```

---

## Task 2: Extend `_ensure_columns()` for the four new columns

**Files:**
- Modify: `backend/app/database/__init__.py:121-200` (the `_ensure_columns` body)

- [ ] **Step 1: Add `entry_path` and `source_tag` to both `contacts_needed` lists.**

In `_ensure_columns()`, the function builds two `contacts_needed` lists — one for SQLite (around line 126), one for Postgres (around line 150). At the bottom of each list (after the `puprime_client_id` entry), append:

For SQLite (`if dialect == "sqlite":` branch):

```python
            ("source_tag", "TEXT"),
            ("entry_path", "TEXT"),
```

For Postgres (`else:` branch):

```python
            ("source_tag", "VARCHAR(255)"),
            ("entry_path", "VARCHAR(64)"),
```

- [ ] **Step 2: Add `last_backfill_at` and `last_backfill_summary` to `ws_needed`.**

Locate the `ws_needed` list inside the `if _table_exists("workspaces"):` block (around line 208). At the bottom (after `deposit_webhook_secret`), append:

```python
            ("last_backfill_at", "TIMESTAMP"),
            ("last_backfill_summary", "TEXT"),
```

(These DDLs are valid for both SQLite and Postgres — `TIMESTAMP` and `TEXT` are dialect-portable.)

- [ ] **Step 3: Verify `Base.metadata.create_all()` will create the `app_meta` table on a fresh DB.**

`init_db()` already calls `Base.metadata.create_all(bind=engine)` at line 452. Since Task 1 added `AppMeta` to the same `Base`, no extra code is needed for greenfield DBs.

For existing deployments where `app_meta` may not exist yet, `create_all` is idempotent and adds it automatically — no `_ensure_columns` work needed for the table itself, only for adding columns to existing tables.

- [ ] **Step 4: Smoke-test the migration on a fresh in-memory SQLite.**

Run from `backend/`:

```bash
source .venv/bin/activate
DATABASE_URL=sqlite:///:memory: python -c "
from app.database import init_db, engine
from sqlalchemy import inspect
init_db()
insp = inspect(engine)
cols_contacts = {c['name'] for c in insp.get_columns('contacts')}
cols_ws = {c['name'] for c in insp.get_columns('workspaces')}
assert 'entry_path' in cols_contacts, 'missing entry_path'
assert 'source_tag' in cols_contacts, 'missing source_tag'
assert 'last_backfill_at' in cols_ws, 'missing last_backfill_at'
assert 'last_backfill_summary' in cols_ws, 'missing last_backfill_summary'
assert insp.has_table('app_meta'), 'missing app_meta table'
print('ok')
"
```

Expected output: `ok`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/database/__init__.py
git commit -m "feat(db): _ensure_columns adds entry_path/source_tag/last_backfill_*"
```

---

## Task 3: Add `_get_app_meta` / `_set_app_meta` helpers

**Files:**
- Modify: `backend/app/database/__init__.py` — add helpers in the "Schema helpers" block (around line 70-97)
- Test: `backend/scripts/test_app_meta.py` (new)

- [ ] **Step 1: Write the failing test.**

Create `backend/scripts/test_app_meta.py`:

```python
"""
Tests for app_meta KV helpers.
Run from backend/:  python -m scripts.test_app_meta
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.database import init_db, engine, _get_app_meta, _set_app_meta

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_get_missing_returns_none():
    print("\n=== Test 1: missing key returns None ===")
    init_db()
    with engine.connect() as conn:
        v = _get_app_meta(conn, "no_such_key")
    return check(f"_get_app_meta('no_such_key') is None (got {v!r})", v is None)


def test_set_then_get_roundtrip():
    print("\n=== Test 2: set then get returns the value ===")
    with engine.connect() as conn:
        _set_app_meta(conn, "k1", "hello")
        v = _get_app_meta(conn, "k1")
    return check(f"roundtrip 'hello' (got {v!r})", v == "hello")


def test_set_overwrites_existing():
    print("\n=== Test 3: set overwrites existing value ===")
    with engine.connect() as conn:
        _set_app_meta(conn, "k1", "first")
        _set_app_meta(conn, "k1", "second")
        v = _get_app_meta(conn, "k1")
    return check(f"value 'second' after overwrite (got {v!r})", v == "second")


def main():
    results = [
        test_get_missing_returns_none(),
        test_set_then_get_roundtrip(),
        test_set_overwrites_existing(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd backend
python -m scripts.test_app_meta
```

Expected: ImportError or AttributeError on `_get_app_meta` / `_set_app_meta` not being importable from `app.database`.

- [ ] **Step 3: Implement the helpers.**

In `backend/app/database/__init__.py`, just below `_add_column` (around line 97), add:

```python
def _get_app_meta(conn, key: str) -> str | None:
    """Read a single value from the app_meta KV table. Returns None if missing."""
    row = conn.execute(
        text("SELECT value FROM app_meta WHERE key = :k"),
        {"k": key},
    ).fetchone()
    return row[0] if row else None


def _set_app_meta(conn, key: str, value: str) -> None:
    """Insert or update a key in app_meta. Dialect-aware upsert."""
    dialect = engine.dialect.name
    if dialect == "sqlite":
        conn.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) "
                "VALUES (:k, :v, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP"
            ),
            {"k": key, "v": value},
        )
    else:
        conn.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) "
                "VALUES (:k, :v, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=CURRENT_TIMESTAMP"
            ),
            {"k": key, "v": value},
        )
    conn.commit()
```

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd backend
python -m scripts.test_app_meta
```

Expected: `Results: 3/3 test groups passed`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/database/__init__.py backend/scripts/test_app_meta.py
git commit -m "feat(db): _get_app_meta/_set_app_meta KV helpers + tests"
```

---

## Task 4: Implement the legacy attribution migration

**Files:**
- Modify: `backend/app/database/__init__.py` — add `_run_legacy_attribution_migration_v1` after the `_set_app_meta` helper from Task 3
- Test: `backend/scripts/test_legacy_attribution.py` (new)

- [ ] **Step 1: Write the failing test.**

Create `backend/scripts/test_legacy_attribution.py`:

```python
"""
Tests for the one-time legacy attribution migration.
Run from backend/:  python -m scripts.test_legacy_attribution
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import datetime
from app.database import (
    init_db, engine, SessionLocal, _get_app_meta,
    _run_legacy_attribution_migration_v1,
)
from app.database.models import Contact, Message, Organization, Workspace

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _reset_and_seed():
    """Wipe contacts/messages and seed fresh fixtures. Workspace 1 already exists."""
    db = SessionLocal()
    db.query(Message).delete()
    db.query(Contact).delete()
    db.commit()
    now = datetime.utcnow()
    # 1: existing source string, no /start history
    db.add(Contact(
        id=1, workspace_id=1, first_seen=now, last_seen=now,
        source="meta_old_campaign", classification="new_lead", deposit_status="none",
    ))
    # 2: NULL source, has /start payload in inbound history
    db.add(Contact(
        id=2, workspace_id=1, first_seen=now, last_seen=now,
        source=None, classification="new_lead", deposit_status="none",
    ))
    db.add(Message(
        user_id=2, message_text="/start lp_meta_recovered",
        content="/start lp_meta_recovered",
        direction="inbound", sender="system", timestamp=now,
    ))
    # 3: NULL source, no payload — pure legacy
    db.add(Contact(
        id=3, workspace_id=1, first_seen=now, last_seen=now,
        source=None, classification="new_lead", deposit_status="none",
    ))
    # 4: NULL source, multiple /start payloads (newest should win — order DESC by timestamp)
    db.add(Contact(
        id=4, workspace_id=1, first_seen=now, last_seen=now,
        source=None, classification="new_lead", deposit_status="none",
    ))
    db.add(Message(
        user_id=4, message_text="/start old_one", content="/start old_one",
        direction="inbound", sender="system",
        timestamp=datetime(2025, 1, 1),
    ))
    db.add(Message(
        user_id=4, message_text="/start newest_one", content="/start newest_one",
        direction="inbound", sender="system",
        timestamp=datetime(2025, 6, 1),
    ))
    # 5: NULL source, has bare `/start` (no payload) — should be ignored
    db.add(Contact(
        id=5, workspace_id=1, first_seen=now, last_seen=now,
        source=None, classification="new_lead", deposit_status="none",
    ))
    db.add(Message(
        user_id=5, message_text="/start", content="/start",
        direction="inbound", sender="system", timestamp=now,
    ))
    db.commit()
    db.close()


def _clear_flag():
    """Reset the migration flag so we can re-run."""
    from sqlalchemy import text as _text
    with engine.connect() as conn:
        conn.execute(_text("DELETE FROM app_meta WHERE key = 'legacy_attribution_v1'"))
        conn.commit()


def test_migration_tags_legacy_rows():
    print("\n=== Test 1: every contact gets entry_path='legacy_pre_attribution' ===")
    init_db()
    _reset_and_seed()
    _clear_flag()
    with engine.connect() as conn:
        _run_legacy_attribution_migration_v1(conn)
    db = SessionLocal()
    rows = db.query(Contact).order_by(Contact.id).all()
    all_ok = True
    for r in rows:
        all_ok &= check(
            f"contact {r.id} entry_path='legacy_pre_attribution' (got {r.entry_path!r})",
            r.entry_path == "legacy_pre_attribution",
        )
    db.close()
    return all_ok


def test_migration_carries_forward_existing_source():
    print("\n=== Test 2: source='meta_old_campaign' carried into source_tag ===")
    db = SessionLocal()
    c = db.query(Contact).filter(Contact.id == 1).first()
    ok = check(f"source_tag='meta_old_campaign' (got {c.source_tag!r})", c.source_tag == "meta_old_campaign")
    db.close()
    return ok


def test_migration_recovers_start_payload():
    print("\n=== Test 3: /start lp_meta_recovered → source_tag='lp_meta_recovered' ===")
    db = SessionLocal()
    c = db.query(Contact).filter(Contact.id == 2).first()
    ok = check(f"source_tag='lp_meta_recovered' (got {c.source_tag!r})", c.source_tag == "lp_meta_recovered")
    db.close()
    return ok


def test_migration_leaves_no_payload_null():
    print("\n=== Test 4: pure legacy → source_tag stays NULL ===")
    db = SessionLocal()
    c = db.query(Contact).filter(Contact.id == 3).first()
    ok = check(f"source_tag IS NULL (got {c.source_tag!r})", c.source_tag is None)
    db.close()
    return ok


def test_migration_picks_newest_start_payload():
    print("\n=== Test 5: most recent /start payload wins ===")
    db = SessionLocal()
    c = db.query(Contact).filter(Contact.id == 4).first()
    ok = check(f"source_tag='newest_one' (got {c.source_tag!r})", c.source_tag == "newest_one")
    db.close()
    return ok


def test_migration_ignores_bare_start():
    print("\n=== Test 6: bare /start (no payload) is ignored ===")
    db = SessionLocal()
    c = db.query(Contact).filter(Contact.id == 5).first()
    ok = check(f"source_tag IS NULL (got {c.source_tag!r})", c.source_tag is None)
    db.close()
    return ok


def test_migration_is_idempotent():
    print("\n=== Test 7: second run is a no-op ===")
    # Mutate a row, then re-run; should not be reverted because the flag short-circuits
    db = SessionLocal()
    c = db.query(Contact).filter(Contact.id == 3).first()
    c.source_tag = "manual_override"
    c.entry_path = "direct"
    db.commit()
    db.close()

    with engine.connect() as conn:
        _run_legacy_attribution_migration_v1(conn)

    db = SessionLocal()
    c = db.query(Contact).filter(Contact.id == 3).first()
    ok1 = check(f"source_tag stays 'manual_override' (got {c.source_tag!r})", c.source_tag == "manual_override")
    ok2 = check(f"entry_path stays 'direct' (got {c.entry_path!r})", c.entry_path == "direct")
    db.close()
    with engine.connect() as conn:
        flag = _get_app_meta(conn, "legacy_attribution_v1")
    ok3 = check(f"flag is 'done' (got {flag!r})", flag == "done")
    return ok1 and ok2 and ok3


def main():
    results = [
        test_migration_tags_legacy_rows(),
        test_migration_carries_forward_existing_source(),
        test_migration_recovers_start_payload(),
        test_migration_leaves_no_payload_null(),
        test_migration_picks_newest_start_payload(),
        test_migration_ignores_bare_start(),
        test_migration_is_idempotent(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd backend
python -m scripts.test_legacy_attribution
```

Expected: ImportError on `_run_legacy_attribution_migration_v1` or NameError.

- [ ] **Step 3: Implement the migration.**

In `backend/app/database/__init__.py`, immediately after `_set_app_meta` from Task 3, add:

```python
import re as _re

_START_PAYLOAD_RE = _re.compile(r"^/start\s+(\S+)", _re.IGNORECASE)


def _run_legacy_attribution_migration_v1(conn) -> None:
    """
    One-time migration. Tags all rows with NULL entry_path as
    'legacy_pre_attribution', carries Contact.source forward into
    Contact.source_tag, and best-effort recovers historical
    /start <payload> from message history.

    Idempotent: gated by app_meta['legacy_attribution_v1'] == 'done'.
    Safe to retry — every step is conditional on its target column being NULL.
    """
    import time
    if _get_app_meta(conn, "legacy_attribution_v1") == "done":
        return

    t0 = time.monotonic()

    # Step 1: carry source forward into source_tag where source_tag is NULL
    conn.execute(text(
        "UPDATE contacts SET source_tag = source "
        "WHERE source_tag IS NULL AND source IS NOT NULL"
    ))

    # Step 2: tag every row that doesn't yet have an entry_path
    tagged = conn.execute(text(
        "UPDATE contacts SET entry_path = 'legacy_pre_attribution' "
        "WHERE entry_path IS NULL"
    )).rowcount or 0

    # Step 3: best-effort /start payload recovery for rows where source_tag is still NULL
    rows = conn.execute(text(
        "SELECT id FROM contacts WHERE source_tag IS NULL"
    )).fetchall()
    recovered = 0
    for (contact_id,) in rows:
        msgs = conn.execute(
            text(
                "SELECT message_text FROM messages "
                "WHERE user_id = :id AND direction = 'inbound' "
                "ORDER BY timestamp DESC"
            ),
            {"id": contact_id},
        ).fetchall()
        for (text_val,) in msgs:
            if not text_val:
                continue
            m = _START_PAYLOAD_RE.match(text_val)
            if m:
                conn.execute(
                    text("UPDATE contacts SET source_tag = :tag WHERE id = :id"),
                    {"tag": m.group(1), "id": contact_id},
                )
                recovered += 1
                break

    conn.commit()
    _set_app_meta(conn, "legacy_attribution_v1", "done")

    import logging
    logging.getLogger(__name__).info(
        "Legacy attribution migration: tagged %d contacts, recovered %d /start payloads in %dms",
        tagged, recovered, int((time.monotonic() - t0) * 1000),
    )
```

Note: the `text` (lowercase) symbol is already imported at line 19 of the file (`from sqlalchemy import create_engine, event, inspect, text`). The `re` import is namespaced as `_re` to avoid colliding with any future direct `re` import.

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd backend
python -m scripts.test_legacy_attribution
```

Expected: `Results: 7/7 test groups passed`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/database/__init__.py backend/scripts/test_legacy_attribution.py
git commit -m "feat(db): one-time legacy attribution migration + tests"
```

---

## Task 5: Wire the migration into `init_db()`

**Files:**
- Modify: `backend/app/database/__init__.py:440-468` (the `init_db` function)

- [ ] **Step 1: Add a call to the migration after `_ensure_columns()`.**

In `init_db()`, after the `try: _ensure_columns()` block (around line 454-456) and before the `_seed_organization()` block, insert:

```python
    try:
        with engine.connect() as conn:
            _run_legacy_attribution_migration_v1(conn)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("legacy_attribution_v1 migration failed: %s", e)
```

The placement matters: columns must already exist before the migration runs (`_ensure_columns` ran), and the org/workspace seed must NOT run before the migration (the migration only touches `contacts` and `messages`, both of which exist after `create_all`).

- [ ] **Step 2: Smoke-test that init_db calls the migration without errors.**

```bash
cd backend
DATABASE_URL=sqlite:///:memory: python -c "
from app.database import init_db, engine, _get_app_meta
init_db()
with engine.connect() as conn:
    flag = _get_app_meta(conn, 'legacy_attribution_v1')
assert flag == 'done', f'expected done, got {flag!r}'
print('ok')
"
```

Expected output: `ok`

- [ ] **Step 3: Commit.**

```bash
git add backend/app/database/__init__.py
git commit -m "feat(db): call legacy_attribution_v1 from init_db"
```

---

## Task 6: Mirror `extract_start_source` writes to `source_tag`

**Files:**
- Modify: `backend/app/handlers/leads.py:60-105` (both branches of `ensure_contact`)
- Modify: `backend/app/services/telethon_client.py:160-170` (the existing source-update block)

- [ ] **Step 1: Update the `ensure_contact` update branch to also write `source_tag`.**

In `backend/app/handlers/leads.py`, find lines 68-69:

```python
        if source is not None:
            contact.source = source
```

Replace with:

```python
        if source is not None:
            contact.source = source           # legacy mirror
            contact.source_tag = source
```

- [ ] **Step 2: Update the new-contact branch to also set `source_tag`.**

Still in `ensure_contact`, find the `Contact(...)` constructor call (around lines 91-105). Locate the line `source=source,` and add `source_tag=source,` immediately after it:

```python
    contact = Contact(
        id=user_id,
        workspace_id=workspace_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        source=source,           # legacy mirror
        source_tag=source,
        first_seen=now,
        last_seen=now,
        classification=classification,
        current_stage=spos,            # legacy mirror
        current_stage_id=sid,
        stage_entered_at=entered_at,
        deposit_status="none",
    )
```

- [ ] **Step 3: Mirror the same change in `telethon_client.py`.**

In `backend/app/services/telethon_client.py`, find lines 161-164:

```python
                if source and not contact.source:
                    contact.source = source
                    db.commit()
```

Replace with:

```python
                if source and not contact.source_tag:
                    contact.source = source           # legacy mirror
                    contact.source_tag = source
                    db.commit()
```

The condition swap (`not contact.source_tag` instead of `not contact.source`) is intentional — `source_tag` is the new source of truth.

- [ ] **Step 4: Smoke-test that `/start <param>` populates both columns.**

```bash
cd backend
DATABASE_URL=sqlite:///:memory: python -c "
from app.database import init_db, SessionLocal
init_db()
from app.services.pipeline_seed import seed_default_pipeline
db = SessionLocal()
seed_default_pipeline(1, db)
db.close()

from app.handlers.leads import ensure_contact
db = SessionLocal()
c = ensure_contact(db, 999, 'tester', 'meta_test_campaign', 'Test', 'User', workspace_id=1)
assert c.source == 'meta_test_campaign', c.source
assert c.source_tag == 'meta_test_campaign', c.source_tag
print('ok')
"
```

Expected output: `ok`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/handlers/leads.py backend/app/services/telethon_client.py
git commit -m "feat(leads): mirror /start source writes to source_tag"
```

---

## Task 7: Implement `name_matches_vip_marker` (pure function)

**Files:**
- Modify: `backend/app/services/pipeline.py` — add helpers at the top of the file (after the existing imports)
- Test: `backend/scripts/test_vip_name_promotion.py` (new — partial; extended in Task 8)

- [ ] **Step 1: Write the failing test for the pure helper.**

Create `backend/scripts/test_vip_name_promotion.py`:

```python
"""
Tests for VIP-name promotion: the pure matcher and the side-effecting promotion helper.
Run from backend/:  python -m scripts.test_vip_name_promotion
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.services.pipeline import name_matches_vip_marker

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_word_boundary_matches():
    print("\n=== Test 1: word-boundary matching ===")
    markers = ["vip", "premium"]
    cases = [
        # (first, last, expected_match_or_None)
        ("Mike",       "VIP",       "vip"),
        ("VIP Mike",   None,        "vip"),
        ("Sarah",      "(VIP)",     "vip"),
        ("[VIP] Walid",None,        "vip"),
        ("PREMIUM",    "Member",    "premium"),
        ("Vipul",      None,        None),
        ("vipassana",  None,        None),
        ("Mike",       "Premiummax",None),
        ("",           "",          None),
        (None,         None,        None),
    ]
    all_ok = True
    for first, last, expected in cases:
        got = name_matches_vip_marker(first, last, markers)
        all_ok &= check(
            f"({first!r}, {last!r}) → {expected!r} (got {got!r})",
            got == expected,
        )
    return all_ok


def test_empty_markers_returns_none():
    print("\n=== Test 2: empty marker list returns None ===")
    return check(
        "empty markers → None",
        name_matches_vip_marker("Mike VIP", None, []) is None,
    )


def test_marker_with_regex_special_chars():
    print("\n=== Test 3: markers containing regex metacharacters are escaped ===")
    # Walid could legitimately put '.' or '+' or '*' in markers
    markers = ["v.i.p", "$$$"]
    ok1 = check(
        "literal 'v.i.p' matches 'Mike v.i.p'",
        name_matches_vip_marker("Mike", "v.i.p", markers) == "v.i.p",
    )
    ok2 = check(
        "'v.i.p' does NOT match 'vxixp' (no regex injection)",
        name_matches_vip_marker("Mike", "vxixp", markers) is None,
    )
    return ok1 and ok2


def main():
    # Tests defined in this file run here. Task 8 will append maybe_promote tests.
    results = [
        test_word_boundary_matches(),
        test_empty_markers_returns_none(),
        test_marker_with_regex_special_chars(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd backend
python -m scripts.test_vip_name_promotion
```

Expected: ImportError on `name_matches_vip_marker`.

- [ ] **Step 3: Implement the helpers.**

In `backend/app/services/pipeline.py`, near the top of the file (after the existing imports — around line 26), add:

```python
import re as _re_module


_marker_re_cache: dict[tuple[str, ...], "_re_module.Pattern"] = {}


def _compile_markers(markers: tuple[str, ...]) -> "_re_module.Pattern":
    """Compile a regex that matches any marker as a standalone word (case-insensitive)."""
    if markers in _marker_re_cache:
        return _marker_re_cache[markers]
    escaped = [_re_module.escape(m) for m in markers if m]
    if not escaped:
        pat = _re_module.compile(r"(?!)")  # never matches
    else:
        pat = _re_module.compile(
            r"\b(?:" + "|".join(escaped) + r")\b",
            _re_module.IGNORECASE,
        )
    _marker_re_cache[markers] = pat
    return pat


def name_matches_vip_marker(
    first_name: Optional[str],
    last_name: Optional[str],
    markers: list[str],
) -> Optional[str]:
    """
    Return the matched marker (lowercased) if first+last name contains any
    workspace VIP marker as a standalone word. Otherwise None. Pure function.
    """
    if not markers:
        return None
    text_val = f"{first_name or ''} {last_name or ''}"
    if not text_val.strip():
        return None
    pat = _compile_markers(tuple(markers))
    m = pat.search(text_val)
    return m.group(0).lower() if m else None
```

(The existing `from typing import List, Optional, Tuple` import at line 14 makes `Optional` available.)

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd backend
python -m scripts.test_vip_name_promotion
```

Expected: `Results: 3/3 test groups passed`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/pipeline.py backend/scripts/test_vip_name_promotion.py
git commit -m "feat(pipeline): name_matches_vip_marker pure regex helper + tests"
```

---

## Task 8: Implement `maybe_promote_to_member_stage`

**Files:**
- Modify: `backend/app/services/pipeline.py` — append after `name_matches_vip_marker`
- Modify: `backend/scripts/test_vip_name_promotion.py` — add side-effecting tests

- [ ] **Step 1: Extend the test script with promotion tests.**

In `backend/scripts/test_vip_name_promotion.py`, replace the `main()` function (and add the new test functions above it, but below the existing tests). The full updated file structure should be:

```python
# ... existing imports + check() ...

# (existing tests test_word_boundary_matches / test_empty_markers / test_marker_with_regex_special_chars stay)

import json
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import (
    Base, Contact, Organization, Workspace, PipelineStage, StageHistory,
)
from app.services.pipeline_seed import seed_default_pipeline
from app.services.pipeline import maybe_promote_to_member_stage

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)


def _seed_workspace_with_markers(markers=None):
    """Build org + workspace with the seeded default pipeline. member_stage_id is set by the seeder."""
    db = Session()
    if not db.query(Organization).filter(Organization.id == 1).first():
        db.add(Organization(id=1, name="T")); db.commit()
        db.add(Workspace(id=1, name="T", org_id=1, root_workspace_id=1, workspace_role="owner"))
        db.commit()
        seed_default_pipeline(1, db)
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.vip_marker_phrases = json.dumps(markers if markers is not None else ["vip", "premium"])
    db.commit()
    db.close()


def _stages_by_position():
    db = Session()
    try:
        return {s.position: s for s in
                db.query(PipelineStage).filter(PipelineStage.workspace_id == 1).all()}
    finally:
        db.close()


def _fresh_contact(stage_id, *, contact_id=10, first_name="Mike", last_name=None):
    """Wipe + create a contact at the given stage."""
    db = Session()
    db.query(StageHistory).filter(StageHistory.contact_id == contact_id).delete()
    db.query(Contact).filter(Contact.id == contact_id).delete()
    db.commit()
    ps = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first() if stage_id else None
    pos = ps.position if ps else None
    c = Contact(
        id=contact_id, workspace_id=1, username="t",
        first_name=first_name, last_name=last_name,
        current_stage_id=stage_id, current_stage=pos,
        classification="new_lead", deposit_status="none",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    db.add(c); db.commit()
    return db, c


def test_promotion_from_position_1_succeeds():
    print("\n=== Test 4: lead at position 1 with VIP name → promoted ===")
    _seed_workspace_with_markers(["vip"])
    stages = _stages_by_position()
    member = next(s for s in stages.values() if s.is_member_stage)
    db, c = _fresh_contact(stages[1].id, first_name="VIP Mike")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    ok1 = check(f"promoted=True (got {promoted})", promoted is True)
    ok2 = check(f"current_stage_id={member.id} (got {c.current_stage_id})", c.current_stage_id == member.id)
    ok3 = check(f"classification='vip' (got {c.classification!r})", c.classification == "vip")
    db.close()
    return ok1 and ok2 and ok3


def test_promotion_blocked_at_higher_position():
    print("\n=== Test 5: lead at deposited stage with VIP name → NOT moved ===")
    stages = _stages_by_position()
    deposit_stage = next((s for s in stages.values() if s.is_deposit_stage), stages[8])
    db, c = _fresh_contact(deposit_stage.id, contact_id=11, first_name="VIP Sarah")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    ok1 = check(f"promoted=False (got {promoted})", promoted is False)
    ok2 = check(
        f"current_stage_id stays {deposit_stage.id} (got {c.current_stage_id})",
        c.current_stage_id == deposit_stage.id,
    )
    db.close()
    return ok1 and ok2


def test_no_promotion_without_marker_in_name():
    print("\n=== Test 6: lead at position 1 without VIP marker → not promoted ===")
    stages = _stages_by_position()
    db, c = _fresh_contact(stages[1].id, contact_id=12, first_name="Mike")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    ok1 = check(f"promoted=False (got {promoted})", promoted is False)
    ok2 = check(f"stage stays {stages[1].id} (got {c.current_stage_id})", c.current_stage_id == stages[1].id)
    db.close()
    return ok1 and ok2


def test_no_demotion_when_already_at_member_stage():
    print("\n=== Test 7: lead already at member_stage with VIP name → no-op (no second history row) ===")
    stages = _stages_by_position()
    member = next(s for s in stages.values() if s.is_member_stage)
    db, c = _fresh_contact(member.id, contact_id=13, first_name="VIP Walid")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    history_rows = db.query(StageHistory).filter(StageHistory.contact_id == 13).count()
    ok1 = check(f"promoted=False (got {promoted})", promoted is False)
    ok2 = check(f"stage stays member ({member.id}) (got {c.current_stage_id})", c.current_stage_id == member.id)
    ok3 = check(f"no extra history row (got {history_rows})", history_rows == 0)
    db.close()
    return ok1 and ok2 and ok3


def test_writes_stage_history_with_marker():
    print("\n=== Test 8: promotion writes StageHistory with moved_by='name_marker' ===")
    stages = _stages_by_position()
    member = next(s for s in stages.values() if s.is_member_stage)
    db, c = _fresh_contact(stages[1].id, contact_id=14, first_name="VIP Trader")
    maybe_promote_to_member_stage(c, db)
    history = (db.query(StageHistory)
               .filter(StageHistory.contact_id == 14)
               .order_by(StageHistory.moved_at.desc()).first())
    ok1 = check(f"history row exists", history is not None)
    ok2 = check(f"to_stage_id={member.id} (got {history.to_stage_id})", history.to_stage_id == member.id)
    ok3 = check(f"moved_by='name_marker' (got {history.moved_by!r})", history.moved_by == "name_marker")
    ok4 = check(f"trigger_keyword='vip' (got {history.trigger_keyword!r})", history.trigger_keyword == "vip")
    db.close()
    return ok1 and ok2 and ok3 and ok4


def test_idempotent_double_call():
    print("\n=== Test 9: calling helper twice produces only one StageHistory row ===")
    stages = _stages_by_position()
    db, c = _fresh_contact(stages[1].id, contact_id=15, first_name="VIP Two")
    maybe_promote_to_member_stage(c, db)
    maybe_promote_to_member_stage(c, db)
    rows = db.query(StageHistory).filter(StageHistory.contact_id == 15).count()
    ok = check(f"history rows=1 (got {rows})", rows == 1)
    db.close()
    return ok


def test_no_member_stage_id_configured():
    print("\n=== Test 10: workspace without member_stage_id → no-op ===")
    db = Session()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    saved_member = ws.member_stage_id
    ws.member_stage_id = None
    db.commit()
    db.close()

    stages = _stages_by_position()
    db, c = _fresh_contact(stages[1].id, contact_id=16, first_name="VIP Foo")
    promoted = maybe_promote_to_member_stage(c, db)
    db.close()

    # Restore for downstream tests
    db = Session()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.member_stage_id = saved_member
    db.commit()
    db.close()

    return check(f"promoted=False (got {promoted})", promoted is False)


def main():
    results = [
        test_word_boundary_matches(),
        test_empty_markers_returns_none(),
        test_marker_with_regex_special_chars(),
        test_promotion_from_position_1_succeeds(),
        test_promotion_blocked_at_higher_position(),
        test_no_promotion_without_marker_in_name(),
        test_no_demotion_when_already_at_member_stage(),
        test_writes_stage_history_with_marker(),
        test_idempotent_double_call(),
        test_no_member_stage_id_configured(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the extended tests and verify the new ones fail.**

```bash
cd backend
python -m scripts.test_vip_name_promotion
```

Expected: ImportError on `maybe_promote_to_member_stage`.

- [ ] **Step 3: Implement `maybe_promote_to_member_stage`.**

In `backend/app/services/pipeline.py`, append after `name_matches_vip_marker`:

```python
def maybe_promote_to_member_stage(
    contact: "Contact",
    db: Session,
    *,
    moved_by: str = "name_marker",
) -> bool:
    """
    Forward-only, promotion-only. Returns True if the contact moved to
    member_stage, False otherwise. Idempotent: contacts already at or past
    member_stage are no-ops.

    Reads workspace.vip_marker_phrases (JSON list). Writes a StageHistory
    row when promoted. Re-classifies the contact inline.
    """
    import json as _json

    ws = db.query(Workspace).filter(Workspace.id == contact.workspace_id).first()
    if not ws or not ws.member_stage_id or not ws.vip_marker_phrases:
        return False

    try:
        markers = _json.loads(ws.vip_marker_phrases) or []
    except Exception:
        return False

    matched = name_matches_vip_marker(contact.first_name, contact.last_name, markers)
    if not matched:
        return False

    member = db.query(PipelineStage).filter(PipelineStage.id == ws.member_stage_id).first()
    if not member:
        return False

    current = None
    if contact.current_stage_id:
        current = db.query(PipelineStage).filter(
            PipelineStage.id == contact.current_stage_id,
        ).first()
    current_pos = current.position if current else 0

    if current_pos >= member.position:
        return False  # never demote, never sidestep

    now = datetime.utcnow()
    from_stage_id = contact.current_stage_id
    contact.current_stage_id = member.id
    contact.current_stage = member.position    # legacy mirror
    contact.stage_entered_at = now

    db.add(StageHistory(
        contact_id=contact.id,
        from_stage_id=from_stage_id, to_stage_id=member.id,
        from_stage=current_pos or None, to_stage=member.position,
        moved_at=now, moved_by=moved_by, trigger_keyword=matched,
    ))
    contact.classification = classify_contact(
        db, contact.id,
        getattr(contact, "source_tag", None) or contact.source,
        existing=contact,
    )
    db.commit()
    return True
```

- [ ] **Step 4: Run all 10 tests and verify they pass.**

```bash
cd backend
python -m scripts.test_vip_name_promotion
```

Expected: `Results: 10/10 test groups passed`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/pipeline.py backend/scripts/test_vip_name_promotion.py
git commit -m "feat(pipeline): maybe_promote_to_member_stage forward-only helper + tests"
```

---

## Task 9: Refactor `_initial_stage_for_contact` to use the pure helper

**Files:**
- Modify: `backend/app/handlers/leads.py:122-165`

- [ ] **Step 1: Replace the inline substring check with the helper call.**

In `backend/app/handlers/leads.py`, find `_initial_stage_for_contact` (line 122). The current body has:

```python
    full = f"{first_name or ''} {last_name or ''}".lower()
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    markers: list[str] = []
    if ws and ws.vip_marker_phrases:
        try:
            markers = json.loads(ws.vip_marker_phrases) or []
        except Exception:
            markers = []

    if any(m for m in markers if m and m.lower() in full):
        if ws and ws.member_stage_id:
            stage = db.query(PipelineStage).filter(
                PipelineStage.id == ws.member_stage_id,
            ).first()
            if stage:
                return stage.id, stage.position, now
```

Replace with:

```python
    from app.services.pipeline import name_matches_vip_marker
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    markers: list[str] = []
    if ws and ws.vip_marker_phrases:
        try:
            markers = json.loads(ws.vip_marker_phrases) or []
        except Exception:
            markers = []

    if name_matches_vip_marker(first_name, last_name, markers):
        if ws and ws.member_stage_id:
            stage = db.query(PipelineStage).filter(
                PipelineStage.id == ws.member_stage_id,
            ).first()
            if stage:
                return stage.id, stage.position, now
```

The `full = ...` local is no longer used. The fallback (`first_stage = ...`) below stays unchanged.

- [ ] **Step 2: Run the existing pipeline tests to make sure nothing regressed.**

```bash
cd backend
python -m scripts.test_pipeline
python -m scripts.test_vip_name_promotion
```

Expected: both scripts report all tests passing.

- [ ] **Step 3: Smoke-test that a fresh VIP-named contact still lands at member_stage.**

```bash
cd backend
DATABASE_URL=sqlite:///:memory: python -c "
from app.database import init_db, SessionLocal
from app.database.models import Workspace
from app.services.pipeline_seed import seed_default_pipeline
import json
init_db()
db = SessionLocal()
seed_default_pipeline(1, db)
ws = db.query(Workspace).filter(Workspace.id == 1).first()
ws.vip_marker_phrases = json.dumps(['vip'])
db.commit()
db.close()

from app.handlers.leads import ensure_contact
db = SessionLocal()
c = ensure_contact(db, 555, 'tester', None, 'VIP Trader', 'X', workspace_id=1)
db.refresh(c)
ws = db.query(Workspace).filter(Workspace.id == 1).first()
assert c.current_stage_id == ws.member_stage_id, f'{c.current_stage_id} != {ws.member_stage_id}'
print('ok')
"
```

Expected: `ok`

- [ ] **Step 4: Commit.**

```bash
git add backend/app/handlers/leads.py
git commit -m "refactor(leads): _initial_stage_for_contact uses name_matches_vip_marker"
```

---

## Task 10: Wire `ensure_contact` update path to call `maybe_promote_to_member_stage`

**Files:**
- Modify: `backend/app/handlers/leads.py:42-86` (update branch of `ensure_contact`)
- Test: `backend/scripts/test_ensure_contact_rename.py` (new)

- [ ] **Step 1: Write the failing test.**

Create `backend/scripts/test_ensure_contact_rename.py`:

```python
"""
Tests that ensure_contact's update path re-runs the VIP-name check on rename.
Run from backend/:  python -m scripts.test_ensure_contact_rename
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import datetime
from app.database import init_db, SessionLocal
from app.database.models import Contact, StageHistory, Workspace, PipelineStage
from app.services.pipeline_seed import seed_default_pipeline
from app.handlers.leads import ensure_contact

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _setup():
    init_db()
    db = SessionLocal()
    seed_default_pipeline(1, db)
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.vip_marker_phrases = json.dumps(["vip"])
    db.commit()
    db.close()


def test_rename_to_vip_promotes_existing_contact():
    print("\n=== Test 1: rename to 'VIP Mike' promotes contact at stage 1 ===")
    db = SessionLocal()
    # Create as 'Mike' first — should land at first stage
    c = ensure_contact(db, 1001, "mike", None, "Mike", None, workspace_id=1)
    db.refresh(c)
    stage1_id = c.current_stage_id
    db.close()

    # Now "rename" to VIP via a second ensure_contact call
    db = SessionLocal()
    ensure_contact(db, 1001, "mike", None, "VIP Mike", None, workspace_id=1)
    c = db.query(Contact).filter(Contact.id == 1001).first()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ok1 = check(f"started at stage {stage1_id}", stage1_id is not None)
    ok2 = check(
        f"now at member_stage_id {ws.member_stage_id} (got {c.current_stage_id})",
        c.current_stage_id == ws.member_stage_id,
    )
    history = (db.query(StageHistory)
               .filter(StageHistory.contact_id == 1001)
               .order_by(StageHistory.moved_at.desc()).first())
    ok3 = check(
        f"history row moved_by='name_marker' (got {history.moved_by!r})",
        history is not None and history.moved_by == "name_marker",
    )
    db.close()
    return ok1 and ok2 and ok3


def test_rename_with_no_change_skips_promotion_check():
    print("\n=== Test 2: same-name re-call does not write a duplicate history row ===")
    db = SessionLocal()
    rows_before = db.query(StageHistory).filter(StageHistory.contact_id == 1001).count()
    ensure_contact(db, 1001, "mike", None, "VIP Mike", None, workspace_id=1)
    rows_after = db.query(StageHistory).filter(StageHistory.contact_id == 1001).count()
    db.close()
    return check(f"history rows unchanged ({rows_before} → {rows_after})", rows_before == rows_after)


def test_rename_loses_marker_does_not_demote():
    print("\n=== Test 3: removing the VIP marker does NOT demote ===")
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    member_id = ws.member_stage_id
    db.close()

    # Contact 1001 is at member_stage; rename it to remove the marker
    db = SessionLocal()
    ensure_contact(db, 1001, "mike", None, "Mike", None, workspace_id=1)
    c = db.query(Contact).filter(Contact.id == 1001).first()
    db.close()
    return check(
        f"stays at member_stage {member_id} (got {c.current_stage_id})",
        c.current_stage_id == member_id,
    )


def main():
    _setup()
    results = [
        test_rename_to_vip_promotes_existing_contact(),
        test_rename_with_no_change_skips_promotion_check(),
        test_rename_loses_marker_does_not_demote(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd backend
python -m scripts.test_ensure_contact_rename
```

Expected: Test 1 fails — contact stays at stage 1 because the rename hook isn't wired yet.

- [ ] **Step 3: Wire the rename hook into `ensure_contact`.**

In `backend/app/handlers/leads.py`, replace the entire `if contact:` block (lines 60-86) with:

```python
    if contact:
        contact.last_seen = now
        if username is not None:
            contact.username = username

        # Capture name change BEFORE assigning so we know whether to re-check the marker
        name_changed = (
            (first_name is not None and first_name != contact.first_name) or
            (last_name  is not None and last_name  != contact.last_name)
        )
        if first_name is not None:
            contact.first_name = first_name
        if last_name is not None:
            contact.last_name = last_name
        if source is not None:
            contact.source = source           # legacy mirror
            contact.source_tag = source

        # Initialise missing defaults (rows created before CRM columns existed)
        if contact.current_stage_id is None:
            sid, spos, _ = _initial_stage_for_contact(db, workspace_id, contact.first_name, contact.last_name, now)
            if sid is not None:
                contact.current_stage_id = sid
                contact.current_stage = spos  # legacy mirror
        if contact.stage_entered_at is None:
            contact.stage_entered_at = now

        # Re-run the VIP-name check if the name moved
        if name_changed:
            from app.services.pipeline import maybe_promote_to_member_stage
            maybe_promote_to_member_stage(contact, db)

        # Re-classify in case stage or deposit status changed
        contact.classification = classify_contact(
            db, user_id, contact.source_tag or contact.source, existing=contact,
        )
        db.commit()
        db.refresh(contact)
        return contact
```

Notes:
- The `source` block from Task 6 is preserved.
- `name_changed` must be computed *before* the `contact.first_name = ...` assignments — that's the entire point.
- `classify_contact` now reads `contact.source_tag or contact.source` (small change from line 82's `contact.source`) so the new column takes precedence once populated.
- `maybe_promote_to_member_stage` itself commits if it promotes; the trailing `db.commit()` is a no-op in that case but still needed for the classification update.

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd backend
python -m scripts.test_ensure_contact_rename
```

Expected: `Results: 3/3 test groups passed`

- [ ] **Step 5: Run the broader test suite to check for regressions.**

```bash
cd backend
python -m scripts.test_pipeline
python -m scripts.test_vip_name_promotion
python -m scripts.test_ensure_contact_rename
python -m scripts.test_legacy_attribution
python -m scripts.test_app_meta
```

Expected: every script reports all tests passing.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/handlers/leads.py backend/scripts/test_ensure_contact_rename.py
git commit -m "feat(leads): re-run VIP-name check on rename in ensure_contact"
```

---

## Task 11: Wire backfill loop to call `maybe_promote_to_member_stage`

**Files:**
- Modify: `backend/app/services/backfill.py:42-82`

- [ ] **Step 1: Add the helper call after `ensure_contact` returns the contact.**

In `backend/app/services/backfill.py`, find the section starting at line 64:

```python
            contact = (
                db.query(Contact)
                .filter(Contact.id == user_id, Contact.workspace_id == workspace_id)
                .first()
            )
            if not contact:
                skipped += 1
                continue

            async for msg in client.iter_messages(user, limit=limit_per_dialog, reverse=True):
```

Insert the helper call between `if not contact:` and `async for msg in ...`:

```python
            contact = (
                db.query(Contact)
                .filter(Contact.id == user_id, Contact.workspace_id == workspace_id)
                .first()
            )
            if not contact:
                skipped += 1
                continue

            # VIP-name re-detection — covers the case where the operator already
            # renamed the lead (e.g. "VIP Mike") before backfill was run.
            from app.services.pipeline import maybe_promote_to_member_stage
            maybe_promote_to_member_stage(contact, db)

            async for msg in client.iter_messages(user, limit=limit_per_dialog, reverse=True):
```

- [ ] **Step 2: Smoke-test that backfill imports cleanly.**

```bash
cd backend
python -c "from app.services.backfill import backfill_workspace_history; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit.**

```bash
git add backend/app/services/backfill.py
git commit -m "feat(backfill): re-run VIP-name detection per dialog"
```

(Note: a deeper integration test of the backfill loop would require a Telethon mock that yields synthetic dialogs; that's out of scope for this plan. The unit-level coverage in `test_vip_name_promotion.py` and `test_ensure_contact_rename.py` exercise the same helper from both call paths.)

---

## Task 12: Persist `last_backfill_at` and `last_backfill_summary` in `backfill_workspace_history`

**Files:**
- Modify: `backend/app/services/backfill.py:84-92`
- Test: `backend/scripts/test_backfill_persists_summary.py` (new)

- [ ] **Step 1: Write the failing test.**

Create `backend/scripts/test_backfill_persists_summary.py`:

```python
"""
Tests that backfill_workspace_history persists last_backfill_at and
last_backfill_summary on the Workspace row.

Run from backend/:  python -m scripts.test_backfill_persists_summary
"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.database import init_db, SessionLocal
from app.database.models import Workspace
from app.services.backfill import backfill_workspace_history

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_persists_summary_on_no_telethon():
    """
    Without a Telethon client the function returns early with an error dict.
    Even in that case it should NOT crash; we expect last_backfill_at to remain
    NULL because nothing was actually run.
    """
    print("\n=== Test 1: no Telethon → no-op, no crash ===")
    init_db()
    result = asyncio.run(backfill_workspace_history(1))
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    db.close()
    ok1 = check(f"returned an error dict (got {result})", "error" in result)
    ok2 = check(f"last_backfill_at IS NULL (got {ws.last_backfill_at!r})", ws.last_backfill_at is None)
    return ok1 and ok2


def test_persists_summary_on_successful_run():
    """
    Stub out the Telethon client and verify last_backfill_at + summary are set.
    """
    print("\n=== Test 2: stubbed Telethon → summary persisted ===")

    class _StubDialog:
        is_user = False  # all dialogs skipped → 0 contacts, 0 messages, 0 skipped

    class _StubClient:
        async def iter_dialogs(self):
            for d in []:
                yield d

    # Monkey-patch get_client
    from app.services import telethon_client as tc
    saved = tc.get_client
    tc.get_client = lambda ws_id: _StubClient()
    try:
        result = asyncio.run(backfill_workspace_history(1))
    finally:
        tc.get_client = saved

    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    db.close()
    ok1 = check(f"result has expected keys (got {result})",
                set(result.keys()) >= {"contacts_created", "messages_replayed", "skipped"})
    ok2 = check(f"last_backfill_at is set (got {ws.last_backfill_at!r})", ws.last_backfill_at is not None)
    summary = json.loads(ws.last_backfill_summary) if ws.last_backfill_summary else {}
    ok3 = check(f"summary contacts_created=0 (got {summary.get('contacts_created')!r})",
                summary.get("contacts_created") == 0)
    return ok1 and ok2 and ok3


def main():
    results = [
        test_persists_summary_on_no_telethon(),
        test_persists_summary_on_successful_run(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test and verify it fails.**

```bash
cd backend
python -m scripts.test_backfill_persists_summary
```

Expected: Test 2 fails — `last_backfill_at` is still NULL.

- [ ] **Step 3: Update `backfill_workspace_history` to persist the summary.**

In `backend/app/services/backfill.py`, find the `finally:` block at lines 81-82:

```python
    finally:
        db.close()

    logger.info(
        "backfill ws=%s contacts_created=%s messages=%s skipped=%s",
        workspace_id, contacts_created, messages_replayed, skipped,
    )
    return {
        "contacts_created": contacts_created,
        "messages_replayed": messages_replayed,
        "skipped": skipped,
    }
```

Replace with:

```python
    finally:
        db.close()

    summary = {
        "contacts_created": contacts_created,
        "messages_replayed": messages_replayed,
        "skipped": skipped,
    }

    # Persist summary on the workspace
    import json as _json
    from datetime import datetime
    from app.database.models import Workspace
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if ws:
            ws.last_backfill_at = datetime.utcnow()
            ws.last_backfill_summary = _json.dumps(summary)
            db.commit()
    finally:
        db.close()

    logger.info(
        "backfill ws=%s contacts_created=%s messages=%s skipped=%s",
        workspace_id, contacts_created, messages_replayed, skipped,
    )
    return summary
```

The early-return path (when `client is None` at lines 27-34) intentionally does NOT touch the workspace — that matches Test 1.

- [ ] **Step 4: Run the test and verify it passes.**

```bash
cd backend
python -m scripts.test_backfill_persists_summary
```

Expected: `Results: 2/2 test groups passed`

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/backfill.py backend/scripts/test_backfill_persists_summary.py
git commit -m "feat(backfill): persist last_backfill_at and summary on workspace"
```

---

## Task 13: Extend `GET /settings/telethon/status` with backfill summary

**Files:**
- Modify: `backend/app/main.py:1056-1062`

- [ ] **Step 1: Update the endpoint body.**

In `backend/app/main.py`, find the `telethon_status` function (line 1056). Replace the entire function body with:

```python
@app.get("/settings/telethon/status")
def telethon_status(
    workspace_id: int = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    _=Depends(require_workspace_owner),
):
    from app.services.telethon_client import get_client
    from app.database.models import Workspace
    import json as _json

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    last_summary = None
    if ws and ws.last_backfill_summary:
        try:
            last_summary = _json.loads(ws.last_backfill_summary)
        except Exception:
            last_summary = None
    return {
        "connected": get_client(workspace_id) is not None,
        "last_backfill_at": ws.last_backfill_at.isoformat() if ws and ws.last_backfill_at else None,
        "last_backfill_summary": last_summary,
    }
```

- [ ] **Step 2: Smoke-test the endpoint shape.**

```bash
cd backend
DATABASE_URL=sqlite:///:memory: python -c "
from fastapi.testclient import TestClient
import os
os.environ.setdefault('SECRET_KEY', 'test')
from app.main import app
from app.database import init_db, SessionLocal
from app.database.models import Workspace
from datetime import datetime
import json as _json
init_db()
db = SessionLocal()
ws = db.query(Workspace).filter(Workspace.id == 1).first()
ws.last_backfill_at = datetime(2026, 4, 29, 12, 0, 0)
ws.last_backfill_summary = _json.dumps({'contacts_created': 7, 'messages_replayed': 42, 'skipped': 1})
db.commit()
db.close()

# Direct unit-test the function (skip auth wiring)
from app.main import telethon_status
db = SessionLocal()
result = telethon_status(workspace_id=1, db=db, _=None)
db.close()
assert 'connected' in result
assert result['last_backfill_at'] == '2026-04-29T12:00:00'
assert result['last_backfill_summary']['contacts_created'] == 7
print('ok')
"
```

Expected output: `ok`

- [ ] **Step 3: Commit.**

```bash
git add backend/app/main.py
git commit -m "feat(api): expose last_backfill_at and summary via /settings/telethon/status"
```

---

## Task 14: Add the "Sync Telegram history" card to the frontend

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Locate the Telegram tab and the Telethon connection block.**

In `frontend/src/pages/SettingsPage.tsx`, the Telegram tab is rendered by a component that uses the `/settings/telethon/status` endpoint (search for `settings/telethon/status` — appears around line 1079 in the existing code). Read the existing component structure to confirm:

```bash
grep -n "settings/telethon/status\|TelethonTab\|TelegramTab\|TelethonConnect" frontend/src/pages/SettingsPage.tsx | head -10
```

Identify the function/component that owns the Telegram tab (likely `TelegramTab` or similar). The new card goes in the same component, below the existing Telethon connection UI.

- [ ] **Step 2: Extend the existing telethon-status fetch to capture the new fields.**

Find the `useEffect` or fetch call that hits `/settings/telethon/status` (around line 1079). It currently sets a `connected` boolean. Update it to also store the two new fields. Example shape (adjust to match the existing state-management style):

```ts
type TelethonStatus = {
  connected: boolean;
  last_backfill_at: string | null;
  last_backfill_summary: { contacts_created: number; messages_replayed: number; skipped: number } | null;
};

const [telethonStatus, setTelethonStatus] = useState<TelethonStatus>({
  connected: false,
  last_backfill_at: null,
  last_backfill_summary: null,
});

// In the fetch:
fetch(`${API_BASE}/settings/telethon/status`, { headers: authHeaders() })
  .then(r => r.json())
  .then((s: TelethonStatus) => setTelethonStatus(s))
  .catch(() => {});
```

If `connected` is already stored as a separate boolean state (e.g., `telethonConnected`), preserve that and add the two new fields alongside it as siblings — don't restructure the existing state shape if it would be invasive.

- [ ] **Step 3: Add a `syncing` state for the button.**

Inside the same component:

```ts
const [syncing, setSyncing] = useState(false);
```

- [ ] **Step 4: Add the `handleSyncBackfill` callback.**

Inside the same component (next to other handlers like `handleConnectTelethon`):

```ts
async function handleSyncBackfill() {
  if (syncing) return;
  setSyncing(true);
  try {
    const workspaceId = currentWorkspaceId();  // existing helper used elsewhere on this page
    const res = await fetch(
      `${API_BASE}/workspaces/${workspaceId}/backfill-telegram-history?limit_per_dialog=500`,
      {
        method: "POST",
        headers: authHeaders(),
        signal: AbortSignal.timeout(5 * 60 * 1000),
      },
    );
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast.error(`Sync failed: ${body.detail || res.status}`);
      return;
    }
    if (body.error) {
      toast.error(body.error);
      return;
    }
    toast.success(
      `Synced: ${body.contacts_created} contacts, ${body.messages_replayed} messages, ${body.skipped} skipped`,
    );
    // Refresh status so the "Last run" line updates
    const fresh = await fetch(`${API_BASE}/settings/telethon/status`, { headers: authHeaders() }).then(r => r.json());
    setTelethonStatus(fresh);
  } catch (e: any) {
    if (e?.name === "TimeoutError") {
      toast.error("Sync took too long — check status manually.");
    } else {
      toast.error(`Sync failed: ${e?.message || e}`);
    }
  } finally {
    setSyncing(false);
  }
}
```

If the project uses a different toast library (e.g. `sonner` vs `react-hot-toast`), adapt the import. Inspect existing toast usage on `SettingsPage.tsx` (`grep -n "toast\." frontend/src/pages/SettingsPage.tsx | head -5`) and match the same pattern.

If `currentWorkspaceId()` isn't a real helper, replace with however the page accesses the workspace_id — most likely from a JWT decode utility or an `auth` helper used elsewhere on the page (`grep -n "workspace_id" frontend/src/pages/SettingsPage.tsx | head -5`).

- [ ] **Step 5: Render the "Sync Telegram history" card.**

Below the existing Telethon connection UI (find the JSX rendering the "Connect" / "Disconnect" buttons), add:

```tsx
<div className="mt-6 rounded-lg border border-border bg-card p-4">
  <h3 className="text-base font-semibold text-foreground">Sync Telegram history</h3>
  <p className="mt-1 text-sm text-muted-foreground">
    Pull past DMs from your connected Telegram account into the CRM.
    Replays operator messages through the keyword pipeline so historical leads
    land at the right stage. Run after first connecting, or after batch-renaming
    leads.
  </p>
  <p className="mt-2 text-xs text-muted-foreground">
    {telethonStatus.last_backfill_at
      ? `Last run: ${new Date(telethonStatus.last_backfill_at).toLocaleString()} — ${telethonStatus.last_backfill_summary?.contacts_created ?? 0} contacts, ${telethonStatus.last_backfill_summary?.messages_replayed ?? 0} messages, ${telethonStatus.last_backfill_summary?.skipped ?? 0} skipped`
      : "Last run: never"}
  </p>
  <button
    type="button"
    onClick={handleSyncBackfill}
    disabled={syncing || !telethonStatus.connected}
    className="mt-3 inline-flex items-center justify-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
    title={!telethonStatus.connected ? "Connect Telegram first" : undefined}
  >
    {syncing ? "Syncing…" : "Sync now"}
  </button>
</div>
```

Match the className conventions used elsewhere on `SettingsPage.tsx`. If the page doesn't use `bg-card` / `text-muted-foreground` / etc., substitute with the project's actual Tailwind theme classes (inspect any nearby card component).

- [ ] **Step 6: Type-check and build.**

```bash
cd frontend
npx tsc --noEmit
npm run build
```

Expected: both succeed without errors.

- [ ] **Step 7: Manual smoke-test (DEV).**

```bash
# Terminal 1
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

Open `http://localhost:5173`, log in as admin, go to Settings → Telegram. Verify:
- The "Sync Telegram history" card renders below the connection block.
- "Last run: never" appears when `last_backfill_at` is NULL.
- The "Sync now" button is disabled when Telethon is disconnected.
- Clicking "Sync now" while connected fires the request, shows the toast, and updates "Last run".

(If Telethon is hard to connect locally, test by manually setting `Workspace.last_backfill_at` and `last_backfill_summary` via SQL and refreshing — Step 8 covers verifying just the rendering.)

- [ ] **Step 8: Commit.**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat(ui): Sync Telegram history card on Settings → Telegram"
```

---

## Task 15: Add `entry_path` and `source_tag` to the frontend `Contact` type

**Files:**
- Modify: whichever frontend type file declares the `Contact` interface (likely `frontend/src/api/contacts.ts` or `frontend/src/types.ts` — confirm by `grep -rn "interface Contact\|type Contact " frontend/src --include="*.ts" --include="*.tsx" | head`)

- [ ] **Step 1: Locate the type definition.**

```bash
grep -rn "interface Contact\b\|type Contact = \|type Contact\b" frontend/src --include="*.ts" --include="*.tsx" | head
```

Open the file that declares `Contact` (or whichever type/interface is the canonical lead row). Identify the existing `source` field.

- [ ] **Step 2: Add the two new fields.**

Locate the existing `source` line. Add the two new optional fields immediately after it:

```ts
  source: string | null;       // legacy — being deprecated; mirror of source_tag
  source_tag: string | null;
  entry_path: string | null;
```

(Adjust syntax to match the file — e.g. `source?: string | null` if the convention is optional fields.)

- [ ] **Step 3: Type-check.**

```bash
cd frontend
npx tsc --noEmit
```

Expected: passes. If any consumer code accesses `entry_path` / `source_tag` and they were missing, `tsc` will flag those — but since this spec doesn't add any new consumers, there should be no errors.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/  # adjust path to whichever file changed
git commit -m "feat(types): add entry_path and source_tag to Contact"
```

---

## Task 16: Final integration smoke-test

**Files:**
- (No file changes — full-flow validation only.)

- [ ] **Step 1: Run every test script.**

```bash
cd backend
source .venv/bin/activate

set -e  # any failure aborts
python -m scripts.test_app_meta
python -m scripts.test_legacy_attribution
python -m scripts.test_vip_name_promotion
python -m scripts.test_ensure_contact_rename
python -m scripts.test_backfill_persists_summary
python -m scripts.test_pipeline       # existing — make sure we didn't regress it
```

Expected: every script reports all tests passing.

- [ ] **Step 2: Run a fresh `init_db` against a clean SQLite to verify cold-boot behavior.**

```bash
cd backend
rm -f /tmp/lead_classification_smoke.db
DATABASE_URL=sqlite:////tmp/lead_classification_smoke.db python -c "
from app.database import init_db, engine, _get_app_meta
init_db()
with engine.connect() as conn:
    flag = _get_app_meta(conn, 'legacy_attribution_v1')
assert flag == 'done', f'flag={flag!r}'
print('ok')
"
rm -f /tmp/lead_classification_smoke.db
```

Expected output: `ok`

- [ ] **Step 3: Type-check + build the frontend.**

```bash
cd frontend
npx tsc --noEmit
npm run build
```

Expected: both succeed.

- [ ] **Step 4: No commit needed for this task.**

(Smoke-test only. If anything failed, fix it as a new commit on the failing task — do not paper over with a "test fix" commit.)

---

## Self-review notes

The plan above maps to the spec as follows:

| Spec section | Tasks |
|---|---|
| Slice 1 — schema columns | 1, 2 |
| Slice 1 — `app_meta` + helpers | 1, 3 |
| Slice 1 — legacy migration | 4, 5 |
| Slice 1 — passive `/start` populator | 6 |
| Slice 2 — pure matcher helper | 7 |
| Slice 2 — promotion helper | 8 |
| Slice 2 — initial-create call site | 9 |
| Slice 2 — rename hook | 10 |
| Slice 2 — backfill loop call site | 11 |
| Slice 3 — backend (last-run summary) | 12 |
| Slice 3 — backend (status endpoint) | 13 |
| Slice 3 — frontend card | 14 |
| Slice 3 — frontend types | 15 |
| Integration validation | 16 |

No spec section is unaddressed.

## Out-of-scope reminders (for the engineer)

- Do **not** add the per-campaign invite-link table, the `/attribution/invite` endpoint, the Telethon channel-join listener, or the pending-attribution claim flow. Those are Spec B.
- Do **not** drop the legacy `Contact.source` column. Mirror writes to it for one stable week; the cleanup PR is a separate task.
- Do **not** auto-trigger backfill from the onboarding wizard. Manual button only.
