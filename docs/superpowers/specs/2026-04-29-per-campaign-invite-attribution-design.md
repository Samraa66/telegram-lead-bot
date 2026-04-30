# Per-Campaign Telegram Invite-Link Attribution — Design Spec

**Date:** 2026-04-29
**Status:** Ready for review
**Type:** Feature (new endpoint + new tables + Telethon listener + ensure_contact extension + frontend modal)

## Goal

Restore per-campaign attribution by exploiting Telegram's chat-invite-link feature. Each campaign gets its own unique invite link to the existing 47k-member public channel; Telethon listens for joins, records the campaign tag against the user, and the bot claims that tag the moment the user later starts the bot from the pinned link.

This preserves the existing social-proof funnel (Meta ad → landing page → public channel → bot) while adding the missing attribution layer that makes Meta CAPI conversion-based ad optimisation actually work.

## Non-goals

- **Bypassing the public channel.** Walid's funnel depends on the channel as the social-proof step. We do not route paid traffic directly to the bot as the main solution.
- **Attributing pre-existing channel members.** Users who joined before this ships have no recorded join → they continue to hit the bot as organic (NULL source_tag).
- **Tracking attribution past 90 days.** Unclaimed `channel_join_events` rows older than 90 days are deleted by a daily cleanup job.
- **Touching the existing `/start <tag>` deep-link path.** It stays functional and takes precedence over channel-join attribution (a fresh deep-link click overwrites stale public-channel attribution).
- **Auto-installing the JS snippet on Walid's landing page.** We provide a copy-paste block in the Telelytics dashboard. Walid pastes it once.
- **Real Telegram API contract tests in CI.** All tests use HTTP-layer mocks via `MockHttpClient` and a mocked Telethon client object — same convention as Spec A.5.

## Context

The current funnel:

```
Meta ad (?utm_campaign=cmp_xxx)
   → bullishfxwalid.com/vsl-page-fb-7
       → static "Join Channel" button (https://t.me/+publicChannelLink)
           → user joins the 47k-member public channel
               → reads pinned post → taps t.me/{bot}
                   → bot receives /start with NO param
                       → contact.source = NULL
```

Attribution dies at the static channel link because Telegram channel invite links ignore `?start=`. The campaign tag never reaches our bot. Result: every paid lead arrives indistinguishable from organic, Meta CAPI cannot optimise on conversion, and analytics dashboards show nothing meaningful.

Walid is the workspace owner and the operator of `bullishfxwalid.com`. There is no third-party in the funnel — the same person controls the Meta ad, the landing page, the channel (admin via Telethon operator account), and the bot.

## Architecture

Six numbered touch-points, each maps 1:1 to a task in the implementation plan.

```
[1] Meta ad URL has ?utm_campaign=cmp_xxx
       ↓
[2] Walid's landing page — JS snippet reads utm_campaign / src and fetches:
       GET /attribution/invite?workspace_id=N&src=cmp_xxx
       ↓
[3] Backend endpoint: returns existing invite link or mints one via Telethon
       (ExportChatInviteRequest), persists row to campaign_invite_links
       returns { "invite_link": "https://t.me/+abc123" }
       ↓
[4] JS rewrites Join button href → user clicks → Telegram joins them to the channel
       ↓
[5] Telethon ChatAction listener fires:
       extracts invite-link hash from event → looks up source_tag →
       INSERT INTO channel_join_events (workspace_id, telegram_user_id,
                                        channel_id, source_tag, joined_at)
       ↓
   [user reads pinned post, taps t.me/{bot}, types /start]
       ↓
[6] ensure_contact() in handlers/leads.py:
       if /start has explicit tag → use it (existing behaviour preserved)
       else → look up most-recent unclaimed channel_join_events row for telegram_user_id
              → write source_tag to contact, set entry_path='public_channel'
              → mark the join row as claimed
   Existing pipeline continues unchanged.
```

### Module map

```
backend/app/
  database/models.py
    + Workspace.attribution_channel_id (BIGINT, nullable)
    + class CampaignInviteLink         (new table)
    + class ChannelJoinEvent           (new table)
  database/__init__.py
    + _ensure_columns adds the column + creates the new tables
  services/attribution.py             ← new module: mint_invite_link,
                                        resolve_attribution_channel,
                                        record_channel_join, claim_pending
  services/telethon_client.py
    + register_channel_join_handler called from start_workspace_client
  services/scheduler.py               ← extend with daily cleanup job
  handlers/leads.py                   ← ensure_contact extended with claim
  main.py                             ← new endpoint /attribution/invite

frontend/src/
  api/campaigns.ts                    ← extend response shape
  pages/AnalyticsDashboard.tsx        ← extend campaign-creation modal
```

## Per-component design

### 1. Auth model — `/attribution/invite`

The endpoint is called from a third-party domain (Walid's `bullishfxwalid.com`) at landing-page load time, anonymously, with no JWT. Three protections, in order:

1. **CORS gate.** Read `Origin` header; allow only if its host equals the host parsed out of `Workspace.landing_page_url` (or its `www.` variant). Echo that exact origin in `Access-Control-Allow-Origin`. Anything else → 403, browser blocks client-side.
2. **Rate limit.** SlowAPI (existing dep) — 30 req/min per IP per workspace_id.
3. **Existing-campaign gate.** The endpoint only mints / returns links for `(workspace_id, src)` pairs where a `Campaign` row already exists. **This is the primary spam shield** — attackers cannot farm new invite links because the tag must already be created in the dashboard by an authenticated workspace owner.

### 2. Channel identity & resolution

`Workspace.main_channel_url` stores `t.me/+abc...` (a join URL), not a numeric chat ID. Telethon needs the numeric ID for `ExportChatInviteRequest` and join-event matching. Strategy:

- New nullable column `Workspace.attribution_channel_id BIGINT`.
- On the first call to `/attribution/invite` for a workspace, Telethon resolves `main_channel_url` → entity → numeric ID → save to the column.
- Subsequent calls read from the column (no Telethon round-trip).
- Resolution failure (Telethon not in channel, URL invalid) → 502 `{"error": "channel_unreachable"}` with a clear message.

Self-healing: if `main_channel_url` ever changes, clear `attribution_channel_id` and the next call re-resolves.

### 3. Multi-touch attribution

**Last-touch wins.** Same Telegram user joining via campaign A then later via campaign B → campaign B's tag is the one written to `contact.source_tag` when they DM the bot. Implementation: `ORDER BY joined_at DESC LIMIT 1` against unclaimed `channel_join_events` rows.

Justification: Meta's CAPI deduplication and ad-optimisation use last-touch under the hood, so aligning matters for ad-spend feedback. Plus the operational case is "user sees ad, joins, sees a different ad later, joins again" — they're more recently engaged with ad B.

We retain the full join history in `channel_join_events`, so attribution rules can be reanalysed later without storage redesign.

### 4. Storage — append-only event log + 90-day TTL

```sql
ALTER TABLE workspaces ADD COLUMN attribution_channel_id BIGINT;

CREATE TABLE campaign_invite_links (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id),
    source_tag      VARCHAR(255) NOT NULL,            -- denormalised from campaigns.source_tag
    channel_id      BIGINT NOT NULL,
    invite_link     TEXT NOT NULL,                    -- full https://t.me/+abc123
    invite_link_hash VARCHAR(64) NOT NULL,            -- suffix after the +
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMP,
    CONSTRAINT uq_invite_per_campaign UNIQUE (workspace_id, campaign_id, channel_id)
);
CREATE INDEX idx_campaign_invite_links_hash ON campaign_invite_links (invite_link_hash);
CREATE INDEX idx_campaign_invite_links_ws_src ON campaign_invite_links (workspace_id, source_tag);

CREATE TABLE channel_join_events (
    id                   SERIAL PRIMARY KEY,
    workspace_id         INTEGER NOT NULL REFERENCES workspaces(id),
    telegram_user_id     BIGINT NOT NULL,
    channel_id           BIGINT NOT NULL,
    source_tag           VARCHAR(255),                -- nullable: organic joins are recorded with NULL
    invite_link_hash     VARCHAR(64),                 -- nullable: same reason
    joined_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    claimed_contact_id   INTEGER REFERENCES contacts(id),
    claimed_at           TIMESTAMP
);
CREATE INDEX idx_join_events_user_lookup ON channel_join_events (workspace_id, telegram_user_id, joined_at DESC);
CREATE INDEX idx_join_events_ttl ON channel_join_events (joined_at);
```

Design rationales:

- **`source_tag` denormalised** onto `campaign_invite_links` so the join handler doesn't need a JOIN.
- **`invite_link_hash` indexed** because that's the field the join event matches against.
- **`claimed_contact_id` / `claimed_at`** track which contact ate the row — analytics can answer "% of paid joins that ever DM'd the bot".
- **Organic joins recorded with NULL source_tag** — useful for "channel growth: paid vs organic" without a separate counter.
- **Append-only.** Last-touch resolved at claim time, not via upsert. Storage cost is trivial (~90k rows for a fast-growing client at 1k joins/day; cheap on Postgres).

**Cleanup job.** Daily APScheduler task in `services/scheduler.py`:

```sql
DELETE FROM channel_join_events
WHERE joined_at < NOW() - INTERVAL '90 days'
  AND claimed_contact_id IS NULL;
```

Claimed rows are kept indefinitely as part of the contact's attribution audit.

### 5. Endpoint shape — `GET /attribution/invite`

```
GET /attribution/invite?workspace_id=<int>&src=<source_tag>
```

GET (not POST) so the browser doesn't preflight on cross-origin.

Request handling, in order:

1. CORS gate (Origin header vs Workspace.landing_page_url host).
2. Rate limit (30 req/min per IP per workspace_id).
3. Campaign lookup (`SELECT FROM campaigns WHERE workspace_id=? AND source_tag=? AND is_active=TRUE`). Missing → 404.
4. Channel resolution (cached on Workspace.attribution_channel_id; lazy Telethon resolve on miss).
5. Invite-link mint (cached in `campaign_invite_links`; Telethon `ExportChatInviteRequest` on miss; idempotent — same `(workspace_id, src)` always returns the same link).
6. Response:
   ```json
   {
     "invite_link": "https://t.me/+abc123def",
     "campaign": "cmp_xxx",
     "channel_id": -1001234567890
   }
   ```
   With `Cache-Control: private, max-age=600` (browser caches 10 min).

| Failure | Status | Body |
|---|---|---|
| Origin not in allowlist | 403 | `{"error": "origin_not_allowed"}` |
| Rate limit hit | 429 | `{"error": "rate_limited"}` |
| Unknown campaign tag | 404 | `{"error": "unknown_campaign"}` |
| Telethon can't resolve channel | 502 | `{"error": "channel_unreachable"}` |
| Telethon down for workspace | 503 | `{"error": "operator_account_offline"}` |

The JS snippet falls back to the workspace's static `main_channel_url` on any failure — never breaks the user's join flow, just loses attribution for that click.

### 6. Telethon join listener

Registered in `services/telethon_client.py`'s `start_workspace_client` only when `Workspace.attribution_channel_id` is set. Re-binding on attribution-channel change goes through the existing Telethon stop+restart cycle (per the source-channel pattern from per-org-forwarding).

Event source: Telethon's `events.ChatAction` fires on `joined` / `added` / `user_joined`. The event exposes:

- `event.user_id` — the Telegram user
- `event.chat_id` — the channel
- `event.action_message.action.invite` — `ChatInviteExported` if join was via invite link, else absent

Handler body (extracted as a pure async function `services/attribution.py:handle_channel_join` so tests don't need a live Telethon):

```python
async def handle_channel_join(event, db):
    ws = db.query(Workspace).filter(
        Workspace.attribution_channel_id == event.chat_id
    ).first()
    if not ws:
        return  # not our public channel for any workspace

    invite = getattr(getattr(event.action_message, "action", None), "invite", None)
    invite_link_hash = None
    source_tag = None
    if invite is not None:
        invite_link_hash = _extract_hash(invite.link)
        row = db.query(CampaignInviteLink).filter_by(
            workspace_id=ws.id, invite_link_hash=invite_link_hash,
        ).first()
        source_tag = row.source_tag if row else None

    db.add(ChannelJoinEvent(
        workspace_id=ws.id,
        telegram_user_id=event.user_id,
        channel_id=event.chat_id,
        source_tag=source_tag,
        invite_link_hash=invite_link_hash,
        joined_at=datetime.utcnow(),
    ))
    db.commit()
```

Three deliberate behaviours:

1. **Non-attributed (organic) joins are still logged** with NULL source_tag.
2. **No bot DM is sent at join time** — attribution is passive until the user actually starts the bot.
3. **No retroactive sweep.** Pre-Spec-B channel members trigger nothing.

Best-effort: if Telethon misses an event during a disconnect, that user's attribution is lost. This is acceptable and consistent with how Telethon already behaves for signal forwarding.

### 7. Attribution claim — `ensure_contact`

Extends the existing `handlers/leads.py:ensure_contact`. Runs after the contact row is materialised, before the welcome flow:

```python
# 1. Explicit /start <tag> — UNCHANGED, wins everything else.
if start_param:
    contact.source = start_param
    contact.source_tag = start_param
    # entry_path is already set by existing logic to 'direct' or 'landing_page'.

# 2. Else: claim a pending channel join (last-touch).
elif contact.source_tag is None:
    pending = (
        db.query(ChannelJoinEvent)
          .filter(
              ChannelJoinEvent.workspace_id == workspace_id,
              ChannelJoinEvent.telegram_user_id == telegram_user_id,
              ChannelJoinEvent.source_tag.isnot(None),
              ChannelJoinEvent.claimed_contact_id.is_(None),
          )
          .order_by(ChannelJoinEvent.joined_at.desc())
          .first()
    )
    if pending:
        contact.source_tag = pending.source_tag
        contact.source = pending.source_tag           # legacy compat
        contact.entry_path = "public_channel"
        pending.claimed_contact_id = contact.id
        pending.claimed_at = datetime.utcnow()

# 3. Else: leave as-is (NULL source, entry_path falls through to existing logic).
```

Properties:

- `/start` param wins even when a stale channel-join row exists — fresh deep links overwrite stale attribution.
- Only `claimed_contact_id IS NULL` rows are eligible — defensive against double-claim.
- Only `source_tag IS NOT NULL` joins are eligible — organic joins live in the table for analytics but never claim a contact.
- Re-running `ensure_contact` is idempotent — `elif contact.source_tag is None` skips the lookup.

### 8. Frontend — campaign-creation modal

Single change in `frontend/src/pages/AnalyticsDashboard.tsx`. The existing "Generate Tracked Link" modal extends from one link to three rendering options:

1. **Bot deep link** — `https://t.me/{bot}?start={source_tag}`, for organic / non-channel placements.
2. **Channel invite link** — fetched live from `/attribution/invite`, for placements that want the channel social-proof step but no landing page (Twitter bio, podcast notes, etc.).
3. **Landing-page snippet** — the JS code block to paste on the landing page's Join button. Pre-templated with the workspace's `id` and the campaign's `source_tag`.

```html
<script>
(async () => {
  const p = new URLSearchParams(window.location.search);
  const src = p.get('utm_campaign') || p.get('src') || 'organic';
  try {
    const r = await fetch(
      `https://telelytics.org/attribution/invite?workspace_id={WS_ID}&src=${src}`,
      { mode: 'cors' });
    if (r.ok) {
      const { invite_link } = await r.json();
      document.querySelector('{SELECTOR}').href = invite_link;
    }
  } catch (e) { /* leave default href */ }
})();
</script>
```

`{SELECTOR}` is a small input in the modal (default `#join-button`). If the fetch fails for any reason, the Join button keeps its static href — never breaks the user's flow, just loses attribution for that click.

The Campaigns table view also gets two new columns surfaced from the existing `/campaigns` endpoint:

```json
{
  "id": 42,
  "source_tag": "cmp_a1b2c3d4",
  "name": "spring_promo",
  "link": "https://t.me/MyBot?start=cmp_a1b2c3d4",
  "landing_url": "https://lp.example.com?src=cmp_a1b2c3d4",
  "invite_link": "https://t.me/+xKL9q4-Z83Mk",   // NEW
  "channel_join_count": 137,                       // NEW
  "leads": ...,
  "deposits": ...
}
```

So Walid can see "this campaign brought 137 channel joins, 89 of them DM'd the bot, 12 deposited" in one row.

## Testing

Same script-style convention as Spec A.5 (`backend/scripts/test_*.py`, runnable via `python -m scripts.<name>`).

| File | Coverage | Tests |
|---|---|---|
| `test_attribution_endpoint.py` | origin allowlist, rate limit, 404 unknown campaign, 502 channel unresolvable, 200 mint, 200 cache-hit, idempotent | 7 |
| `test_attribution_telethon.py` | invite-link join records row, organic join records NULL row, non-attribution channel ignored, malformed event no crash, hash extraction | 5 |
| `test_attribution_claim.py` | `/start` param wins, channel-join claim when no param, last-touch ordering, no double-claim, organic join doesn't claim, no pending leaves NULL, claimed row not re-eligible | 7 |
| `test_attribution_cleanup.py` | TTL deletes unclaimed >90d, keeps unclaimed <90d, never deletes claimed (any age) | 3 |
| `test_attribution_models.py` | column types match models, indexes present, FK ON DELETE behaviour | 3 |

**Total: 25 new tests across 5 scripts.** Re-run alongside the existing 79 backend tests in the final integration step.

Mocking strategy:

- Telethon's `ExportChatInviteRequest` is wrapped behind `services/attribution.py:mint_invite_link(client, channel_id, name)`. Tests inject a mock client that returns a canned `ChatInviteExported` object.
- `events.ChatAction` handler body is the pure `handle_channel_join(event, db)` function — tests construct fake events as dict-shaped data and call directly.
- `/attribution/invite` is exercised via FastAPI TestClient.

What we deliberately don't test in CI:

- Real Telegram API contracts (HTTP-mocked only).
- Browser CORS preflight (validated manually once on production).
- Rate-limit timing accuracy (just that it triggers).

Manual smoke test before declaring done:

1. Create a Campaign in the dashboard.
2. Hit `/attribution/invite?workspace_id=1&src=cmp_xxx` from the dashboard origin → confirm 200 + link.
3. Click the link from a test Telegram account → join the channel.
4. Verify a `channel_join_events` row appears.
5. DM the bot from that account → verify `contact.source_tag` got set, `claimed_contact_id` populated.

## Migration / rollout

Single PR. Schema migration via `_ensure_columns()` (no Alembic, per project convention).

Deploy order:

1. Backend deploy (uvicorn restart) — schema migration + new endpoint + Telethon listener bind. Listener is idempotent — even with no campaigns yet, it just records organic joins.
2. Frontend deploy — modal renders the new UI.
3. Walid creates one campaign as smoke test.
4. Walid pastes the snippet on `bullishfxwalid.com`'s Join button (one-time setup).
5. Walid updates Meta ad URLs to include `?utm_campaign=cmp_xxx`.

No phased rollout, no feature flag, no parallel-run period. The new code is purely additive — `/start` parser still works, existing `/campaigns` endpoint still returns the same shape (just with two extra fields), no existing field is repurposed.

Backwards-compatibility:

- Contacts already in the DB are untouched.
- Pre-Spec-B `Campaign` rows don't have invite links yet. First call to `/attribution/invite?src=<old_tag>` mints a link on demand.
- The static legacy `t.me/+publicChannelLink` keeps working forever — clicks land in the channel as organic joins (NULL source_tag in `channel_join_events`).

Operational risks:

| Risk | Probability | Mitigation |
|---|---|---|
| Telethon revoked / not admin in public channel | Medium | `/attribution/invite` returns 502; surfaces in dashboard immediately. Future: extend Spec A.5 system-health to probe attribution channel admin rights. |
| Telegram rate-limits invite-link minting | Low | Idempotent endpoint reuses cached rows — one mint per campaign ever. |
| Walid forgets `?utm_campaign=` in Meta | Medium | Snippet falls back to `src=organic` (visible as the "organic" row in Campaigns list). |
| Snippet conflicts with existing landing-page JS | Low | Snippet is async IIFE, scoped, only mutates one DOM element by selector. |
| Wrong selector configured | Low | Modal lets Walid set the selector; if wrong, button keeps default href, attribution shows zero leads — visible in dashboard. |

Runtime cost:

- One indexed SELECT per `/start` event (~0.1 ms).
- One INSERT per channel join — Telethon already handles thousands of events per minute on this account.
- Daily cleanup: one DELETE statement, <1s on any realistic table size.
- `/attribution/invite` cold path: one Telethon round-trip (~200 ms). Cached path: one indexed SELECT (~1 ms).

## Inventory of changes

**New files:**
- `backend/app/services/attribution.py` — `mint_invite_link`, `resolve_attribution_channel`, `handle_channel_join`, `claim_pending_attribution`, `_extract_hash`
- `backend/scripts/test_attribution_endpoint.py`
- `backend/scripts/test_attribution_telethon.py`
- `backend/scripts/test_attribution_claim.py`
- `backend/scripts/test_attribution_cleanup.py`
- `backend/scripts/test_attribution_models.py`

**Modified files:**
- `backend/app/database/models.py` — `Workspace.attribution_channel_id`, new `CampaignInviteLink`, new `ChannelJoinEvent`
- `backend/app/database/__init__.py` — column + new tables
- `backend/app/services/telethon_client.py` — register `events.ChatAction` handler in `start_workspace_client`
- `backend/app/services/scheduler.py` — daily cleanup job
- `backend/app/handlers/leads.py` — `ensure_contact` extension (claim block)
- `backend/app/main.py` — `GET /attribution/invite` endpoint; `/campaigns` response shape extended
- `frontend/src/api/campaigns.ts` — new response fields in TypeScript types
- `frontend/src/pages/AnalyticsDashboard.tsx` — three-link modal + new table columns

## Open questions

None. All design decisions resolved during brainstorming:

- Auth model: public endpoint, restricted to existing `Campaign` rows, CORS-allowlisted to workspace landing-page domain, IP rate-limited.
- Channel ID resolution: lazy Telethon resolve, cached on `Workspace.attribution_channel_id`.
- Multi-touch: last-touch wins.
- Storage: append-only `channel_join_events` log + 90-day TTL.
- Frontend: extended campaign-creation modal showing all three link options + JS snippet.
- Tests: 25 new tests across 5 scripts, HTTP-mocked Telethon and TestClient-driven endpoint exercise.
