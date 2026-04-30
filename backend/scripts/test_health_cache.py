"""
Tests for TTLCache.
Run from backend/:  python -m scripts.test_health_cache
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

from app.services.health_cache import TTLCache

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_get_missing_returns_none():
    print("\n=== Test 1: missing key returns None ===")
    c = TTLCache(ttl_seconds=60)
    return check(f"get('x') is None (got {c.get(('x',))!r})", c.get(("x",)) is None)


def test_set_then_get_roundtrip():
    print("\n=== Test 2: set then get returns the value ===")
    c = TTLCache(ttl_seconds=60)
    c.set(("k",), 42)
    return check(f"get returns 42 (got {c.get(('k',))!r})", c.get(("k",)) == 42)


def test_expiry_returns_none():
    print("\n=== Test 3: expired entry returns None ===")
    c = TTLCache(ttl_seconds=0)  # immediately stale
    c.set(("k",), 42)
    time.sleep(0.01)
    return check(f"expired get is None (got {c.get(('k',))!r})", c.get(("k",)) is None)


def test_clear_wipes_everything():
    print("\n=== Test 4: clear() removes all entries ===")
    c = TTLCache(ttl_seconds=60)
    c.set(("a",), 1); c.set(("b",), 2)
    c.clear()
    ok1 = check(f"a is None (got {c.get(('a',))!r})", c.get(("a",)) is None)
    ok2 = check(f"b is None (got {c.get(('b',))!r})", c.get(("b",)) is None)
    return ok1 and ok2


def test_overwrite():
    print("\n=== Test 5: set overwrites existing value ===")
    c = TTLCache(ttl_seconds=60)
    c.set(("k",), 1)
    c.set(("k",), 2)
    return check(f"latest value wins (got {c.get(('k',))!r})", c.get(("k",)) == 2)


def main():
    results = [
        test_get_missing_returns_none(),
        test_set_then_get_roundtrip(),
        test_expiry_returns_none(),
        test_clear_wipes_everything(),
        test_overwrite(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
