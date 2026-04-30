"""
Tests for GET /attribution/invite.
Run from backend/:  python -m scripts.test_attribution_endpoint
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from app.database import init_db, SessionLocal
from app.database.models import Campaign, CampaignInviteLink, Workspace

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def _setup_ws(*, landing_url="https://lp.example.com",
              attribution_channel_id=-1001):
    init_db()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ws.landing_page_url = landing_url
    ws.main_channel_url = "https://t.me/+publicchan"
    ws.attribution_channel_id = attribution_channel_id
    db.commit()
    db.close()


def _ensure_campaign(*, source_tag, is_active=True):
    db = SessionLocal()
    try:
        c = db.query(Campaign).filter(Campaign.source_tag == source_tag).first()
        if c is None:
            c = Campaign(source_tag=source_tag, name=source_tag, is_active=is_active)
            db.add(c); db.commit(); db.refresh(c)
        else:
            c.is_active = is_active
            db.commit()
        return c.id
    finally:
        db.close()


def _patch_attribution(routes):
    """
    Monkey-patch app.services.attribution.{resolve_attribution_channel,
    mint_invite_link} with stubs returning the given fixtures.
    """
    from app.services import attribution as attr
    saved = (attr.resolve_attribution_channel, attr.mint_invite_link)

    async def fake_resolve(ws, db, client):
        return routes.get("resolve")

    async def fake_mint(ws, campaign, db, client, *, channel_id):
        result = routes.get("mint")
        if isinstance(result, Exception):
            raise result
        return result

    attr.resolve_attribution_channel = fake_resolve
    attr.mint_invite_link = fake_mint
    return saved


def _restore_attribution(saved):
    from app.services import attribution as attr
    attr.resolve_attribution_channel, attr.mint_invite_link = saved


def _client():
    from app.main import app
    return TestClient(app)


def _stub_link(url):
    """Construct a fake CampaignInviteLink-shaped object for the stub mint."""
    from app.database.models import CampaignInviteLink
    row = CampaignInviteLink(
        workspace_id=1, campaign_id=999, source_tag="x", channel_id=-1001,
        invite_link=url, invite_link_hash="x",
    )
    return row


def test_403_when_origin_not_allowed():
    print("\n=== Test 1: 403 when Origin not in workspace allowlist ===")
    _setup_ws(landing_url="https://lp.example.com")
    _ensure_campaign(source_tag="cmp_a")
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_a"},
                          headers={"Origin": "https://evil.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=403 (got {r.status_code})", r.status_code == 403)


def test_404_unknown_campaign():
    print("\n=== Test 2: 404 unknown_campaign when src has no Campaign row ===")
    _setup_ws()
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_does_not_exist"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    ok1 = check(f"status=404 (got {r.status_code})", r.status_code == 404)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok2 = check(f"body says unknown_campaign (got {body!r})", body.get("error") == "unknown_campaign")
    return ok1 and ok2


def test_502_channel_unreachable():
    print("\n=== Test 3: 502 when resolve returns None ===")
    _setup_ws(attribution_channel_id=None)
    _ensure_campaign(source_tag="cmp_b")
    saved = _patch_attribution({"resolve": None, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_b"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=502 (got {r.status_code})", r.status_code == 502)


def test_502_when_mint_returns_none():
    print("\n=== Test 4: 502 when mint returns None (Telethon failure) ===")
    _setup_ws()
    _ensure_campaign(source_tag="cmp_c")
    saved = _patch_attribution({"resolve": -1001, "mint": None})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_c"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=502 (got {r.status_code})", r.status_code == 502)


def test_200_returns_invite_link():
    print("\n=== Test 5: 200 returns invite_link, campaign, channel_id ===")
    _setup_ws()
    _ensure_campaign(source_tag="cmp_d")
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+ok123")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_d"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    ok1 = check(f"status=200 (got {r.status_code})", r.status_code == 200)
    body = r.json() if ok1 else {}
    ok2 = check(f"invite_link present (got {body!r})", body.get("invite_link") == "https://t.me/+ok123")
    ok3 = check(f"campaign='cmp_d'", body.get("campaign") == "cmp_d")
    ok4 = check(f"channel_id=-1001", body.get("channel_id") == -1001)
    ok5 = check(f"CORS header echoes origin",
                r.headers.get("access-control-allow-origin") == "https://lp.example.com")
    return ok1 and ok2 and ok3 and ok4 and ok5


def test_200_www_variant_allowed():
    print("\n=== Test 6: 200 when Origin is the www. variant of landing_page_url ===")
    _setup_ws(landing_url="https://lp.example.com")
    _ensure_campaign(source_tag="cmp_e")
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+ok")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_e"},
                          headers={"Origin": "https://www.lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=200 (got {r.status_code})", r.status_code == 200)


def test_404_inactive_campaign():
    print("\n=== Test 7: 404 when Campaign exists but is_active=False ===")
    _setup_ws()
    _ensure_campaign(source_tag="cmp_inactive", is_active=False)
    saved = _patch_attribution({"resolve": -1001, "mint": _stub_link("https://t.me/+x")})
    try:
        r = _client().get("/attribution/invite",
                          params={"workspace_id": 1, "src": "cmp_inactive"},
                          headers={"Origin": "https://lp.example.com"})
    finally:
        _restore_attribution(saved)
    return check(f"status=404 (got {r.status_code})", r.status_code == 404)


def main():
    results = [
        test_403_when_origin_not_allowed(),
        test_404_unknown_campaign(),
        test_502_channel_unreachable(),
        test_502_when_mint_returns_none(),
        test_200_returns_invite_link(),
        test_200_www_variant_allowed(),
        test_404_inactive_campaign(),
    ]
    passed = sum(results); total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
