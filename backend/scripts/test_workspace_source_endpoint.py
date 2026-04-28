"""
Test PATCH /workspace/me/source-channel — writes source_channel_id and
cycles the Telethon client.

Run from backend/:
    python -m scripts.test_workspace_source_endpoint
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DEVELOPER_USERNAME"] = "dev"
os.environ["DEVELOPER_PASSWORD"] = "devpw"
os.environ["APP_ENV"] = "development"  # use dev fallback encryption key

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base, Workspace, Organization
from app.main import app
from app import database as db_module
from app.auth import create_access_token

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label, condition):
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


# Swap real engine for in-memory
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
TestSession = sessionmaker(bind=engine)
db_module.SessionLocal = TestSession  # type: ignore

# Seed
with TestSession() as db:
    db.add(Organization(id=1, name="OrgOne"))
    db.add(Workspace(id=10, name="OrgOne-root", org_id=1, workspace_role="owner",
                     parent_workspace_id=None, root_workspace_id=10,
                     bot_token="botA"))
    db.commit()

# Token for workspace owner of ws 10
token = create_access_token(
    username="owner10",
    role="affiliate",
    workspace_id=10,
    org_id=1,
    org_role="workspace_owner",
)

client = TestClient(app)

print("Test 1: PATCH writes source_channel_id and cycles Telethon")
cycle_calls = []
async def fake_stop(ws_id):
    cycle_calls.append(("stop", ws_id))
async def fake_start(ws_id, *args, **kwargs):
    cycle_calls.append(("start", ws_id))

with patch("app.services.telethon_client.stop_workspace_client", side_effect=fake_stop), \
     patch("app.services.telethon_client.start_workspace_client", side_effect=fake_start):
    resp = client.patch(
        "/workspace/me/source-channel",
        json={"source_channel_id": "-1003333"},
        headers={"Authorization": f"Bearer {token}"},
    )

check("status 200", resp.status_code == 200)

with TestSession() as db:
    ws = db.query(Workspace).filter(Workspace.id == 10).first()
    check("DB row updated", ws.source_channel_id == "-1003333")

# Note: the cycle only runs if ws.telethon_session is set; here it's None,
# so cycle calls are NOT expected in this case. The endpoint must still return 200.
check("endpoint returns ok=True", resp.json().get("ok") is True)
check("response includes source_channel_id", resp.json().get("source_channel_id") == "-1003333")

print("\nTest 2: PATCH triggers Telethon cycle when telethon_session is set")
with TestSession() as db:
    ws = db.query(Workspace).filter(Workspace.id == 10).first()
    ws.telethon_session = "fake-session-string"
    db.commit()

cycle_calls.clear()
with patch("app.services.telethon_client.stop_workspace_client", side_effect=fake_stop), \
     patch("app.services.telethon_client.start_workspace_client", side_effect=fake_start):
    resp = client.patch(
        "/workspace/me/source-channel",
        json={"source_channel_id": "-1004444"},
        headers={"Authorization": f"Bearer {token}"},
    )

check("status 200 with session", resp.status_code == 200)
check("stop_workspace_client called", any(c[0] == "stop" for c in cycle_calls))
check("start_workspace_client called", any(c[0] == "start" for c in cycle_calls))

print("\nTest 3: rejects non-workspace-owner")
aff_token = create_access_token(
    username="aff",
    role="affiliate",
    workspace_id=11,
    org_id=1,
    org_role="affiliate",
)
resp = client.patch(
    "/workspace/me/source-channel",
    json={"source_channel_id": "-100ZZZZ"},
    headers={"Authorization": f"Bearer {aff_token}"},
)
check("non-owner gets 403", resp.status_code == 403)

print("\nDone.")
