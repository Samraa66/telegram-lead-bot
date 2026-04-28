"""
Default pipeline template seeded for new workspaces. Users can edit/delete/reorder
stages freely after onboarding — this is a STARTING POINT only, not a fixed schema.
"""

from __future__ import annotations
import json
from typing import Optional
from sqlalchemy.orm import Session

from app.database.models import (
    PipelineStage, StageKeyword, FollowUpTemplate, QuickReply, Workspace,
)


# (position, name, color, is_deposit, is_member, end_action, revert_to_position_or_None)
DEFAULT_TEMPLATE: list[tuple[int, str, str, bool, bool, str, Optional[int]]] = [
    (1, "New Lead",             "#3b82f6", False, False, "cold",     None),
    (2, "Qualified",            "#a855f7", False, False, "cold",     None),
    (3, "Hesitant / Ghosting",  "#f59e0b", False, False, "weekly",   None),
    (4, "Link Sent",            "#06b6d4", False, False, "revert",   3),
    (5, "Account Created",      "#06b6d4", False, False, "revert",   3),
    (6, "Deposit Intent",       "#06b6d4", False, False, "revert",   3),
    (7, "Deposited",            "#10b981", True,  False, "monthly",  None),
    (8, "VIP Member",           "#10b981", False, True,  "cold",     None),
]

# (phrase, target_position)
DEFAULT_KEYWORDS: list[tuple[str, int]] = [
    ("any experience trading", 2),
    ("is there something specific holding you back", 3),
    ("your link to open your free puprime account", 4),
    ("the hard part done", 5),
    ("exactly how to get set up", 6),
    ("welcome to the vip room", 7),
    ("really happy to have you here", 8),
]

# (target_position, sequence_num, hours_offset, message_text)
DEFAULT_FOLLOWUPS: list[tuple[int, int, float, str]] = [
    (1, 1, 24,  "Hey, just checking in - happy to answer any questions!"),
    (1, 2, 72,  "Still here whenever you're ready. No pressure at all."),
    (2, 1, 24,  "Did you get a chance to think about your trading experience?"),
    (3, 1, 48,  "Hey, wanted to follow up - is there anything holding you back?"),
    (3, 2, 120, "Still thinking it over? I'm here whenever you're ready."),
    (4, 1, 6,   "Quick check - did you manage to open your PuPrime account?"),
    (4, 2, 24,  "The account only takes a few minutes - want me to walk you through it?"),
    (4, 3, 48,  "Last nudge on the account - let me know if you hit any snags."),
    (5, 1, 6,   "You're almost there - any issues with the setup?"),
    (5, 2, 24,  "Let me know if you need help finishing the setup."),
    (6, 1, 6,   "How's the setup going? Happy to answer any questions."),
    (6, 2, 24,  "Just making sure everything went smoothly - any questions?"),
    (7, 1, 1,   "Welcome again! Let me know if you need anything."),
    (7, 2, 72,  "How are you finding the VIP signals so far?"),
    (7, 3, 168, "Checking in - really happy to have you in the room!"),
]

# (target_position, label, text)
DEFAULT_QUICK_REPLIES: list[tuple[int, str, str]] = [
    (1, "Qualify",      "Hey! Quick question — do you have any experience trading, or is this something new for you? 😊"),
    (2, "Objection",    "Totally understand! Is there something specific holding you back from getting started?"),
    (3, "Re-engage",    "Hey, hope you're well — circling back. Anything I can help with?"),
    (4, "Send link",    "Here's your link to open your free PuPrime account — takes about 2 minutes! 👇"),
    (5, "Confirm done", "Amazing — looks like you've got the hard part done! 🎉 Let me know once you're in."),
    (6, "Setup guide",  "Perfect! Let me walk you through exactly how to get set up with the signals 📊"),
    (7, "VIP welcome",  "Welcome to the VIP room! You're officially in 🔥"),
    (8, "Onboard",      "Really happy to have you here — let's make sure you're getting the most out of everything!"),
]

DEFAULT_VIP_MARKERS: list[str] = ["vip", "premium"]


def seed_default_pipeline(workspace_id: int, db: Session) -> dict:
    """
    Seed a brand-new workspace with the default 8-stage template + keywords +
    follow-up templates + quick replies + VIP marker phrases. Idempotent —
    skips any layer that already has rows.

    Returns {"stage_ids": {position: id}} so callers can wire workspace pointers.
    """
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise ValueError(f"workspace {workspace_id} not found")

    pos_to_id: dict[int, int] = {}
    if db.query(PipelineStage).filter(PipelineStage.workspace_id == workspace_id).count() == 0:
        # First pass: create rows without revert_to_stage_id
        for pos, name, color, is_dep, is_mem, end_action, _revert_pos in DEFAULT_TEMPLATE:
            stage = PipelineStage(
                workspace_id=workspace_id, position=pos, name=name, color=color,
                is_deposit_stage=is_dep, is_member_stage=is_mem, end_action=end_action,
            )
            db.add(stage)
            db.flush()
            pos_to_id[pos] = stage.id
        # Second pass: wire revert_to_stage_id by position
        for pos, _name, _color, _is_dep, _is_mem, _end, revert_pos in DEFAULT_TEMPLATE:
            if revert_pos is not None:
                stage = db.query(PipelineStage).filter(
                    PipelineStage.workspace_id == workspace_id,
                    PipelineStage.position == pos,
                ).first()
                stage.revert_to_stage_id = pos_to_id[revert_pos]
        db.commit()
    else:
        for s in db.query(PipelineStage).filter(PipelineStage.workspace_id == workspace_id).all():
            pos_to_id[s.position] = s.id

    # Set workspace pointers if unset
    deposited = next((s for s in db.query(PipelineStage)
                      .filter(PipelineStage.workspace_id == workspace_id)
                      .all() if s.is_deposit_stage), None)
    member = next((s for s in db.query(PipelineStage)
                   .filter(PipelineStage.workspace_id == workspace_id)
                   .all() if s.is_member_stage), None)
    changed = False
    if deposited and not ws.deposited_stage_id:
        ws.deposited_stage_id = deposited.id; changed = True
    if member and not ws.member_stage_id:
        ws.member_stage_id = member.id; changed = True
    if not ws.vip_marker_phrases:
        ws.vip_marker_phrases = json.dumps(DEFAULT_VIP_MARKERS); changed = True
    if changed:
        db.commit()

    # Keywords — only seed if none exist
    if db.query(StageKeyword).filter(StageKeyword.workspace_id == workspace_id).count() == 0:
        for phrase, target_pos in DEFAULT_KEYWORDS:
            db.add(StageKeyword(
                workspace_id=workspace_id, keyword=phrase,
                target_stage=target_pos,                    # legacy int kept for compat
                target_stage_id=pos_to_id.get(target_pos),
                is_active=True,
            ))
        db.commit()

    # Follow-up templates
    if db.query(FollowUpTemplate).filter(FollowUpTemplate.workspace_id == workspace_id).count() == 0:
        for target_pos, seq, hours, body in DEFAULT_FOLLOWUPS:
            db.add(FollowUpTemplate(
                workspace_id=workspace_id, stage=target_pos,
                stage_id=pos_to_id.get(target_pos),
                sequence_num=seq, hours_offset=hours, message_text=body,
            ))
        db.commit()

    # Quick replies
    if db.query(QuickReply).filter(QuickReply.workspace_id == workspace_id).count() == 0:
        for i, (target_pos, label, text) in enumerate(DEFAULT_QUICK_REPLIES):
            db.add(QuickReply(
                workspace_id=workspace_id, stage_num=target_pos,
                stage_id=pos_to_id.get(target_pos),
                label=label, text=text, sort_order=i, is_active=True,
            ))
        db.commit()

    return {"stage_ids": pos_to_id}
