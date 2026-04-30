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
