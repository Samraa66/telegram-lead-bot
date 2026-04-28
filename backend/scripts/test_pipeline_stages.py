"""
Sanity tests for PipelineStage data model + default seed.
Run from backend/:  python -m scripts.test_pipeline_stages
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import (
    Base, Workspace, Organization, PipelineStage, StageKeyword, FollowUpTemplate, QuickReply,
)
from app.services.pipeline_seed import seed_default_pipeline

engine = create_engine("sqlite:///:memory:",
                       connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)

PASS = "\033[92mPASS\033[0m"; FAIL = "\033[91mFAIL\033[0m"
def check(label, cond):
    print(f"  [{PASS if cond else FAIL}] {label}")
    return cond


def test_seed():
    print("\n=== Seed default pipeline into a fresh workspace ===")
    db = Session()
    db.add(Organization(id=1, name="Test")); db.commit()
    db.add(Workspace(id=1, name="Test", org_id=1, root_workspace_id=1, workspace_role="owner"))
    db.commit()

    seed_default_pipeline(1, db)

    stages = db.query(PipelineStage).filter(PipelineStage.workspace_id == 1).order_by(PipelineStage.position).all()
    ok1 = check(f"8 stages seeded (got {len(stages)})", len(stages) == 8)
    ok2 = check("position 7 is deposit_stage", stages[6].is_deposit_stage and not stages[6].is_member_stage)
    ok3 = check("position 8 is member_stage", stages[7].is_member_stage and not stages[7].is_deposit_stage)
    ok4 = check("position 4 reverts to position 3", stages[3].revert_to_stage_id == stages[2].id)

    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ok5 = check("ws.deposited_stage_id set", ws.deposited_stage_id == stages[6].id)
    ok6 = check("ws.member_stage_id set", ws.member_stage_id == stages[7].id)
    ok7 = check("vip_marker_phrases seeded", ws.vip_marker_phrases and "vip" in ws.vip_marker_phrases)

    kw = db.query(StageKeyword).filter(StageKeyword.workspace_id == 1).all()
    ok8 = check(f"7 default keywords seeded (got {len(kw)})", len(kw) == 7)
    ok9 = check("each keyword has a target_stage_id", all(k.target_stage_id is not None for k in kw))

    fut = db.query(FollowUpTemplate).filter(FollowUpTemplate.workspace_id == 1).all()
    ok10 = check(f"15 follow-up templates seeded (got {len(fut)})", len(fut) == 15)

    qr = db.query(QuickReply).filter(QuickReply.workspace_id == 1).all()
    ok11 = check(f"8 quick replies seeded (got {len(qr)})", len(qr) == 8)

    db.close()
    return all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9, ok10, ok11])


def test_idempotent():
    print("\n=== Re-seeding the same workspace is a no-op ===")
    db = Session()
    seed_default_pipeline(1, db)  # second call
    stages = db.query(PipelineStage).filter(PipelineStage.workspace_id == 1).count()
    ok = check(f"still 8 stages after re-seed (got {stages})", stages == 8)
    db.close()
    return ok


def main():
    results = [test_seed(), test_idempotent()]
    print(f"\n{'='*45}\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
