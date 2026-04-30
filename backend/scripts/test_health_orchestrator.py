"""
Tests for run_all_checks (orchestrator).
Run from backend/:  python -m scripts.test_health_orchestrator
"""
import sys, os, asyncio, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import init_db, SessionLocal
from app.database.models import Workspace

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _patch_checks(replacements: dict):
    """Replace check_* symbols on services.health with the given async callables."""
    from app.services import health
    saved = {}
    for name, fn in replacements.items():
        saved[name] = getattr(health, name)
        setattr(health, name, fn)
    return saved


def _restore(saved):
    from app.services import health
    for name, fn in saved.items():
        setattr(health, name, fn)


async def _ok(*a, **kw):
    return {"id": "x", "label": "X", "status": "ok", "detail": ""}

async def _warn(*a, **kw):
    return {"id": "x", "label": "X", "status": "warn", "detail": ""}

async def _err(*a, **kw):
    return {"id": "x", "label": "X", "status": "error", "detail": ""}

async def _none(*a, **kw):
    return None

async def _slow(*a, **kw):
    await asyncio.sleep(0.1)
    return {"id": "x", "label": "X", "status": "ok", "detail": ""}

async def _boom(*a, **kw):
    raise RuntimeError("boom")


def test_overall_healthy():
    print("\n=== Test 1: overall=healthy when every check is ok ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _ok,
        "check_operator_account": _ok,
        "check_signal_forwarding": _ok,
        "check_meta": _ok,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    return check(f"overall=healthy (got {result['overall']!r})", result["overall"] == "healthy")


def test_overall_degraded():
    print("\n=== Test 2: overall=degraded when any check is warn ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _ok,
        "check_operator_account": _warn,
        "check_signal_forwarding": _ok,
        "check_meta": _ok,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    return check(f"overall=degraded (got {result['overall']!r})", result["overall"] == "degraded")


def test_overall_critical():
    print("\n=== Test 3: overall=critical when any check is error ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _err,
        "check_operator_account": _ok,
        "check_signal_forwarding": _ok,
        "check_meta": _warn,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    return check(f"overall=critical (got {result['overall']!r})", result["overall"] == "critical")


def test_exception_in_one_check_does_not_crash_endpoint():
    print("\n=== Test 4: exception in one check yields synthetic error, others survive ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _boom,
        "check_operator_account": _ok,
        "check_signal_forwarding": _ok,
        "check_meta": _ok,
        "check_vip_channel": _none,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        result = asyncio.run(run_all_checks(ws, 1, db))
    finally:
        db.close(); _restore(saved)
    bot = next((c for c in result["checks"] if c["id"] == "bot"), None)
    ok1 = check(f"bot check has status=error (got {bot})", bot is not None and bot["status"] == "error")
    ok2 = check(f"detail mentions RuntimeError", bot is not None and "RuntimeError" in bot["detail"])
    ok3 = check(f"other checks still present (got {len(result['checks'])} total)",
                len(result["checks"]) >= 4)
    return ok1 and ok2 and ok3


def test_checks_run_in_parallel():
    print("\n=== Test 5: 5 slow checks (100ms each) finish in <300ms when parallel ===")
    init_db()
    saved = _patch_checks({
        "check_telegram_bot": _slow,
        "check_operator_account": _slow,
        "check_signal_forwarding": _slow,
        "check_meta": _slow,
        "check_vip_channel": _slow,
    })
    db = SessionLocal()
    try:
        from app.services.health import run_all_checks
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        t0 = time.monotonic()
        asyncio.run(run_all_checks(ws, 1, db))
        elapsed = time.monotonic() - t0
    finally:
        db.close(); _restore(saved)
    return check(f"elapsed < 0.3s (got {elapsed:.3f}s)", elapsed < 0.3)


def main():
    results = [
        test_overall_healthy(),
        test_overall_degraded(),
        test_overall_critical(),
        test_exception_in_one_check_does_not_crash_endpoint(),
        test_checks_run_in_parallel(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
