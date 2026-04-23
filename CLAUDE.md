# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telelytics — a multi-tenant Telegram CRM & signal-mirroring platform. Clients run trading communities: Meta ads → landing page → Telegram bot → lead pipeline → VIP channel. The system tracks leads through an 8-stage sales funnel, auto-fires follow-up messages, mirrors trade signals to VIP channels, and provides analytics + affiliate management.

Live at: **https://telelytics.org**

---

## Commands

### Backend
```bash
cd backend
source .venv/bin/activate          # venv lives at backend/.venv
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm run dev        # dev server at http://localhost:5173
npm run build      # outputs to frontend/dist (served by FastAPI in prod)
npx tsc --noEmit   # type-check only
```

### Deploy (on VPS)
```bash
git pull
cd frontend && npm run build && cd ..
sudo systemctl restart telegrambot
```

The `telegrambot` systemd service runs uvicorn on port 8000. FastAPI serves `frontend/dist` as static files — no separate web server.

---

## Architecture

### Single-process, single-repo

FastAPI (`backend/app/main.py`) serves both the API and the built React SPA. In production there is one process. In dev, Vite proxies to `localhost:8000`.

A middleware in `main.py` intercepts browser navigations (requests with `Accept: text/html` and no `Authorization` header) and serves `frontend/dist/index.html` so React Router handles routing client-side.

### Database

- **Local dev**: SQLite (`leadbot.db` in repo root)
- **Production**: PostgreSQL (set `DATABASE_URL` in `.env`)
- **Migrations**: no Alembic. `_ensure_columns()` in `database/__init__.py` adds missing columns on every startup. When adding a new column: add it to the SQLAlchemy model in `models.py` AND add it to `_ensure_columns()` so existing deployments get it automatically.

### Multi-tenancy (workspaces)

Every resource is scoped to a `workspace_id`. The JWT carries `workspace_id`; the FastAPI dependency `get_workspace_id` extracts it. All queries filter by workspace.

Hierarchy: `Organization` → root `Workspace` (org owner) → child `Workspace` (affiliates). `Workspace.workspace_role` is either `"owner"` or `"affiliate"`. `Workspace.parent_workspace_id` / `root_workspace_id` track the tree.

### Auth & roles

Roles (highest → lowest): `developer` → `admin` → `operator` → `vip_manager` → `affiliate`.

- `developer/admin/operator/vip_manager`: static credentials in `.env`.
- `affiliate`: credentials generated at creation, stored hashed in `affiliates.affiliate_login_username` / `login_password_hash`.

JWT includes: `sub`, `role`, `workspace_id`, `org_id`, `org_role`, `affiliate_id`. `org_role` is `org_owner` or `workspace_owner` and controls workspace switching / sub-affiliate creation.

Use `require_roles(...)` or `require_affiliate` / `require_workspace_owner` FastAPI dependencies to gate endpoints.

### Telegram: two separate integrations

| | Bot API (webhook) | Telethon (MTProto) |
|---|---|---|
| What | Receives incoming bot messages, forwards signals | Operator account — reads/sends DMs as a human |
| Config | `bot_token` on Workspace (or `BOT_TOKEN` env) | `telethon_session` StringSession on Workspace |
| Entry point | `POST /webhook/{workspace_id}` | `services/telethon_client.py` |
| Sets up via | Settings → Bot tab | Settings → Telegram tab (OTP flow) |

Signal mirroring: Telethon listens on `SOURCE_CHANNEL_ID` (env). On new channel post → `handlers/signals.py` → `services/forwarding.py` → copies to all destination channels (static `DESTINATION_CHANNEL_IDS` env + active `Affiliate.vip_channel_id` from DB).

### Lead pipeline

Leads enter when someone DMs the bot (`handlers/leads.py` → `ensure_contact`). Stage advances when the **operator's outgoing** message contains a keyword from `stage_keywords` table (fallback: hardcoded `STAGE_KEYWORDS` in `services/pipeline.py`). Every stage change is logged in `stage_history`. The scheduler (`services/scheduler.py`, APScheduler) fires follow-up messages from `follow_up_templates`, respecting Dubai timezone window (09:00–22:00).

### Frontend routing

`App.tsx` defines all routes. Key guards:
- `PrivateRoute` — redirects to `/login` if no token; redirects to `/onboarding` if `role === "affiliate"` and `onboarding_complete === false`.
- `OnboardingRoute` — redirects to `/` if `onboarding_complete` is already true.

Affiliates after onboarding get the full CRM (Leads, Analytics, Settings). Their Dashboard renders `AffiliateSelfDashboard` (referral stats + checklist). Non-affiliates get the full admin dashboard.

`onboarding_complete` is stored in localStorage via `auth.ts:saveAuth` and updated by `markOnboardingComplete()` after the wizard finishes.

### Settings architecture

`SettingsPage.tsx` has five tabs: `pipeline | team | bot | telegram | meta`. Each tab is a self-contained component at the bottom of the file. Bot and Telegram tabs call the existing workspace-aware backend endpoints — they work for any workspace automatically because the JWT carries `workspace_id`.

### API base URL pattern

Every `api/` file uses:
```ts
const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";
```
In production the frontend is same-origin so `API_BASE` is empty string.

---

## Key env vars

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | Postgres URL; empty = SQLite |
| `BOT_TOKEN` | Workspace-1 bot (fallback when DB token not set) |
| `WEBHOOK_SECRET` | Workspace-1 webhook validation (fallback when DB secret not set) |
| `SOURCE_CHANNEL_ID` | Telegram channel to mirror signals from |
| `DESTINATION_CHANNEL_IDS` | Comma-separated static destination channel IDs |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | MTProto app credentials (from my.telegram.org) |
| `SECRET_KEY` | JWT signing key |
| `APP_BASE_URL` | Public URL, used to build webhook registration URL |
| `DEVELOPER_USERNAME/PASSWORD` | etc. for each static role |

---

## Naming conventions

This is a generic SaaS product. **Never use client names** (Walid, Talal, or any specific person's name) in code, variable names, comments, or commit messages.
