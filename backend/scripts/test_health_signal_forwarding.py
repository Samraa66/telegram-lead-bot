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
