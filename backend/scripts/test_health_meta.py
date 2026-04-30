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


def _ws(token="meta_t", landing=None, account_id=None):
    return Workspace(id=1, meta_access_token=token,
                     landing_page_url=landing, meta_ad_account_id=account_id)


def _me_url(token):
    return f"https://graph.facebook.com/v19.0/me?fields=id,name,permissions&access_token={token}"


def _granted(perms_list):
    return {"id": "1", "name": "x", "permissions": {"data": [
        {"permission": p, "status": "granted"} for p in perms_list
    ]}}


# Prefix-only routes for the three account-scoped probes.
# MockHttpClient routes by URL prefix, so the trailing query-string fields
# don't need to be enumerated exactly.
def _campaigns_route(account_id, body):
    return {f"https://graph.facebook.com/v19.0/act_{account_id}/campaigns": (200, body)}


def _creatives_route(account_id, body):
    return {f"https://graph.facebook.com/v19.0/act_{account_id}/adcreatives": (200, body)}


def _insights_route(account_id, body):
    return {f"https://graph.facebook.com/v19.0/act_{account_id}/insights": (200, body)}


def _full_routes_ok(account_id, token="meta_t", perms=None):
    """Routes for token=ok, perms granted, all 3 probes returning rows."""
    perms = perms or ["ads_management"]
    routes = {_me_url(token): (200, _granted(perms))}
    routes.update(_campaigns_route(account_id, {"data": [{"id": "c1", "name": "Campaign A", "effective_status": "ACTIVE"}]}))
    routes.update(_creatives_route(account_id, {"data": [{"id": "cr1", "name": "Creative A"}]}))
    routes.update(_insights_route(account_id, {"data": [{"impressions": "1234", "spend": "56.78"}]}))
    return routes


def test_warn_when_no_token():
    print("\n=== Test 1: warn when no Meta token saved ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(token=None)
    result = asyncio.run(check_meta(ws, MockHttpClient({})))
    return check(f"status=warn (got {result['status']!r})", result["status"] == "warn")


def test_ok_when_all_data_flowing():
    print("\n=== Test 2: ok when token valid + ads_management + campaigns + creatives + recent insights ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(landing="https://lp.example.com", account_id="999")
    routes = _full_routes_ok("999")
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=ok (got {result['status']!r})", result["status"] == "ok")
    ok2 = check(f"detail mentions landing", "landing" in result["detail"].lower())
    ok3 = check(f"detail mentions campaigns count", "1 campaigns" in result["detail"] or "1 campaign" in result["detail"])
    ok4 = check(f"detail mentions creatives count", "creatives" in result["detail"].lower())
    return ok1 and ok2 and ok3 and ok4


def test_error_when_missing_ads_management():
    print("\n=== Test 3: error when token valid but missing ads_management ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = {_me_url("meta_t"): (200, _granted(["public_profile"]))}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_error_when_token_rejected():
    print("\n=== Test 4: error when Meta returns {error:...} on /me ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = {_me_url("meta_t"): (200, {"error": {"message": "token expired"}})}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_warn_when_unreachable():
    print("\n=== Test 5: warn when Graph API unreachable ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = {_me_url("meta_t"): (200, "TIMEOUT")}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail says could not reach", "could not reach" in result["detail"].lower() or "unreachable" in result["detail"].lower())
    return ok1 and ok2


def test_warn_when_no_ad_account_id():
    print("\n=== Test 6: warn when token good but ad account ID not set ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id=None)
    routes = {_me_url("meta_t"): (200, _granted(["ads_management"]))}
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions ad account",
                "ad account" in result["detail"].lower() or "account id" in result["detail"].lower())
    return ok1 and ok2


def test_warn_when_no_campaigns():
    print("\n=== Test 7: warn when /campaigns returns empty data ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = _full_routes_ok("999")
    routes.update(_campaigns_route("999", {"data": []}))  # empty
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions no campaigns",
                "no campaigns" in result["detail"].lower())
    return ok1 and ok2


def test_warn_when_no_creatives():
    print("\n=== Test 8: warn when /adcreatives returns empty data ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = _full_routes_ok("999")
    routes.update(_creatives_route("999", {"data": []}))  # empty
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions no creatives",
                "no ad creatives" in result["detail"].lower() or "no creatives" in result["detail"].lower())
    return ok1 and ok2


def test_warn_when_no_recent_insights():
    print("\n=== Test 9: warn when /insights returns empty data (no impressions) ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = _full_routes_ok("999")
    routes.update(_insights_route("999", {"data": []}))  # empty
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions no impressions / not delivering",
                "impressions" in result["detail"].lower() or "delivering" in result["detail"].lower())
    return ok1 and ok2


def test_error_when_data_probe_returns_error():
    print("\n=== Test 10: error when a probe returns Meta {error:...} ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = _full_routes_ok("999")
    routes.update(_campaigns_route("999", {"error": {"message": "Permission denied: ads_read"}}))
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=error (got {result['status']!r})", result["status"] == "error")
    ok2 = check(f"detail mentions campaigns",
                "campaign" in result["detail"].lower())
    return ok1 and ok2


def test_warn_when_only_insights_unreachable():
    print("\n=== Test 11: warn when insights probe times out ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="999")
    routes = _full_routes_ok("999")
    routes.update(_insights_route("999", "TIMEOUT"))
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions insights",
                "insights" in result["detail"].lower())
    return ok1 and ok2


def test_account_id_strips_act_prefix():
    print("\n=== Test 12: 'act_999' is normalised to '999' before probing ===")
    _probe_cache.clear()
    from app.services.health import check_meta
    ws = _ws(account_id="act_999")  # user-friendly form
    routes = _full_routes_ok("999")  # account_id without prefix
    result = asyncio.run(check_meta(ws, MockHttpClient(routes)))
    return check(f"status=ok (got {result['status']!r})", result["status"] == "ok")


def main():
    results = [
        test_warn_when_no_token(),
        test_ok_when_all_data_flowing(),
        test_error_when_missing_ads_management(),
        test_error_when_token_rejected(),
        test_warn_when_unreachable(),
        test_warn_when_no_ad_account_id(),
        test_warn_when_no_campaigns(),
        test_warn_when_no_creatives(),
        test_warn_when_no_recent_insights(),
        test_error_when_data_probe_returns_error(),
        test_warn_when_only_insights_unreachable(),
        test_account_id_strips_act_prefix(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
