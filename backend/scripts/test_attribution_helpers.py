"""
Tests for attribution.py helpers (pure functions only).
Run from backend/:  python -m scripts.test_attribution_helpers
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.attribution import _extract_hash
from app.database.models import Workspace

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


def _make_ws(*, main_url=None, attribution_channel_id=None):
    return Workspace(
        id=1, name="t",
        main_channel_url=main_url,
        attribution_channel_id=attribution_channel_id,
    )


class _MockClient:
    """Stand-in for Telethon. Returns canned entities or raises configured exceptions."""
    def __init__(self, *, entity_id=None, raises=None):
        self._entity_id = entity_id
        self._raises = raises

    async def get_entity(self, url):
        if self._raises:
            raise self._raises
        if self._entity_id is None:
            raise ValueError("no canned entity")
        return type("E", (), {"id": self._entity_id})()


def test_resolve_returns_cached_when_set():
    print("\n=== Test 6: resolve returns Workspace.attribution_channel_id when already set ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    ws = _make_ws(main_url="t.me/+abc", attribution_channel_id=-1009999)
    got = asyncio.run(resolve_attribution_channel(ws, db=None, client=_MockClient()))
    return check(f"returns -1009999 (got {got!r})", got == -1009999)


def test_resolve_uses_telethon_when_unset():
    print("\n=== Test 7: resolve calls Telethon and writes attribution_channel_id ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    from app.database import init_db, SessionLocal
    init_db()
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        ws.main_channel_url = "https://t.me/+abc123"
        ws.attribution_channel_id = None
        db.commit()
        got = asyncio.run(resolve_attribution_channel(ws, db=db, client=_MockClient(entity_id=-1001)))
        ok1 = check(f"returns -1001 (got {got!r})", got == -1001)
        db.refresh(ws)
        ok2 = check(f"persisted on workspace (got {ws.attribution_channel_id!r})", ws.attribution_channel_id == -1001)
        return ok1 and ok2
    finally:
        db.close()


def test_resolve_returns_none_on_missing_url():
    print("\n=== Test 8: resolve returns None when main_channel_url is empty ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    ws = _make_ws(main_url=None, attribution_channel_id=None)
    got = asyncio.run(resolve_attribution_channel(ws, db=None, client=_MockClient()))
    return check(f"returns None (got {got!r})", got is None)


def test_resolve_returns_none_on_telethon_failure():
    print("\n=== Test 9: resolve returns None when Telethon raises ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    ws = _make_ws(main_url="t.me/+abc", attribution_channel_id=None)
    got = asyncio.run(resolve_attribution_channel(ws, db=None, client=_MockClient(raises=ValueError("nope"))))
    return check(f"returns None (got {got!r})", got is None)


def test_resolve_returns_none_when_client_is_none():
    print("\n=== Test 10: resolve returns None when client arg is None ===")
    import asyncio
    from app.services.attribution import resolve_attribution_channel
    ws = _make_ws(main_url="t.me/+abc", attribution_channel_id=None)
    got = asyncio.run(resolve_attribution_channel(ws, db=None, client=None))
    return check(f"returns None (got {got!r})", got is None)


def main():
    results = [
        test_extract_hash_https_form(),
        test_extract_hash_joinchat_form(),
        test_extract_hash_no_scheme(),
        test_extract_hash_invalid_returns_none(),
        test_extract_hash_empty_returns_none(),
        test_resolve_returns_cached_when_set(),
        test_resolve_uses_telethon_when_unset(),
        test_resolve_returns_none_on_missing_url(),
        test_resolve_returns_none_on_telethon_failure(),
        test_resolve_returns_none_when_client_is_none(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
