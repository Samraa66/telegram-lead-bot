"""
Tests for attribution.py helpers (pure functions only).
Run from backend/:  python -m scripts.test_attribution_helpers
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.attribution import _extract_hash

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_extract_hash_https_form():
    print("\n=== Test 1: https://t.me/+abc123 → 'abc123' ===")
    return check("hash matches", _extract_hash("https://t.me/+abc123") == "abc123")


def test_extract_hash_joinchat_form():
    print("\n=== Test 2: https://t.me/joinchat/abc123 → 'abc123' ===")
    return check("hash matches", _extract_hash("https://t.me/joinchat/abc123") == "abc123")


def test_extract_hash_no_scheme():
    print("\n=== Test 3: t.me/+xyz with no scheme → 'xyz' ===")
    return check("hash matches", _extract_hash("t.me/+xyz") == "xyz")


def test_extract_hash_invalid_returns_none():
    print("\n=== Test 4: garbage URL → None ===")
    return check("returns None", _extract_hash("https://example.com/foo") is None)


def test_extract_hash_empty_returns_none():
    print("\n=== Test 5: empty string → None ===")
    return check("returns None", _extract_hash("") is None)


def main():
    results = [
        test_extract_hash_https_form(),
        test_extract_hash_joinchat_form(),
        test_extract_hash_no_scheme(),
        test_extract_hash_invalid_returns_none(),
        test_extract_hash_empty_returns_none(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
