"""
Tests that backfill_workspace_history persists last_backfill_at and
last_backfill_summary on the Workspace row.

Run from backend/:  python -m scripts.test_backfill_persists_summary
"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("APP_ENV", "development")

from app.database import init_db, SessionLocal
from app.database.models import Workspace
from app.services.backfill import backfill_workspace_history

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_persists_summary_on_no_telethon():
    """
    Without a Telethon client the function returns early with an error dict.
    Even in that case it should NOT crash; we expect last_backfill_at to remain
    NULL because nothing was actually run.
    """
    print("\n=== Test 1: no Telethon -> no-op, no crash ===")
    init_db()
    result = asyncio.run(backfill_workspace_history(1))
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    db.close()
    ok1 = check(f"returned an error dict (got {result})", "error" in result)
    ok2 = check(f"last_backfill_at IS NULL (got {ws.last_backfill_at!r})", ws.last_backfill_at is None)
    return ok1 and ok2


def test_persists_summary_on_successful_run():
    """
    Stub out the Telethon client and verify last_backfill_at + summary are set.
    """
    print("\n=== Test 2: stubbed Telethon -> summary persisted ===")

    class _StubClient:
        async def iter_dialogs(self):
            for d in []:
                yield d  # never reached — empty generator

    # Monkey-patch get_client
    from app.services import telethon_client as tc
    saved = tc.get_client
    tc.get_client = lambda ws_id: _StubClient()
    try:
        result = asyncio.run(backfill_workspace_history(1))
    finally:
        tc.get_client = saved

    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    db.close()
    ok1 = check(f"result has expected keys (got {result})",
                set(result.keys()) >= {"contacts_created", "messages_replayed", "skipped"})
    ok2 = check(f"last_backfill_at is set (got {ws.last_backfill_at!r})", ws.last_backfill_at is not None)
    summary = json.loads(ws.last_backfill_summary) if ws.last_backfill_summary else {}
    ok3 = check(f"summary contacts_created=0 (got {summary.get('contacts_created')!r})",
                summary.get("contacts_created") == 0)
    return ok1 and ok2 and ok3


def main():
    results = [
        test_persists_summary_on_no_telethon(),
        test_persists_summary_on_successful_run(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
