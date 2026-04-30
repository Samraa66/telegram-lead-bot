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
