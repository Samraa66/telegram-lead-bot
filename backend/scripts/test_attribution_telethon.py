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
