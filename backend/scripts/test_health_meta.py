"""
Tests for check_meta.
Run from backend/:  python -m scripts.test_health_meta
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database.models import Workspace
from app.services.health_cache import _probe_cache
from scripts.test_health_mocks import MockHttpClient

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _ws(token="meta_t", landing=None):
    return Workspace(id=1, meta_access_token=token, landing_page_url=landing)


def _meta_url(token):
    return f"https://graph.facebook.com/v19.0/me?fields=id,name,permissions&access_token={token}"


def _granted(perms_list):
    return {"id": "1", "name": "x", "permissions": {"data": [
        {"permission": p, "status": "granted"} for p in perms_list
    ]}}


def test_warn_when_no_token():
    print("\n=== Test 1: warn when no Meta token saved ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(token=None)
    result = asyncio.run(check_meta(ws, MockHttpClient({})))
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_ok_when_token_valid_with_ads_management():
    print("\n=== Test 2: ok when token valid + ads_management granted ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(landing="https://lp.example.com")
    routes = {_meta_url("meta_t"): (200, _granted(["ads_management", "business_management"]))}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=ok (got {result['status']!r})", result["status"] == "ok")
    ok2 = check(f"detail mentions landing", "landing" in result["detail"].lower())
    return ok1 and ok2


def test_error_when_missing_ads_management():
    print("\n=== Test 3: error when token valid but missing ads_management ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws()
    routes = {_meta_url("meta_t"): (200, _granted(["public_profile"]))}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_error_when_token_rejected():
    print("\n=== Test 4: error when Meta returns {error:...} ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws()
    routes = {_meta_url("meta_t"): (200, {"error": {"message": "token expired"}})}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_warn_when_unreachable():
    print("\n=== Test 5: warn when Graph API unreachable ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws()
    routes = {_meta_url("meta_t"): (200, "TIMEOUT")}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail says could not reach", "could not reach" in result["detail"].lower() or "unreachable" in result["detail"].lower())
    return ok1 and ok2


def main():
    results = [
        test_warn_when_no_token(),
        test_ok_when_token_valid_with_ads_management(),
        test_error_when_missing_ads_management(),
        test_error_when_token_rejected(),
        test_warn_when_unreachable(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
