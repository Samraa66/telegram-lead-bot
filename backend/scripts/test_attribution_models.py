"""
Tests for CampaignInviteLink and ChannelJoinEvent schema.
Run from backend/:  python -m scripts.test_attribution_models
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import inspect
from app.database import init_db, engine, SessionLocal

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def test_invite_links_table_exists_with_required_columns():
    print("\n=== Test 1: campaign_invite_links table + columns ===")
    init_db()
    insp = inspect(engine)
    tbls = set(insp.get_table_names())
    if not check("table 'campaign_invite_links' exists", "campaign_invite_links" in tbls):
        return False
    cols = {c["name"] for c in insp.get_columns("campaign_invite_links")}
    needed = {"id", "workspace_id", "campaign_id", "source_tag", "channel_id",
              "invite_link", "invite_link_hash", "created_at", "revoked_at"}
    return check(f"all required columns present (got {sorted(cols)})", needed.issubset(cols))


def test_invite_links_unique_constraint():
    print("\n=== Test 2: campaign_invite_links unique (workspace_id, campaign_id, channel_id) ===")
    init_db()
    insp = inspect(engine)
    uqs = insp.get_unique_constraints("campaign_invite_links")
    found = any(
        set(u["column_names"]) == {"workspace_id", "campaign_id", "channel_id"}
        for u in uqs
    )
    return check(f"unique constraint present (got {uqs})", found)


def test_invite_links_index_on_hash():
    print("\n=== Test 3: campaign_invite_links has index on invite_link_hash ===")
    init_db()
    insp = inspect(engine)
    idxs = insp.get_indexes("campaign_invite_links")
    found = any("invite_link_hash" in i["column_names"] for i in idxs)
    return check(f"index on invite_link_hash present (got {idxs})", found)


def test_join_events_table_exists_with_required_columns():
    print("\n=== Test 4: channel_join_events table + columns ===")
    init_db()
    insp = inspect(engine)
    tbls = set(insp.get_table_names())
    if not check("table 'channel_join_events' exists", "channel_join_events" in tbls):
        return False
    cols = {c["name"] for c in insp.get_columns("channel_join_events")}
    needed = {"id", "workspace_id", "telegram_user_id", "channel_id", "source_tag",
              "invite_link_hash", "joined_at", "claimed_contact_id", "claimed_at"}
    return check(f"all required columns present (got {sorted(cols)})", needed.issubset(cols))


def test_join_events_index_for_user_lookup():
    print("\n=== Test 5: channel_join_events has lookup index on (workspace_id, telegram_user_id) ===")
    init_db()
    insp = inspect(engine)
    idxs = insp.get_indexes("channel_join_events")
    found = any(
        set(i["column_names"]) >= {"workspace_id", "telegram_user_id"}
        for i in idxs
    )
    return check(f"lookup index present (got {idxs})", found)


def main():
    results = [
        test_invite_links_table_exists_with_required_columns(),
        test_invite_links_unique_constraint(),
        test_invite_links_index_on_hash(),
        test_join_events_table_exists_with_required_columns(),
        test_join_events_index_for_user_lookup(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
