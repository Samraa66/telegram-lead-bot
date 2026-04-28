"""
End-to-end tests for /auth/signup/organization and /auth/affiliate-invites.
Run from backend/:  python -m scripts.test_signup
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ.setdefault("APP_ENV", "development")

from fastapi.testclient import TestClient
from app.database import init_db
init_db()
from app.main import app

PASS = "\033[92mPASS\033[0m"; FAIL = "\033[91mFAIL\033[0m"
def check(label, cond):
    print(f"  [{PASS if cond else FAIL}] {label}")
    return cond


client = TestClient(app)


def test_org_signup():
    print("\n=== Org signup creates workspace + account ===")
    r = client.post("/auth/signup/organization", json={
        "full_name": "Sam Tester", "email": "sam@test.com", "password": "verysecret1",
        "org_name": "TestCo", "niche": "Trading",
    })
    ok1 = check(f"201 (got {r.status_code})", r.status_code == 201)
    data = r.json() if r.status_code == 201 else {}
    ok2 = check("got access_token", bool(data.get("access_token")))
    ok3 = check("role=admin", data.get("role") == "admin")
    ok4 = check("org_role=org_owner", data.get("org_role") == "org_owner")
    ok5 = check("onboarding_complete=False", data.get("onboarding_complete") is False)
    ok6 = check("account_id present", bool(data.get("account_id")))
    return all([ok1, ok2, ok3, ok4, ok5, ok6])


def test_org_signup_duplicate_email():
    print("\n=== Duplicate email rejected with 409 ===")
    r = client.post("/auth/signup/organization", json={
        "full_name": "Sam Two", "email": "sam@test.com", "password": "verysecret1",
        "org_name": "TestCo2",
    })
    return check(f"409 (got {r.status_code})", r.status_code == 409)


def test_invite_flow():
    print("\n=== Issue invite, accept, log in as affiliate ===")
    r = client.post("/auth/login", json={"username": "sam@test.com", "password": "verysecret1"})
    ok0 = check(f"login ok ({r.status_code})", r.status_code == 200)
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}

    r2 = client.post("/auth/affiliate-invites", headers=H, json={"email": "alice@x.com"})
    ok1 = check(f"invite issue 201 (got {r2.status_code})", r2.status_code == 201)
    invite_token = r2.json()["invite_token"] if r2.status_code == 201 else ""

    r3 = client.get(f"/auth/affiliate-invites/{invite_token}")
    ok2 = check(f"lookup 200 (got {r3.status_code})", r3.status_code == 200)

    r4 = client.post(f"/auth/affiliate-invites/{invite_token}/accept", json={
        "full_name": "Alice", "email": "alice@x.com", "password": "alicepw99",
    })
    ok3 = check(f"accept 200 (got {r4.status_code})", r4.status_code == 200)
    body = r4.json() if r4.status_code == 200 else {}
    ok4 = check("affiliate access_token returned",
                bool(body.get("access_token")) and body.get("role") == "affiliate")
    ok5 = check("affiliate org_role=workspace_owner", body.get("org_role") == "workspace_owner")
    ok6 = check("affiliate onboarding_complete=False", body.get("onboarding_complete") is False)

    r5 = client.get(f"/auth/affiliate-invites/{invite_token}")
    ok7 = check(f"lookup after accept 404 (got {r5.status_code})", r5.status_code == 404)

    # Affiliate can log in
    r6 = client.post("/auth/login", json={"username": "alice@x.com", "password": "alicepw99"})
    ok8 = check(f"affiliate login 200 (got {r6.status_code})", r6.status_code == 200)
    return all([ok0, ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8])


def test_invite_expired():
    print("\n=== Expired invite returns 410 ===")
    r = client.post("/auth/login", json={"username": "sam@test.com", "password": "verysecret1"})
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r2 = client.post("/auth/affiliate-invites", headers=H, json={"expires_in_days": 0})
    invite_token = r2.json()["invite_token"]
    # Force expiry by 1 second in the DB
    from datetime import datetime, timedelta
    from app.database import SessionLocal
    from app.database.models import AffiliateInvite
    db = SessionLocal()
    inv = db.query(AffiliateInvite).filter(AffiliateInvite.invite_token == invite_token).first()
    inv.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit(); db.close()
    r3 = client.get(f"/auth/affiliate-invites/{invite_token}")
    return check(f"410 on expired (got {r3.status_code})", r3.status_code == 410)


def main():
    results = [
        test_org_signup(),
        test_org_signup_duplicate_email(),
        test_invite_flow(),
        test_invite_expired(),
    ]
    print(f"\n{'='*45}\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
