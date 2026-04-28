"""
Local forwarding test — runs in-memory (SQLite). No Telegram, no real bot.

Tests:
  1. get_destinations_for_org returns affiliates from the right org tree only
  2. copy_message takes bot_token as an explicit arg
  3. copy_signal_for_org skips when bot_token is NULL
  4. copy_signal_for_org loops all destinations and continues on per-channel failure

Run from backend/:
    python -m scripts.test_forwarding
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base, Workspace, Affiliate, Organization

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label, condition):
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


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


def make_org_tree(db):
    """
    Build a two-org tree:
      Org 1: workspace 1 (owner) → workspaces 2, 3 (affiliates A, B)
      Org 2: workspace 4 (owner) → workspaces 5 (affiliate C)
    Returns dict of names → workspace ids.
    """
    db.add(Organization(id=1, name="OrgOne"))
    db.add(Organization(id=2, name="OrgTwo"))

    db.add(Workspace(id=1, name="OrgOne-root", org_id=1, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=1,
                     bot_token="botA-token", source_channel_id="-1001111"))
    db.add(Workspace(id=2, name="OrgOne-AffA", org_id=1, workspace_role="affiliate",
                     parent_workspace_id=1, root_workspace_id=1))
    db.add(Workspace(id=3, name="OrgOne-AffB", org_id=1, workspace_role="affiliate",
                     parent_workspace_id=1, root_workspace_id=1))
    db.add(Workspace(id=4, name="OrgTwo-root", org_id=2, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=4,
                     bot_token="botB-token", source_channel_id="-1002222"))
    db.add(Workspace(id=5, name="OrgTwo-AffC", org_id=2, workspace_role="affiliate",
                     parent_workspace_id=4, root_workspace_id=4))

    # Affiliate rows tied to the affiliate workspaces
    db.add(Affiliate(id=10, name="AffA", workspace_id=1, affiliate_workspace_id=2,
                     vip_channel_id="-100AAA", is_active=True))
    db.add(Affiliate(id=11, name="AffB", workspace_id=1, affiliate_workspace_id=3,
                     vip_channel_id="-100BBB", is_active=True))
    db.add(Affiliate(id=12, name="AffC", workspace_id=4, affiliate_workspace_id=5,
                     vip_channel_id="-100CCC", is_active=True))
    db.commit()
    return {"orgA_root": 1, "orgB_root": 4}


if __name__ == "__main__":
    print("Forwarding tests")
    print("(no assertions yet — fixtures only)")
