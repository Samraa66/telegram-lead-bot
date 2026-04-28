# Per-Org Signal Forwarding — Design Spec

**Date:** 2026-04-28
**Status:** Ready for review
**Type:** Refactor + small frontend addition

## Goal

Make signal forwarding properly multi-tenant. Today the forwarding service hardcodes `workspace_id=1` and uses the env-level `BOT_TOKEN` to copy messages, regardless of which workspace's destinations it's targeting. After this refactor, each org-owner workspace independently forwards from *its own* source channel, using *its own* bot, to *its own* affiliates' VIP channels — with no cross-tenant interference and no env fallback.

## Non-goals

- Reset / wipe of existing data (workspace 1 stays intact as a safety state).
- Changes to lead-capture flow (bot DMs → leads). That path is already workspace-aware.
- Changes to operator DM flow (Telethon outgoing/inbound handlers). Already workspace-aware.
- Public self-serve signup. Tenants are still invited via the existing `POST /affiliates` flow with `parent_workspace_id=1`.

## Context

The Telethon multi-tenant infrastructure already exists in `services/telethon_client.py`:
- `_clients: dict[workspace_id → TelegramClient]`
- `start_workspace_client(workspace_id, ...)` / `stop_workspace_client(workspace_id)`
- Per-workspace `_make_inbound_handler` and `_make_outgoing_handler` factories

What's missing is the **signal-channel** handler. Today, signal capture lives in `handlers/signals.py` (a webhook-side path triggered by `channel_post` updates), and `services/forwarding.py` aggregates destinations across the entire platform with no per-org scoping.

Data model already supports per-org config:
- `Workspace.bot_token`, `Workspace.source_channel_id`, `Workspace.destination_channel_ids`
- `Workspace.workspace_role` (`"owner"` for org root, `"affiliate"` for children)
- `Workspace.root_workspace_id` traces every workspace back to its org root in O(1)
- `Affiliate.affiliate_workspace_id` links each Affiliate row to its own workspace
- `Affiliate.vip_channel_id`, `Affiliate.is_active`

## Architecture

Three backend files change. One frontend file is extended. Everything else stays.

### `backend/app/services/forwarding.py` (refactored)

**Removed:**
- `get_static_destination_channels(workspace_id=1)` and its env-`DESTINATION_CHANNEL_IDS` fallback branch
- `get_effective_source_channel_id(workspace_id=1)` and its env-`SOURCE_CHANNEL_ID` fallback branch
- `get_all_destination_channels()` (platform-wide aggregation)
- The `BOT_TOKEN` import from `app.config`

**Added:**

```python
def get_destinations_for_org(workspace_id: int, db: Session) -> list[str]:
    """
    Return vip_channel_ids of all active affiliates whose workspace is in
    the org tree rooted at workspace_id.
    """
    return [
        ch_id for (ch_id,) in (
            db.query(Affiliate.vip_channel_id)
            .join(Workspace, Affiliate.affiliate_workspace_id == Workspace.id)
            .filter(
                Workspace.root_workspace_id == workspace_id,
                Affiliate.is_active.is_(True),
                Affiliate.vip_channel_id.isnot(None),
            )
            .all()
        ) if ch_id
    ]

def copy_message(from_chat_id, message_id, dest_chat_id, bot_token: str) -> bool:
    """Copy via the org's own bot — token now an explicit arg, not env."""

def copy_signal_for_org(workspace_id: int, source_chat_id: str, message_id: int, db: Session) -> None:
    """
    Orchestrate the per-org copy:
      1. Fetch workspace.bot_token (warn-and-skip if NULL)
      2. Fetch destinations via get_destinations_for_org
      3. Loop copy_message for each destination, log per-channel failures
    """
```

### `backend/app/services/telethon_client.py` (extended)

**Added:**

```python
def _make_signal_handler(workspace_id: int):
    """
    Closure that fires when a NewMessage event matches the workspace's
    source_channel_id. Calls copy_signal_for_org(workspace_id, ...).
    """

# Inside start_workspace_client(...), after inbound/outgoing handlers register:
    if ws.workspace_role == "owner" and ws.source_channel_id:
        client.add_event_handler(
            _make_signal_handler(workspace_id),
            events.NewMessage(chats=[int(ws.source_channel_id)]),
        )
```

This means:
- On boot: `start_all_telethon_clients()` iterates workspaces with `telethon_session`. For each, after inbound/outgoing handlers, the signal handler registers IF the workspace is an org-owner with a source channel set.
- On settings update: existing `stop_workspace_client()` + `start_workspace_client()` cycle re-registers naturally.
- On workspace deletion: `stop_workspace_client()` cleans up — no change.

### `backend/app/handlers/signals.py` (deleted)

The webhook-side signal handler is gone. Telethon-per-org handles signal capture now. The bot-API webhook (`POST /webhook/{workspace_id}` in `main.py`) keeps doing what it does for *bot DMs* (lead capture), unchanged.

Concrete cleanups in `main.py`:
- Remove `from app.handlers.signals import process_signal_update` (line 35)
- Remove the `process_signal_update(body)` call inside the webhook handler (line ~242) and any branching that depended on its return value

### `frontend/src/pages/OnboardingPage.tsx` (extended)

Step 3 of the wizard branches on `org_role`:

| `org_role` | Step 3 prompt | Field written |
|---|---|---|
| `workspace_owner` (org root, like an invited tenant) | "Connect your Signal Source channel" | `Workspace.source_channel_id` |
| anything else (sub-affiliate) | "Link your VIP channel" (current behavior) | `Affiliate.vip_channel_id` |

Same component shell, different copy + different field + different backend endpoint. The `org_role` is already in the JWT and exposed via `getStoredUser()`.

A new endpoint is needed for the org-owner branch:
```
PATCH /workspace/me/source-channel
body: { source_channel_id: string }
auth: require_workspace_owner
```

This endpoint MUST also call `stop_workspace_client(ws_id)` + `start_workspace_client(ws_id, ...)` after writing, so the new channel takes effect without a service restart.

The existing `/affiliate/me/checklist` endpoint stays for sub-affiliates.

## Signal flow (end-to-end)

1. Tenant A's Telethon client (running as Tenant A's Telegram user) detects a new post in their `source_channel_id`.
2. `_make_signal_handler(tenant_a_ws_id)` closure fires → `copy_signal_for_org(tenant_a_ws_id, source_id, msg_id, db)`.
3. `forwarding.py` reads `Workspace.bot_token` for `tenant_a_ws_id`. If NULL → warn-log and return.
4. `get_destinations_for_org(tenant_a_ws_id, db)` returns `vip_channel_id`s of every active affiliate under Tenant A's tree.
5. Loop: `copy_message(source_id, msg_id, vip_id, tenant_a_bot_token)`. Per-channel failures logged but don't abort the loop.

Tenant B's flow is identical and completely independent. No shared state. No env reads.

## Migration & env cleanup

- **Workspace 1's DB columns stay NULL** for `bot_token`, `source_channel_id`, `destination_channel_ids`. No migration of env values into DB.
- **Comment out in `backend/.env`:** `SOURCE_CHANNEL_ID`, `DESTINATION_CHANNEL_IDS`, `BOT_TOKEN`, `WEBHOOK_SECRET`. After this + restart, all forwarding stops and the system sits dormant until the first tenant configures a workspace.
- **Code:** delete the env-fallback branches entirely. The `BOT_TOKEN` and `DESTINATION_CHANNEL_IDS` imports in `forwarding.py` are removed. The `app/config.py` references stay (other modules read them for now), but they're effectively dead until/unless those modules are similarly refactored.
- **Kept in `.env`:** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `SECRET_KEY`, `DATABASE_URL`, `APP_BASE_URL`, role credentials (`DEVELOPER_*`, `ADMIN_*`, etc.). These are platform-level, not tenant data.

## Failure modes

| Failure | Behavior |
|---|---|
| Workspace has source channel but `bot_token` is NULL | `copy_signal_for_org` logs warning "ws=N has source but no bot token, skipping" and returns. No crash. |
| Bot not admin in destination channel | Telegram returns 400 `chat not found`. Per-channel error logged, loop continues to other destinations. |
| Source channel deleted / Telethon disconnect | That workspace's signal handler stops firing. Other workspaces unaffected. Reconnect on next `start_workspace_client` cycle. |
| Affiliate marked `is_active=False` | Naturally drops from destination list on next signal — no special handling. |
| Tenant changes `source_channel_id` mid-flight | The settings-save endpoint must explicitly call `stop_workspace_client(ws_id)` + `start_workspace_client(ws_id)` — see "Open questions" below: today only Telethon sign-in/disconnect and workspace deletion trigger this cycle. The endpoint that writes `source_channel_id` (Settings → Telegram → Signal Forwarding section, plus the new onboarding endpoint) must be extended to call the cycle. |
| Two tenants accidentally configure the same source channel | Both Telethon clients receive the event. Each forwards to its own affiliates using its own bot. Idempotent at the Telegram level — destinations get the message once per tenant. (Edge case, no special handling.) |

## Test plan

After the refactor lands and env vars are commented:

1. Restart service → forwarding fully dormant. Bot webhook returns 401 / silent (no token configured anywhere).
2. Sameer logs in as `developer` → `/affiliates` page → invites a new tenant (parent_workspace_id=1) → copies invite URL.
3. Tenant clicks invite → sets password → JWT shows `org_role=workspace_owner`, `role=affiliate` (existing model), `workspace_id=N`.
4. Onboarding wizard runs:
   - **Step 1 (Bot):** tenant creates new bot via BotFather, pastes token, registers webhook → `/webhook/{N}` activates.
   - **Step 2 (Telethon):** OTP login with tenant's Telegram user → session stored on workspace N.
   - **Step 3 (Source — branched on `org_role`):** tenant pastes source channel ID/link → written to `workspaces.source_channel_id`.
   - On finish: `start_workspace_client(N)` is called (or already running and gets re-cycled), and the signal handler registers because both source channel and Telethon session are now set.
5. Tenant goes to `/affiliates` → invites two test sub-affiliates → copies invite URLs.
6. Each sub-affiliate clicks invite → wizard runs in normal (VIP) mode → they paste a `vip_channel_id`.
   - **Bot-admin requirement:** the *tenant's* bot (not the sub-affiliate's own bot) must be admin in the sub-affiliate's VIP channel, because the tenant's bot is what does the copying. The current wizard copy in Step 3 says "add the bot you created in step 1" — which would be the sub-affiliate's own bot. This copy needs updating in the wizard for sub-affiliates so they add the *tenant's* bot username instead. Tracked under "Open questions" below.
7. Post a test message in the tenant's source channel.
8. **Assert in logs:**
   - `Telethon ws=N: signal received from <source_chat_id>, msg_id=...`
   - `Forwarding signal for workspace=N to 2 channel(s)`
   - `Copied to channel <aff_1_vip>` / `Copied to channel <aff_2_vip>`
   - All copies use tenant's bot token, not env's. Workspace 1's affiliates (none, but if any existed) get nothing.

## Rollback

Single-commit refactor. If any step fails:

```bash
cd ~/telegram-lead-bot
git revert <refactor-commit-sha>
sudo -u postgres pg_restore -d tgcrm_db --clean --if-exists ~/backups/pre-reset-20260428-131403/tgcrm_db.dump
cp ~/backups/pre-reset-20260428-131403/.env backend/.env
sudo systemctl restart telegrambot
```

~30 seconds. The DB dump and `.env` backup are already in `~/backups/pre-reset-20260428-131403/`.

## Open questions / known follow-ups

- **Sub-affiliate wizard copy needs updating**: Step 3 currently tells sub-affiliates to add "the bot you created in step 1" (their own bot) as admin in their VIP channel. After this refactor, they need to add the *tenant's* bot instead. The frontend needs to fetch and display the tenant's bot username during the sub-affiliate's onboarding. Backend endpoint needed: `GET /workspace/parent/bot-username` or include it in the existing `/affiliate/me/...` response. **In scope for this work.**
- **Settings → Telegram Save endpoint**: today only Telethon sign-in/disconnect and workspace deletion trigger `stop_workspace_client + start_workspace_client`. The endpoint(s) that write `source_channel_id` and the new `/workspace/me/source-channel` endpoint must be audited and extended to cycle the client. **In scope for this work.**
- **Lead-capture bot-webhook env fallback** (`BOT_TOKEN`, `WEBHOOK_SECRET` reads in `main.py`): out of scope. The webhook handler in `main.py` will still read env values for workspace-1 fallback after this refactor. File for next pass.
- **Worker capacity**: each org runs its own Telethon client in the same process. Telethon clients are async-friendly but there's a practical ceiling (file descriptors, memory, MTProto rate limits). Not a near-term issue at 1-10 tenants. File for monitoring.
- **Backups cron is broken** (independent finding — `/var/backups/telelytics/*.sql` files are 707 bytes each, empty `pg_dump` output). Fix as separate task post-refactor.
