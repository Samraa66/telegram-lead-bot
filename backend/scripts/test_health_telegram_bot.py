"""
Tests for check_telegram_bot.
Run from backend/:  python -m scripts.test_health_telegram_bot
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_BASE_URL", "https://test.example.com")

from datetime import datetime, timedelta
from app.database.models import Workspace
from app.services.health_cache import _probe_cache
from scripts.test_health_mocks import MockHttpClient

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _ws(bot_token="test_token"):
    ws = Workspace(id=42, name="t", bot_token=bot_token)
    return ws


def _expected(ws_id):
    return f"https://test.example.com/webhook/{ws_id}"


def test_ok_when_url_matches_no_errors():
    print("\n=== Test 1: ok when URL matches and no errors ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": _expected(42), "pending_update_count": 0}
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    return check(f"status=ok (got {result!r})", result["status"] == "ok")


def test_warn_url_mismatch():
    print("\n=== Test 2: warn when webhook URL doesn't match expected ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": "https://wrong.example.com/webhook/1", "pending_update_count": 0}
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions 'wrong'", "wrong.example.com" in result["detail"])
    return ok1 and ok2


def test_warn_pending_backlog():
    print("\n=== Test 3: warn when pending_update_count > 100 ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": _expected(42), "pending_update_count": 250}
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions queue/backlog", "250" in result["detail"] or "queue" in result["detail"].lower())
    return ok1 and ok2


def test_warn_recent_delivery_error():
    print("\n=== Test 4: warn when last_error_date is recent ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    recent_ts = int((datetime.utcnow() - timedelta(minutes=10)).timestamp())
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {
                "url": _expected(42),
                "pending_update_count": 0,
                "last_error_date": recent_ts,
                "last_error_message": "500 Internal Server Error",
            }
        }),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(f"detail mentions error", "500" in result["detail"] or "error" in result["detail"].lower())
    return ok1 and ok2


def test_error_when_no_token():
    print("\n=== Test 5: error when no bot_token ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws(bot_token=None)
    http = MockHttpClient({})
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    return check(f"status=error (got {result['status']!r})", result["status"] == "error")


def test_warn_on_network_failure():
    print("\n=== Test 6: warn (not 'webhook not registered') when Telegram unreachable ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, "TIMEOUT"),
    })
    result = asyncio.run(check_telegram_bot(ws, 42, http))
    ok1 = check(f"status=warn (got {result['status']!r})", result["status"] == "warn")
    ok2 = check(
        f"detail says 'could not reach' (got {result['detail']!r})",
        "could not reach" in result["detail"].lower() or "unreachable" in result["detail"].lower(),
    )
    return ok1 and ok2


def test_cache_hit_skips_second_call():
    print("\n=== Test 7: second call within TTL doesn't re-hit Telegram ===")
    _probe_cache.clear()
    from app.services.health import check_telegram_bot
    ws = _ws()
    http = MockHttpClient({
        f"https://api.telegram.org/bot{ws.bot_token}/getWebhookInfo": (200, {
            "result": {"url": _expected(42), "pending_update_count": 0}
        }),
    })
    asyncio.run(check_telegram_bot(ws, 42, http))
    asyncio.run(check_telegram_bot(ws, 42, http))
    return check(f"only 1 HTTP call made (got {len(http.calls)})", len(http.calls) == 1)


def main():
    results = [
        test_ok_when_url_matches_no_errors(),
        test_warn_url_mismatch(),
        test_warn_pending_backlog(),
        test_warn_recent_delivery_error(),
        test_error_when_no_token(),
        test_warn_on_network_failure(),
        test_cache_hit_skips_second_call(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
