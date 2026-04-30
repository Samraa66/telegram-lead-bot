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
