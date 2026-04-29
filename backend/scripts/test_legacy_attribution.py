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
from app.database.models import Contact, Message

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
