"""
Local pipeline test — runs entirely in-memory (SQLite).
No real DB, no Telegram, no Meta calls.

Tests:
  1. Each keyword triggers the correct stage transition
  2. Classification updates correctly at each stage
  3. Backward transitions are blocked
  4. Partial / misspelled keywords don't trigger
  5. Stage history is recorded for every transition
  6. Deposit confirmed → vip regardless of stage
  7. Full walk-through stages 1 → 8

Run from backend/:
    python -m scripts.test_pipeline
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base, Contact, StageHistory
from app.services.pipeline import advance_stage, STAGE_KEYWORDS
from app.services.classifier import classify_contact

# ---------------------------------------------------------------------------
# In-memory DB
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def fresh_contact(stage: int = 1, contact_id: int = 1):
    db = Session()
    db.query(StageHistory).filter(StageHistory.contact_id == contact_id).delete()
    db.query(Contact).filter(Contact.id == contact_id).delete()
    db.commit()
    c = Contact(
        id=contact_id,
        username="test_user",
        first_name="Test",
        last_name="Lead",
        current_stage=stage,
        classification="new_lead",
        deposit_confirmed=False,
        is_affiliate=False,
        escalated=False,
    )
    db.add(c)
    db.commit()
    return db, c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_keyword_triggers():
    print("\n=== Test 1: Each keyword triggers the correct stage ===")
    all_ok = True
    for keyword, expected_stage in STAGE_KEYWORDS:
        db, contact = fresh_contact(stage=expected_stage - 1)
        result = advance_stage(contact, keyword, db=db)
        all_ok &= check(f"'{keyword}' → stage {expected_stage} (got {result})", result == expected_stage)
        db.close()
    return all_ok


def test_classification_per_stage():
    print("\n=== Test 2: Classification updates correctly per stage ===")
    expected = {1: "new_lead", 2: "warm_lead", 3: "warm_lead", 4: "warm_lead",
                5: "warm_lead", 6: "warm_lead", 7: "vip", 8: "vip"}
    all_ok = True
    for keyword, target_stage in STAGE_KEYWORDS:
        db, contact = fresh_contact(stage=target_stage - 1)
        advance_stage(contact, keyword, db=db)
        db.refresh(contact)
        exp = expected[target_stage]
        all_ok &= check(
            f"Stage {target_stage} → '{contact.classification}' (expected '{exp}')",
            contact.classification == exp,
        )
        db.close()
    return all_ok


def test_no_backward_transitions():
    print("\n=== Test 3: Backward transitions are blocked ===")
    db, contact = fresh_contact(stage=5)
    result = advance_stage(contact, "any experience trading", db=db)  # stage-2 keyword
    ok1 = check(f"Stage-2 keyword on stage-5 contact → None (got {result})", result is None)
    db.refresh(contact)
    ok2 = check(f"Contact still at stage 5 (got {contact.current_stage})", contact.current_stage == 5)
    db.close()
    return ok1 and ok2


def test_bad_keywords():
    print("\n=== Test 4: Partial/misspelled keywords don't trigger ===")
    bad = [
        "any experience in trading",        # extra word breaks match
        "welcome to vip room",              # missing 'the'
        "really happy to have you",         # missing 'here'
        "open your free puprime account",   # missing 'your link to'
        "",                                 # empty
        "hello how are you",               # unrelated
    ]
    all_ok = True
    for i, msg in enumerate(bad):
        db, contact = fresh_contact(stage=1, contact_id=100 + i)
        result = advance_stage(contact, msg, db=db)
        all_ok &= check(f"'{msg or '(empty)'}' → no trigger (got {result})", result is None)
        db.close()
    return all_ok


def test_stage_history():
    print("\n=== Test 5: Stage history recorded on every transition ===")
    db, contact = fresh_contact(stage=1, contact_id=200)
    advance_stage(contact, "any experience trading", db=db)                          # → 2
    advance_stage(contact, "is there something specific holding you back", db=db)   # → 3

    history = (
        db.query(StageHistory)
        .filter(StageHistory.contact_id == 200)
        .order_by(StageHistory.moved_at)
        .all()
    )
    ok1 = check(f"2 history rows recorded (got {len(history)})", len(history) == 2)
    ok2 = check(
        f"Row 1: 1→2 (got {history[0].from_stage}→{history[0].to_stage})" if history else "Row 1 missing",
        len(history) >= 1 and history[0].from_stage == 1 and history[0].to_stage == 2,
    )
    ok3 = check(
        f"Row 2: 2→3 (got {history[1].from_stage}→{history[1].to_stage})" if len(history) >= 2 else "Row 2 missing",
        len(history) >= 2 and history[1].from_stage == 2 and history[1].to_stage == 3,
    )
    db.close()
    return ok1 and ok2 and ok3


def test_deposit_vip():
    print("\n=== Test 6: deposit_confirmed → vip regardless of stage ===")
    db, contact = fresh_contact(stage=3, contact_id=300)
    contact.deposit_confirmed = True
    db.commit()
    cls = classify_contact(db, contact.id, contact.source, existing=contact)
    ok = check(f"deposit_confirmed at stage 3 → 'vip' (got '{cls}')", cls == "vip")
    db.close()
    return ok


def test_full_pipeline():
    print("\n=== Test 7: Full walk-through stages 1 → 8 ===")
    db, contact = fresh_contact(stage=1, contact_id=400)
    all_ok = True
    for keyword, expected_stage in STAGE_KEYWORDS:
        result = advance_stage(contact, keyword, db=db)
        db.refresh(contact)
        all_ok &= check(
            f"Stage {expected_stage}: triggered={result == expected_stage}, classification={contact.classification}",
            result == expected_stage,
        )
    history_count = db.query(StageHistory).filter(StageHistory.contact_id == 400).count()
    all_ok &= check(f"Total history rows = 7 (got {history_count})", history_count == 7)
    db.close()
    return all_ok


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def main():
    results = [
        test_keyword_triggers(),
        test_classification_per_stage(),
        test_no_backward_transitions(),
        test_bad_keywords(),
        test_stage_history(),
        test_deposit_vip(),
        test_full_pipeline(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
