"""
Tests that ensure_contact's update path re-runs the VIP-name check on rename.
Run from backend/:  python -m scripts.test_ensure_contact_rename
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("APP_ENV", "development")

from app.database import init_db, SessionLocal
from app.database.models import Contact, StageHistory, Workspace
from app.services.pipeline_seed import seed_default_pipeline
from app.handlers.leads import ensure_contact

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _setup():
    init_db()
    db = SessionLocal()
    seed_default_pipeline(1, db)
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.vip_marker_phrases = json.dumps(["vip"])
    db.commit()
    db.close()


def test_rename_to_vip_promotes_existing_contact():
    print("\n=== Test 1: rename to 'VIP Mike' promotes contact at stage 1 ===")
    db = SessionLocal()
    # Create as 'Mike' first — should land at the first stage
    c = ensure_contact(db, 1001, "mike", None, "Mike", None, workspace_id=1)
    db.refresh(c)
    starting_stage_id = c.current_stage_id
    db.close()

    # Now "rename" to VIP via a second ensure_contact call
    db = SessionLocal()
    ensure_contact(db, 1001, "mike", None, "VIP Mike", None, workspace_id=1)
    c = db.query(Contact).filter(Contact.id == 1001).first()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ok1 = check(f"started at a real stage (got {starting_stage_id!r})", starting_stage_id is not None)
    ok2 = check(
        f"now at member_stage_id {ws.member_stage_id} (got {c.current_stage_id})",
        c.current_stage_id == ws.member_stage_id,
    )
    history = (db.query(StageHistory)
               .filter(StageHistory.contact_id == 1001)
               .order_by(StageHistory.moved_at.desc()).first())
    ok3 = check(
        f"history row moved_by='name_marker' (got {history.moved_by if history else None!r})",
        history is not None and history.moved_by == "name_marker",
    )
    db.close()
    return ok1 and ok2 and ok3


def test_rename_with_no_change_skips_promotion_check():
    print("\n=== Test 2: same-name re-call does not write a duplicate history row ===")
    db = SessionLocal()
    rows_before = db.query(StageHistory).filter(StageHistory.contact_id == 1001).count()
    ensure_contact(db, 1001, "mike", None, "VIP Mike", None, workspace_id=1)
    rows_after = db.query(StageHistory).filter(StageHistory.contact_id == 1001).count()
    db.close()
    return check(f"history rows unchanged ({rows_before} -> {rows_after})", rows_before == rows_after)


def test_rename_loses_marker_does_not_demote():
    print("\n=== Test 3: removing the VIP marker does NOT demote ===")
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    member_id = ws.member_stage_id
    db.close()

    # Contact 1001 is at member_stage; rename it to remove the marker
    db = SessionLocal()
    ensure_contact(db, 1001, "mike", None, "Mike", None, workspace_id=1)
    c = db.query(Contact).filter(Contact.id == 1001).first()
    db.close()
    return check(
        f"stays at member_stage {member_id} (got {c.current_stage_id})",
        c.current_stage_id == member_id,
    )


def main():
    _setup()
    results = [
        test_rename_to_vip_promotes_existing_contact(),
        test_rename_with_no_change_skips_promotion_check(),
        test_rename_loses_marker_does_not_demote(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
