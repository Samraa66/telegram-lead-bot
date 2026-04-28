"""
Local pipeline test — runs entirely in-memory (SQLite).
No real DB, no Telegram, no Meta calls.

Tests the stage_id-based pipeline:
  1. Each seeded keyword triggers the correct stage transition
  2. Classification updates correctly at each stage
  3. Backward transitions are blocked
  4. Partial / misspelled keywords don't trigger
  5. Stage history is recorded for every transition
  6. deposit_status='deposited' → vip regardless of stage
  7. Full walk-through positions 1 → 8

Run from backend/:
    python -m scripts.test_pipeline
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import (
    Base, Contact, Organization, Workspace, PipelineStage, StageKeyword,
    StageHistory,
)
from app.services.pipeline_seed import seed_default_pipeline
from app.services.pipeline import advance_stage
from app.services.classifier import classify_contact

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)


def _seed():
    db = Session()
    if not db.query(Organization).filter(Organization.id == 1).first():
        db.add(Organization(id=1, name="T")); db.commit()
        db.add(Workspace(id=1, name="T", org_id=1, root_workspace_id=1, workspace_role="owner"))
        db.commit()
        seed_default_pipeline(1, db)
    db.close()


_seed()

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _stages_by_position():
    db = Session()
    try:
        return {s.position: s for s in
                db.query(PipelineStage).filter(PipelineStage.workspace_id == 1).all()}
    finally:
        db.close()


def _keyword_pairs():
    """Return [(phrase, target_stage_id, target_position), ...] for default seeds."""
    db = Session()
    try:
        kw = (db.query(StageKeyword)
              .filter(StageKeyword.workspace_id == 1, StageKeyword.is_active.is_(True))
              .all())
        out = []
        for k in kw:
            ps = db.query(PipelineStage).filter(PipelineStage.id == k.target_stage_id).first()
            if ps:
                out.append((k.keyword, k.target_stage_id, ps.position))
        out.sort(key=lambda r: r[2])
        return out
    finally:
        db.close()


def _fresh_contact(stage_id: int, contact_id: int = 1):
    db = Session()
    db.query(StageHistory).filter(StageHistory.contact_id == contact_id).delete()
    db.query(Contact).filter(Contact.id == contact_id).delete()
    db.commit()
    # Resolve the position so we can mirror it into the legacy current_stage int field.
    ps = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
    stage_pos = ps.position if ps else 1
    c = Contact(
        id=contact_id, workspace_id=1, username="test_user",
        first_name="Test", last_name="Lead",
        current_stage_id=stage_id, current_stage=stage_pos,
        classification="new_lead",
        deposit_status="none",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    db.add(c); db.commit()
    return db, c


def test_keyword_triggers():
    print("\n=== Test 1: Each keyword triggers the correct stage ===")
    stages = _stages_by_position()
    pairs = _keyword_pairs()
    all_ok = True
    for phrase, target_stage_id, target_pos in pairs:
        prev_pos = target_pos - 1
        prev_stage = stages.get(prev_pos)
        if not prev_stage:
            continue
        db, contact = _fresh_contact(stage_id=prev_stage.id)
        result = advance_stage(contact, phrase, db=db)
        all_ok &= check(
            f"'{phrase}' → stage_id {target_stage_id} (pos {target_pos}, got {result})",
            result == target_stage_id,
        )
        db.close()
    return all_ok


def test_classification_per_stage():
    print("\n=== Test 2: Classification updates correctly per stage ===")
    stages = _stages_by_position()
    pairs = _keyword_pairs()
    all_ok = True
    for phrase, target_stage_id, target_pos in pairs:
        prev_stage = stages.get(target_pos - 1)
        if not prev_stage:
            continue
        db, contact = _fresh_contact(stage_id=prev_stage.id)
        advance_stage(contact, phrase, db=db)
        db.refresh(contact)
        target = stages[target_pos]
        if target.is_member_stage or contact.deposit_status == "deposited":
            expected = "vip"
        elif target_pos >= 2:
            expected = "warm_lead"
        else:
            expected = "new_lead"
        all_ok &= check(
            f"position {target_pos} → '{contact.classification}' (expected '{expected}')",
            contact.classification == expected,
        )
        db.close()
    return all_ok


def test_no_backward_transitions():
    print("\n=== Test 3: Backward transitions are blocked ===")
    stages = _stages_by_position()
    pairs = _keyword_pairs()
    qualify_phrase = next((p for p, _, pos in pairs if pos == 2), None)
    db, contact = _fresh_contact(stage_id=stages[5].id)
    result = advance_stage(contact, qualify_phrase, db=db)
    ok1 = check(f"position-2 keyword on position-5 contact → None (got {result})", result is None)
    db.refresh(contact)
    ok2 = check(
        f"contact still at position 5 (got {contact.current_stage})",
        contact.current_stage == 5,
    )
    db.close()
    return ok1 and ok2


def test_bad_keywords():
    print("\n=== Test 4: Partial/misspelled keywords don't trigger ===")
    stages = _stages_by_position()
    bad = [
        "any experience in trading",
        "welcome to vip room",
        "really happy to have you",
        "open your free puprime account",
        "",
        "hello how are you",
    ]
    all_ok = True
    for i, msg in enumerate(bad):
        db, contact = _fresh_contact(stage_id=stages[1].id, contact_id=100 + i)
        result = advance_stage(contact, msg, db=db)
        all_ok &= check(f"'{msg or '(empty)'}' → no trigger (got {result})", result is None)
        db.close()
    return all_ok


def test_stage_history():
    print("\n=== Test 5: Stage history recorded on every transition ===")
    stages = _stages_by_position()
    pairs = _keyword_pairs()
    p2 = next((p for p, _, pos in pairs if pos == 2), None)
    p3 = next((p for p, _, pos in pairs if pos == 3), None)
    db, contact = _fresh_contact(stage_id=stages[1].id, contact_id=200)
    advance_stage(contact, p2, db=db)
    advance_stage(contact, p3, db=db)
    history = (
        db.query(StageHistory)
        .filter(StageHistory.contact_id == 200)
        .order_by(StageHistory.moved_at)
        .all()
    )
    ok1 = check(f"2 history rows recorded (got {len(history)})", len(history) == 2)
    ok2 = check(
        f"row 1 to_stage_id={stages[2].id} (got {history[0].to_stage_id})" if history else "no row 1",
        len(history) >= 1 and history[0].to_stage_id == stages[2].id,
    )
    ok3 = check(
        f"row 2 to_stage_id={stages[3].id} (got {history[1].to_stage_id})" if len(history) >= 2 else "no row 2",
        len(history) >= 2 and history[1].to_stage_id == stages[3].id,
    )
    db.close()
    return ok1 and ok2 and ok3


def test_deposit_status_vip():
    print("\n=== Test 6: deposit_status='deposited' → vip ===")
    stages = _stages_by_position()
    db, contact = _fresh_contact(stage_id=stages[3].id, contact_id=300)
    contact.deposit_status = "deposited"
    db.commit()
    cls = classify_contact(db, contact.id, contact.source, existing=contact)
    ok = check(f"deposit_status='deposited' at position 3 → 'vip' (got '{cls}')", cls == "vip")
    db.close()
    return ok


def test_full_pipeline():
    print("\n=== Test 7: Full walk-through positions 1 → 8 ===")
    stages = _stages_by_position()
    pairs = _keyword_pairs()
    db, contact = _fresh_contact(stage_id=stages[1].id, contact_id=400)
    all_ok = True
    for phrase, target_stage_id, target_pos in pairs:
        result = advance_stage(contact, phrase, db=db)
        db.refresh(contact)
        all_ok &= check(
            f"position {target_pos}: triggered={result == target_stage_id}, classification={contact.classification}",
            result == target_stage_id,
        )
    history_count = db.query(StageHistory).filter(StageHistory.contact_id == 400).count()
    all_ok &= check(f"total history rows = {len(pairs)} (got {history_count})", history_count == len(pairs))
    db.close()
    return all_ok


def main():
    results = [
        test_keyword_triggers(),
        test_classification_per_stage(),
        test_no_backward_transitions(),
        test_bad_keywords(),
        test_stage_history(),
        test_deposit_status_vip(),
        test_full_pipeline(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
