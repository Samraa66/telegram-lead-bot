"""
Tests for app_meta KV helpers.
Run from backend/:  python -m scripts.test_app_meta
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.database import init_db, engine, _get_app_meta, _set_app_meta

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_get_missing_returns_none():
    print("\n=== Test 1: missing key returns None ===")
    init_db()
    with engine.connect() as conn:
        v = _get_app_meta(conn, "no_such_key")
    return check(f"_get_app_meta('no_such_key') is None (got {v!r})", v is None)


def test_set_then_get_roundtrip():
    print("\n=== Test 2: set then get returns the value ===")
    with engine.connect() as conn:
        _set_app_meta(conn, "k1", "hello")
        v = _get_app_meta(conn, "k1")
    return check(f"roundtrip 'hello' (got {v!r})", v == "hello")


def test_set_overwrites_existing():
    print("\n=== Test 3: set overwrites existing value ===")
    with engine.connect() as conn:
        _set_app_meta(conn, "k1", "first")
        _set_app_meta(conn, "k1", "second")
        v = _get_app_meta(conn, "k1")
    return check(f"value 'second' after overwrite (got {v!r})", v == "second")


def main():
    results = [
        test_get_missing_returns_none(),
        test_set_then_get_roundtrip(),
        test_set_overwrites_existing(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
