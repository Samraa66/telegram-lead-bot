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
                     referral_tag="affa", vip_channel_id="-100AAA", is_active=True))
    db.add(Affiliate(id=11, name="AffB", workspace_id=1, affiliate_workspace_id=3,
                     referral_tag="affb", vip_channel_id="-100BBB", is_active=True))
    db.add(Affiliate(id=12, name="AffC", workspace_id=4, affiliate_workspace_id=5,
                     referral_tag="affc", vip_channel_id="-100CCC", is_active=True))
    db.commit()
    return {"orgA_root": 1, "orgB_root": 4}


if __name__ == "__main__":
    from app.services.forwarding import get_destinations_for_org

    db = Session()
    ids = make_org_tree(db)

    # OrgA's destinations = AffA + AffB (workspaces 2, 3)
    print("Test 1: get_destinations_for_org returns own org's affiliates")
    dests_a = sorted(get_destinations_for_org(ids["orgA_root"], db))
    check("OrgA destinations match [-100AAA, -100BBB]", dests_a == ["-100AAA", "-100BBB"])

    # OrgB's destinations = AffC only (workspace 5)
    print("\nTest 2: orgs are isolated")
    dests_b = get_destinations_for_org(ids["orgB_root"], db)
    check("OrgB destinations match ['-100CCC']", dests_b == ["-100CCC"])

    # Inactive affiliate is excluded
    print("\nTest 3: inactive affiliates excluded")
    aff_a = db.query(Affiliate).filter(Affiliate.id == 10).first()
    aff_a.is_active = False
    db.commit()
    dests_a2 = get_destinations_for_org(ids["orgA_root"], db)
    check("OrgA now has only AffB", dests_a2 == ["-100BBB"])
    aff_a.is_active = True  # reset
    db.commit()

    # NULL vip_channel_id excluded
    print("\nTest 4: affiliates without vip_channel_id excluded")
    aff_b = db.query(Affiliate).filter(Affiliate.id == 11).first()
    aff_b.vip_channel_id = None
    db.commit()
    dests_a3 = get_destinations_for_org(ids["orgA_root"], db)
    check("OrgA now has only AffA", dests_a3 == ["-100AAA"])
    aff_b.vip_channel_id = "-100BBB"  # reset
    db.commit()

    # Org with no affiliates returns empty list
    print("\nTest 5: empty list when no affiliates")
    db.add(Organization(id=3, name="OrgEmpty"))
    db.add(Workspace(id=6, name="OrgEmpty-root", org_id=3, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=6))
    db.commit()
    check("OrgEmpty destinations are []", get_destinations_for_org(6, db) == [])

    print("\nTest 6: copy_message returns False when bot_token is empty")
    from app.services.forwarding import copy_message
    result = copy_message("-100SRC", 42, "-100DST", bot_token="")
    check("empty bot_token → False", result is False)

    print("\nTest 7: copy_message uses the bot_token in URL")
    captured_url = {"value": None}
    def fake_post(url, json=None, timeout=None):
        captured_url["value"] = url
        resp = MagicMock()
        resp.status_code = 200
        return resp
    with patch("app.services.forwarding.requests.post", side_effect=fake_post):
        ok = copy_message("-100SRC", 42, "-100DST", bot_token="my-token-XYZ")
    check("returns True on 200", ok is True)
    check("URL contains the bot_token", "my-token-XYZ" in (captured_url["value"] or ""))

    print("\nTest 8: copy_signal_for_org skips when bot_token is NULL")
    from app.services.forwarding import copy_signal_for_org
    db.add(Workspace(id=7, name="NoBot", org_id=1, workspace_role="owner",
                     root_workspace_id=7, source_channel_id="-100777", bot_token=None))
    db.commit()
    with patch("app.services.forwarding.requests.post") as mock_post:
        copy_signal_for_org(7, "-100777", 42, db)
        check("requests.post not called", mock_post.call_count == 0)

    print("\nTest 9: copy_signal_for_org loops all destinations using workspace's bot")
    captured_calls = []
    def fake_post_orgA(url, json=None, timeout=None):
        captured_calls.append((url, json["chat_id"]))
        resp = MagicMock()
        resp.status_code = 200
        return resp
    with patch("app.services.forwarding.requests.post", side_effect=fake_post_orgA):
        copy_signal_for_org(ids["orgA_root"], "-1001111", 99, db)
    check("posted to 2 destinations (AffA + AffB)", len(captured_calls) == 2)
    check("uses OrgA's bot token in URL", all("botA-token" in u for u, _ in captured_calls))
    captured_chat_ids = sorted([c for _, c in captured_calls])
    check("destinations are AffA + AffB channels",
          captured_chat_ids == ["-100AAA", "-100BBB"])

    print("\nTest 10: per-channel failure does not abort the loop")
    call_log = []
    def fake_post_partial_fail(url, json=None, timeout=None):
        call_log.append(json["chat_id"])
        resp = MagicMock()
        resp.status_code = 400 if json["chat_id"] == "-100AAA" else 200
        resp.text = "{}"
        return resp
    with patch("app.services.forwarding.requests.post", side_effect=fake_post_partial_fail):
        copy_signal_for_org(ids["orgA_root"], "-1001111", 100, db)
    check("both destinations attempted despite first failure", len(call_log) == 2)

    db.close()
    print("\nDone.")
