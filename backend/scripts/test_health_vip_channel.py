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
        referral_tag="aff_test", vip_channel_id=vip_channel_id, is_active=True,
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
