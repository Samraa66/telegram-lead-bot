"""
Tests for VIP-name promotion: the pure matcher and the side-effecting promotion helper.
Run from backend/:  python -m scripts.test_vip_name_promotion
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("APP_ENV", "development")

from app.services.pipeline import name_matches_vip_marker

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_word_boundary_matches():
    print("\n=== Test 1: word-boundary matching ===")
    markers = ["vip", "premium"]
    cases = [
        # (first, last, expected_match_or_None)
        ("Mike",       "VIP",       "vip"),
        ("VIP Mike",   None,        "vip"),
        ("Sarah",      "(VIP)",     "vip"),
        ("[VIP] Test", None,        "vip"),
        ("PREMIUM",    "Member",    "premium"),
        ("Vipul",      None,        None),
        ("vipassana",  None,        None),
        ("Mike",       "Premiummax",None),
        ("",           "",          None),
        (None,         None,        None),
    ]
    all_ok = True
    for first, last, expected in cases:
        got = name_matches_vip_marker(first, last, markers)
        all_ok &= check(
            f"({first!r}, {last!r}) -> {expected!r} (got {got!r})",
            got == expected,
        )
    return all_ok


def test_empty_markers_returns_none():
    print("\n=== Test 2: empty marker list returns None ===")
    return check(
        "empty markers -> None",
        name_matches_vip_marker("Mike VIP", None, []) is None,
    )


def test_marker_with_regex_special_chars():
    print("\n=== Test 3: markers containing regex metacharacters are escaped ===")
    markers = ["v.i.p", "$$$"]
    ok1 = check(
        "literal 'v.i.p' matches 'Mike v.i.p'",
        name_matches_vip_marker("Mike", "v.i.p", markers) == "v.i.p",
    )
    ok2 = check(
        "'v.i.p' does NOT match 'vxixp' (no regex injection)",
        name_matches_vip_marker("Mike", "vxixp", markers) is None,
    )
    return ok1 and ok2


# ---------------------------------------------------------------------------
# Side-effecting promotion helper: maybe_promote_to_member_stage
# ---------------------------------------------------------------------------

import json
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import (
    Base, Contact, Organization, Workspace, PipelineStage, StageHistory,
)
from app.services.pipeline_seed import seed_default_pipeline
from app.services.pipeline import maybe_promote_to_member_stage

# Build a dedicated engine for the side-effecting tests so we don't share
# state with the pure-function tests above.
_engine2 = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=_engine2)
_Session = sessionmaker(bind=_engine2)


def _seed_workspace(markers=None):
    db = _Session()
    if not db.query(Organization).filter(Organization.id == 1).first():
        db.add(Organization(id=1, name="T")); db.commit()
        db.add(Workspace(id=1, name="T", org_id=1, root_workspace_id=1, workspace_role="owner"))
        db.commit()
        seed_default_pipeline(1, db)
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.vip_marker_phrases = json.dumps(markers if markers is not None else ["vip", "premium"])
    db.commit()
    db.close()


def _stages_by_position():
    db = _Session()
    try:
        return {s.position: s for s in
                db.query(PipelineStage).filter(PipelineStage.workspace_id == 1).all()}
    finally:
        db.close()


def _fresh_contact(stage_id, *, contact_id=10, first_name="Mike", last_name=None):
    db = _Session()
    db.query(StageHistory).filter(StageHistory.contact_id == contact_id).delete()
    db.query(Contact).filter(Contact.id == contact_id).delete()
    db.commit()
    ps = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first() if stage_id else None
    pos = ps.position if ps else None
    c = Contact(
        id=contact_id, workspace_id=1, username="t",
        first_name=first_name, last_name=last_name,
        current_stage_id=stage_id, current_stage=pos,
        classification="new_lead", deposit_status="none",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    db.add(c); db.commit()
    return db, c


def test_promotion_from_position_1_succeeds():
    print("\n=== Test 4: lead at position 1 with VIP name -> promoted ===")
    _seed_workspace(["vip"])
    stages = _stages_by_position()
    member = next(s for s in stages.values() if s.is_member_stage)
    db, c = _fresh_contact(stages[1].id, first_name="VIP Mike")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    ok1 = check(f"promoted=True (got {promoted})", promoted is True)
    ok2 = check(f"current_stage_id={member.id} (got {c.current_stage_id})", c.current_stage_id == member.id)
    ok3 = check(f"classification='vip' (got {c.classification!r})", c.classification == "vip")
    db.close()
    return ok1 and ok2 and ok3


def test_promotion_blocked_at_higher_position():
    """
    Forward-only rule: lead whose current stage position is >= member_stage's
    position must not be promoted. Re-points member_stage to position 2 so
    positions 3-8 are "past" it for this test, then verifies a lead at
    position 5 with a VIP marker is left alone.
    """
    print("\n=== Test 5: lead past member_stage_position with VIP name -> NOT moved ===")
    stages = _stages_by_position()
    db = _Session()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    saved_member = ws.member_stage_id
    ws.member_stage_id = stages[2].id     # member at position 2
    db.commit()
    db.close()

    db, c = _fresh_contact(stages[5].id, contact_id=11, first_name="VIP Sarah")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    ok1 = check(f"promoted=False (got {promoted})", promoted is False)
    ok2 = check(
        f"current_stage_id stays {stages[5].id} (got {c.current_stage_id})",
        c.current_stage_id == stages[5].id,
    )
    db.close()

    # Restore member_stage_id for downstream tests
    db = _Session()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.member_stage_id = saved_member
    db.commit()
    db.close()
    return ok1 and ok2


def test_no_promotion_without_marker_in_name():
    print("\n=== Test 6: lead at position 1 without VIP marker -> not promoted ===")
    stages = _stages_by_position()
    db, c = _fresh_contact(stages[1].id, contact_id=12, first_name="Mike")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    ok1 = check(f"promoted=False (got {promoted})", promoted is False)
    ok2 = check(f"stage stays {stages[1].id} (got {c.current_stage_id})", c.current_stage_id == stages[1].id)
    db.close()
    return ok1 and ok2


def test_no_demotion_when_already_at_member_stage():
    print("\n=== Test 7: lead already at member_stage with VIP name -> no-op ===")
    stages = _stages_by_position()
    member = next(s for s in stages.values() if s.is_member_stage)
    db, c = _fresh_contact(member.id, contact_id=13, first_name="VIP test")
    promoted = maybe_promote_to_member_stage(c, db)
    db.refresh(c)
    history_rows = db.query(StageHistory).filter(StageHistory.contact_id == 13).count()
    ok1 = check(f"promoted=False (got {promoted})", promoted is False)
    ok2 = check(f"stage stays member ({member.id}) (got {c.current_stage_id})", c.current_stage_id == member.id)
    ok3 = check(f"no extra history row (got {history_rows})", history_rows == 0)
    db.close()
    return ok1 and ok2 and ok3


def test_writes_stage_history_with_marker():
    print("\n=== Test 8: promotion writes StageHistory with moved_by='name_marker' ===")
    stages = _stages_by_position()
    member = next(s for s in stages.values() if s.is_member_stage)
    db, c = _fresh_contact(stages[1].id, contact_id=14, first_name="VIP Trader")
    maybe_promote_to_member_stage(c, db)
    history = (db.query(StageHistory)
               .filter(StageHistory.contact_id == 14)
               .order_by(StageHistory.moved_at.desc()).first())
    ok1 = check(f"history row exists", history is not None)
    ok2 = check(f"to_stage_id={member.id} (got {history.to_stage_id})", history.to_stage_id == member.id)
    ok3 = check(f"moved_by='name_marker' (got {history.moved_by!r})", history.moved_by == "name_marker")
    ok4 = check(f"trigger_keyword='vip' (got {history.trigger_keyword!r})", history.trigger_keyword == "vip")
    db.close()
    return ok1 and ok2 and ok3 and ok4


def test_idempotent_double_call():
    print("\n=== Test 9: calling helper twice produces only one StageHistory row ===")
    stages = _stages_by_position()
    db, c = _fresh_contact(stages[1].id, contact_id=15, first_name="VIP Two")
    maybe_promote_to_member_stage(c, db)
    maybe_promote_to_member_stage(c, db)
    rows = db.query(StageHistory).filter(StageHistory.contact_id == 15).count()
    ok = check(f"history rows=1 (got {rows})", rows == 1)
    db.close()
    return ok


def test_no_member_stage_id_configured():
    print("\n=== Test 10: workspace without member_stage_id -> no-op ===")
    db = _Session()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    saved_member = ws.member_stage_id
    ws.member_stage_id = None
    db.commit()
    db.close()

    stages = _stages_by_position()
    db, c = _fresh_contact(stages[1].id, contact_id=16, first_name="VIP Foo")
    promoted = maybe_promote_to_member_stage(c, db)
    db.close()

    db = _Session()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.member_stage_id = saved_member
    db.commit()
    db.close()

    return check(f"promoted=False (got {promoted})", promoted is False)


def main():
    results = [
        test_word_boundary_matches(),
        test_empty_markers_returns_none(),
        test_marker_with_regex_special_chars(),
        test_promotion_from_position_1_succeeds(),
        test_promotion_blocked_at_higher_position(),
        test_no_promotion_without_marker_in_name(),
        test_no_demotion_when_already_at_member_stage(),
        test_writes_stage_history_with_marker(),
        test_idempotent_double_call(),
        test_no_member_stage_id_configured(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
