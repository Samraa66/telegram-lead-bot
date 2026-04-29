# Lead Classification Fixes — Design Spec

**Date:** 2026-04-29
**Status:** Ready for review
**Type:** Bugfix + small schema addition + small frontend addition

## Goal

Three independent slices, deployed together:

1. **VIP-name re-detection on rename.** Today the workspace's `vip_marker_phrases` only run at *initial* contact creation. When the operator later renames an existing lead to e.g. `VIP Mike`, the new name is saved but the contact's stage doesn't move. This spec makes the same marker check run on every name change, with a forward-only promotion rule.
2. **Backfill UI button.** The endpoint `POST /workspaces/{id}/backfill-telegram-history` already exists but has no UI affordance. Surface it as a "Sync Telegram history" button in Settings → Telegram, with a stored last-run summary.
3. **Source schema foundation.** Replace the single free-text `Contact.source` column with a two-column model — `entry_path` (controlled vocab) and `source_tag` (free-form campaign label). Migrate existing rows and recover any historical `/start <param>` payloads from message history.

## Non-goals

- **Per-campaign Telegram invite-link attribution.** That is the subject of a follow-up spec ("Spec B"). This spec only adds the schema columns Spec B will populate; it does not introduce invite-link generation, the `/attribution/invite` endpoint, the Telethon channel-join listener, the `campaign_invites` table, or the `pending_attributions` claim flow.
- **Landing-page integration.** Out of scope. The `/start` payload parser stays as it is and continues to write into `source_tag` going forward.
- **Dropping the legacy `source` column.** Kept as a deprecated mirror for one stable week, matching the project's existing pattern (legacy `Contact.current_stage` is still around for the same reason). A follow-up cleanup PR will drop it.
- **Async / streaming progress for the backfill button.** Synchronous request only. Walid runs this rarely; a job queue is over-engineering.
- **Continuous Telethon dialog re-sync** to catch silent renames. Out of scope. Active leads (those who exchange messages) get re-checked on every message; silent leads get re-checked when the admin runs the backfill button.
- **Auto-trigger backfill from the onboarding wizard.** Manual button only.
- **Demotion based on marker removal.** Promotion is forward-only by design.

## Context

### Today's VIP-name detection

`backend/app/handlers/leads.py:122` — `_initial_stage_for_contact` runs a case-insensitive substring check against `Workspace.vip_marker_phrases` (defaults: `["vip", "premium"]`). If a contact's `first_name + last_name` contains any marker, they're inserted at `member_stage_id` instead of stage 1. This was refactored from a hardcoded `"vip" in name` check on 2026-04-27 (commit `2072e81`).

The function is called from `ensure_contact`'s **create** branch only. The **update** branch (`leads.py:60-86`) reassigns `first_name` / `last_name` and re-classifies via `classify_contact`, but never re-runs the marker check — and the classifier itself doesn't look at names.

Result: `Walid renames "Mike" → "VIP Mike"` updates the row but leaves the stage unchanged. The lead never gets promoted to the member stage.

### Today's backfill endpoint

`backend/app/main.py:2840` — `POST /workspaces/{workspace_id}/backfill-telegram-history` exists, gated to `developer`/`admin` roles, with a `limit_per_dialog` query param clamped at 500. It returns `{contacts_created, messages_replayed, skipped}` (or `{error}` if Telethon isn't connected). The implementation lives in `backend/app/services/backfill.py`.

There is no frontend trigger — the only way to call it is via `curl` or DevTools. Walid hasn't run it in production yet.

### Today's source tracking

`Contact.source` is a single nullable VARCHAR populated from `/start <param>` deep links (`extract_start_source` in `handlers/leads.py:22` and the Telethon mirror at `services/telethon_client.py:115-118`). The vast majority of Walid's existing leads have `source = NULL` because the funnel routes them through a public Telegram channel, which strips any UTM tag from the bot link. Spec B will fix this with per-campaign invite links; Spec A only sets up the schema.

### Why two columns instead of one

The user wants to slice analytics two ways:
- "Which Meta **campaign** drove deposits?" — that's `source_tag` (free-form: `meta_summer_2026`, `affiliate_42`).
- "Do **landing-page** leads convert better than **public-channel** leads?" — that's `entry_path` (controlled vocab: `landing_page`, `public_channel`, `affiliate`, `direct`, `unknown`, `legacy_pre_attribution`).

Compressing both into one column either loses information or forces compound encodings. Two columns keeps queries clean and is cheap to add.

## Architecture

Five backend files change, one frontend file changes. No new files apart from tests.

### Backend changes

| File | Change |
|---|---|
| `backend/app/database/models.py` | Add `Contact.entry_path` and `Contact.source_tag` columns. Add `Workspace.last_backfill_at` and `Workspace.last_backfill_summary` columns. Add minimal `AppMeta` model. |
| `backend/app/database/__init__.py` | Extend `_ensure_columns` to add the four new columns. Add startup-time `legacy_attribution_v1` migration step. |
| `backend/app/services/pipeline.py` | Add `maybe_promote_to_member_stage(contact, db)` helper. |
| `backend/app/handlers/leads.py` | Replace inline match in `_initial_stage_for_contact` with a call to the new helper's pure-function core. Call `maybe_promote_to_member_stage` from the update path of `ensure_contact` when `first_name` or `last_name` actually changes. Switch `extract_start_source` writes to populate `source_tag` (mirror to legacy `source`). |
| `backend/app/services/backfill.py` | Call `maybe_promote_to_member_stage(contact, db)` once per dialog after `ensure_contact`, before the message replay loop. Persist `last_backfill_at` + `last_backfill_summary` on the workspace at the end. |

### Frontend changes

| File | Change |
|---|---|
| `frontend/src/pages/SettingsPage.tsx` | Add "Sync Telegram history" card to the Telegram tab. Calls `POST /workspaces/{ws}/backfill-telegram-history?limit_per_dialog=500`, shows result toast and "Last run" timestamp. |
| `frontend/src/api/contacts.ts` (or wherever `Contact` type lives) | Add optional `entry_path` and `source_tag` fields. Keep `source`. |

### What stays the same

- `services/classifier.py` — already derives `vip` from `is_member_stage` flags + `deposit_status`. Promoting a contact via name change automatically flips classification on the next `classify_contact` call.
- `services/pipeline.py` keyword logic (`infer_stage_id`, `advance_stage`) — unchanged.
- `services/telethon_client.py` — already calls `ensure_contact` on every event; gets the new behavior for free.
- The Bot API webhook path (`/webhook/{ws}` → `process_lead_update`) — same.
- The `vip_marker_phrases` Workspace column and seeder — unchanged.

## Slice 1 — Source schema foundation

### Schema

```sql
ALTER TABLE contacts ADD COLUMN entry_path VARCHAR(64);   -- nullable, default NULL
ALTER TABLE contacts ADD COLUMN source_tag VARCHAR(255);  -- nullable, default NULL
ALTER TABLE workspaces ADD COLUMN last_backfill_at TIMESTAMP;
ALTER TABLE workspaces ADD COLUMN last_backfill_summary TEXT;
```

Plus a tiny key-value `app_meta` table to track one-time migrations:

```sql
CREATE TABLE IF NOT EXISTS app_meta (
    key   VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

All four `ALTER`s and the `CREATE` go into `_ensure_columns()` in `backend/app/database/__init__.py` (the existing pattern — no Alembic). The `app_meta` create uses `IF NOT EXISTS` so dev DBs are safe.

### `entry_path` controlled vocabulary

| Value | Set by | Meaning |
|---|---|---|
| `legacy_pre_attribution` | One-time migration (this spec) | Existed before attribution tracking was deployed. |
| `landing_page` | Spec B | Joined via a campaign-specific invite link. |
| `public_channel` | Spec B | Joined via the static channel link, no campaign attribution. |
| `affiliate` | Spec B | Joined via an affiliate's invite link. |
| `direct` | Spec B | DM'd the bot directly without going through the channel. |
| `unknown` | Spec B fallback | Attribution genuinely couldn't be resolved. |
| `NULL` | Default for new rows post-Spec-A | Awaiting Spec B's claim hook. |

This spec only writes `legacy_pre_attribution` (during migration). All other values arrive in Spec B.

### Passive `source_tag` populator

`extract_start_source` already pulls `<param>` from `/start <param>` messages. This spec wires it to write `source_tag` (and continues mirroring to the legacy `source` column for one stable week, matching the deprecation cadence in the Non-goals). No semantic change — it was always a campaign tag; we're just renaming its destination.

In `ensure_contact` (both branches):
```python
if source is not None:
    contact.source_tag = source
    contact.source = source        # legacy mirror
```

In `services/telethon_client.py:163-164` (the analogous block):
```python
if source and not contact.source_tag:
    contact.source_tag = source
    contact.source = source
```

### One-time legacy migration

Lives in `backend/app/database/__init__.py`, runs after `_ensure_columns()` completes, guarded by an `app_meta` row:

```python
def _run_legacy_attribution_migration_v1(conn) -> None:
    """
    Idempotent. Marks all rows with NULL entry_path as legacy_pre_attribution,
    carries forward Contact.source into Contact.source_tag, and best-effort
    scans message history for any /start <payload> to recover lost source_tags.
    """
    if _get_app_meta(conn, "legacy_attribution_v1") == "done":
        return

    # Step 1: carry source forward into source_tag
    conn.execute(
        "UPDATE contacts SET source_tag = source "
        "WHERE source_tag IS NULL AND source IS NOT NULL"
    )

    # Step 2: tag every untouched contact as legacy_pre_attribution
    conn.execute(
        "UPDATE contacts SET entry_path = 'legacy_pre_attribution' "
        "WHERE entry_path IS NULL"
    )

    # Step 3: best-effort /start payload recovery
    rows = conn.execute(
        "SELECT id FROM contacts WHERE source_tag IS NULL"
    ).fetchall()
    pattern = re.compile(r"^/start\s+(\S+)", re.IGNORECASE)
    for (contact_id,) in rows:
        msgs = conn.execute(
            "SELECT message_text FROM messages "
            "WHERE user_id = :id AND direction = 'inbound' "
            "ORDER BY timestamp DESC",
            {"id": contact_id},
        ).fetchall()
        for (text,) in msgs:
            m = pattern.match(text or "")
            if m:
                conn.execute(
                    "UPDATE contacts SET source_tag = :tag WHERE id = :id",
                    {"tag": m.group(1), "id": contact_id},
                )
                break  # most-recent payload wins (we ordered DESC)

    _set_app_meta(conn, "legacy_attribution_v1", "done")
```

Notes:
- `_get_app_meta` / `_set_app_meta` are tiny helpers added in the same file.
- All three steps are idempotent. Crashing partway through and rebooting just retries — the flag is only set after step 3.
- Step 3 is a Python loop, not pure SQL, because SQLite's regex support is optional and Postgres's syntax is different. The loop runs once at deploy time on a few hundred contacts; performance is fine.
- A startup log line records `tagged X contacts, recovered Y /start payloads in Zms`.

## Slice 2 — VIP-name re-detection

### The helper

`backend/app/services/pipeline.py` (new):

```python
import re
from typing import Optional
from sqlalchemy.orm import Session
from app.database.models import Contact, PipelineStage, StageHistory, Workspace
from app.services.classifier import classify_contact

_marker_re_cache: dict[tuple[str, ...], re.Pattern] = {}


def _compile_markers(markers: tuple[str, ...]) -> re.Pattern:
    if markers in _marker_re_cache:
        return _marker_re_cache[markers]
    escaped = [re.escape(m) for m in markers if m]
    if not escaped:
        pat = re.compile(r"(?!)")  # never matches
    else:
        pat = re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)
    _marker_re_cache[markers] = pat
    return pat


def name_matches_vip_marker(
    first_name: Optional[str], last_name: Optional[str], markers: list[str],
) -> Optional[str]:
    """Return the matched marker (lowercased) or None. Pure function."""
    if not markers:
        return None
    text = f"{first_name or ''} {last_name or ''}"
    pat = _compile_markers(tuple(markers))
    m = pat.search(text)
    return m.group(0).lower() if m else None


def maybe_promote_to_member_stage(
    contact: Contact, db: Session, *, moved_by: str = "name_marker",
) -> bool:
    """
    Promotion-only, forward-only. Returns True if a stage move happened.
    Idempotent: contacts already at or past member_stage are no-ops.
    """
    import json
    from datetime import datetime

    ws = db.query(Workspace).filter(Workspace.id == contact.workspace_id).first()
    if not ws or not ws.member_stage_id or not ws.vip_marker_phrases:
        return False

    try:
        markers = json.loads(ws.vip_marker_phrases) or []
    except Exception:
        return False

    matched = name_matches_vip_marker(contact.first_name, contact.last_name, markers)
    if not matched:
        return False

    member = db.query(PipelineStage).filter(
        PipelineStage.id == ws.member_stage_id,
    ).first()
    if not member:
        return False

    current = None
    if contact.current_stage_id:
        current = db.query(PipelineStage).filter(
            PipelineStage.id == contact.current_stage_id,
        ).first()
    current_pos = current.position if current else 0

    if current_pos >= member.position:
        return False  # never demote, never sidestep

    now = datetime.utcnow()
    from_stage_id = contact.current_stage_id
    contact.current_stage_id = member.id
    contact.current_stage = member.position    # legacy mirror
    contact.stage_entered_at = now
    db.add(StageHistory(
        contact_id=contact.id,
        from_stage_id=from_stage_id, to_stage_id=member.id,
        from_stage=current_pos or None, to_stage=member.position,
        moved_at=now, moved_by=moved_by, trigger_keyword=matched,
    ))
    contact.classification = classify_contact(
        db, contact.id, contact.source_tag or contact.source, existing=contact,
    )
    db.commit()
    return True
```

### Call sites

**`handlers/leads.py` — `_initial_stage_for_contact`:**
Replace the inline `any(m for m in markers if m and m.lower() in full)` substring check (line 149) with a call to the pure helper `name_matches_vip_marker(first_name, last_name, markers)`. If it returns a truthy match AND `ws.member_stage_id` resolves to a real stage, return that stage's `(id, position, now)` tuple. Otherwise fall through to the lowest-position-stage path. Function's return shape is unchanged. No call to the side-effecting `maybe_promote_to_member_stage` here — the contact doesn't exist yet, so there's no `StageHistory` row to write.

**`handlers/leads.py` — `ensure_contact` update branch:**
The current code at lines 64-67 reassigns `first_name`/`last_name` directly. The change: compute a `name_changed` boolean *before* the assignment by comparing the inbound values to the contact's current attributes, then call the helper *after* the assignment so the helper sees the new name. Concretely:

```python
# (in the `if contact:` branch of ensure_contact, replacing lines 64-67)
name_changed = (
    (first_name is not None and first_name != contact.first_name) or
    (last_name  is not None and last_name  != contact.last_name)
)
if first_name is not None:
    contact.first_name = first_name
if last_name is not None:
    contact.last_name = last_name
# ...source/source_tag assignment here, unchanged...
if name_changed:
    from app.services.pipeline import maybe_promote_to_member_stage
    maybe_promote_to_member_stage(contact, db)
```

The `name_changed` micro-optimisation avoids re-running the regex + workspace lookup on every inbound message when the name hasn't actually moved.

**`services/backfill.py` — per-dialog loop:**
After `ensure_contact` returns and the contact is re-fetched (`backfill.py:64-68`), call `maybe_promote_to_member_stage(contact, db)` once before the `iter_messages` loop. `advance_stage` calls during message replay will see the promoted stage and respect the no-backwards rule.

### Audit trail and re-classification

- Every promotion writes a `StageHistory` row with `moved_by="name_marker"` and `trigger_keyword=<the matched marker>`. The existing Stage History UI on the lead detail page will surface this without changes.
- `classify_contact` is called inline so `Contact.classification` flips to `"vip"` (because `member_stage` has `is_member_stage=True`).

### What is deliberately NOT done in this slice

- **No CAPI fire on name promotion.** CAPI only fires on transitions to `deposited_stage_id` (a separate flag from `member_stage_id`). The helper does not call `send_capi_conversion`.
- **No follow-up scheduling.** Existing logic in `leads.py:112` already skips follow-ups for contacts that land at member stage on creation; we mirror that by simply not calling `schedule_follow_ups_for_stage_id` from the helper.
- **No demotion.** If a marker disappears from the name, nothing happens. Operators demote manually via the existing stage-set button.

## Slice 3 — Backfill UI button

### Backend

No new endpoint. Two small additions:

1. `backfill_workspace_history` in `services/backfill.py` writes `last_backfill_at = now` and `last_backfill_summary = json.dumps({...})` on the `Workspace` row before returning.
2. The settings endpoint that the SettingsPage Telegram tab already consumes for workspace data includes the two new fields in its response. The implementation plan will identify the exact endpoint (likely `GET /settings/workspace`, since `PATCH /settings/workspace` is already the org-metadata setter from the recent refactor) and extend its serializer.

### Frontend

**Location:** `frontend/src/pages/SettingsPage.tsx`, Telegram tab. Add a new card below the existing Telethon connection block.

**Visibility:** rendered only if the JWT's `role` is `admin` or `developer` (matches the gating used elsewhere on the page).

**State:**

```ts
const [syncing, setSyncing] = useState(false);
const [lastBackfill, setLastBackfill] = useState<{
  at: string | null;
  summary: { contacts_created: number; messages_replayed: number; skipped: number } | null;
}>({ at: null, summary: null });
```

`lastBackfill` is hydrated from the existing settings fetch on mount.

**Behaviour:**

| State | UI |
|---|---|
| Telethon disconnected | Button disabled. Tooltip: "Connect Telegram first." |
| Idle | Button enabled. Subtitle: `Last run: <ago> — N contacts, M messages` (or `Last run: never`). |
| In flight | Button disabled, label `Syncing…`, spinner. 5-minute client timeout. |
| Success | Toast `Synced: N contacts, M messages, K skipped`. Update `lastBackfill` from response. |
| Server returned `{error: "no telethon..."}` | Toast `Connect your Telegram account first`. |
| HTTP error | Toast with status + body. |

**API call:**

```ts
const res = await fetch(
  `${API_BASE}/workspaces/${workspaceId}/backfill-telegram-history?limit_per_dialog=500`,
  {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(5 * 60 * 1000),
  },
);
```

`workspaceId` is read from the existing auth helper (it's already in the JWT).

### What is deliberately NOT done in this slice

- No streaming progress, no abort button, no automatic retry.
- No auto-trigger from the onboarding wizard. Walid presses the button manually.

## Error handling summary

| Scenario | Behavior |
|---|---|
| Empty `vip_marker_phrases` JSON | Helper returns False silently. Feature is a no-op for that workspace. |
| Malformed `vip_marker_phrases` JSON | Log warning, return False. |
| Workspace has no `member_stage_id` | Helper returns False silently. |
| `member_stage_id` points at a deleted stage | Log warning, return False. |
| Migration crashes partway | `app_meta` flag never set; reboot retries. All steps are idempotent. |
| Backfill button: Telethon disconnected | Button disabled with tooltip; endpoint also returns `{error}` defensively. |
| Backfill button: server 5xx | Toast surfaces the error; no client state mutated. |
| Backfill button: client 5-minute timeout | Toast `Sync took too long — check status manually.` (Server keeps running.) |
| Backfill button: double click | Disabled-while-running guard prevents reentry. Server-side concurrent runs are safe (`ensure_contact` is upsert, `advance_stage` enforces no-backwards). |

## Testing

Three new test files under `backend/tests/`. Existing test infrastructure uses in-memory SQLite via the `pytest` conftest pattern.

### `test_vip_name_promotion.py`

- `test_word_boundary_match` — `"Mike VIP"` matches; `"Vipul"` doesn't; `"Sarah (vip)"` matches; `"VIP"` alone matches; `"vipassana"` doesn't.
- `test_promotion_forward_only` — lead at position 1 with VIP marker → promoted; lead at position 8 → unchanged; lead already at member_stage → unchanged.
- `test_no_demotion_on_marker_removal` — lead at member_stage gets renamed to remove the marker → stays at member_stage.
- `test_no_markers_configured` — workspace with empty `vip_marker_phrases` → no-op for any name.
- `test_no_member_stage_id` — workspace without `member_stage_id` → no-op even with matching name.
- `test_writes_stage_history_with_marker` — `StageHistory` row has `moved_by="name_marker"` and `trigger_keyword=<matched marker>`.
- `test_classification_updates` — after promotion, `contact.classification == "vip"`.
- `test_idempotent_double_call` — calling the helper twice produces only one `StageHistory` row.

### `test_ensure_contact_rename_promotion.py`

- `test_rename_to_vip_promotes_existing_contact` — create contact at stage 1; call `ensure_contact` again with `first_name="VIP Mike"`; assert stage = member_stage, history row present.
- `test_rename_with_no_change_skips_promotion_check` — call twice with same name, second call doesn't write a duplicate `StageHistory` row.
- `test_rename_loses_marker_does_not_demote` — contact at member_stage, called with `first_name="Mike"` (no marker), stays at member_stage.
- `test_backfill_loop_promotes_per_contact` — feed mock Telethon dialogs through `backfill_workspace_history`; promoted contacts have correct stage + history rows.

### `test_legacy_attribution_migration.py`

- `test_idempotent` — run migration twice, second run is a no-op (flag short-circuits).
- `test_tags_legacy_rows` — pre-existing contacts with `entry_path IS NULL` get `entry_path="legacy_pre_attribution"`.
- `test_recovers_start_payload_from_history` — contact has `/start meta_old_campaign` in inbound messages → migration sets `source_tag="meta_old_campaign"`.
- `test_carries_forward_existing_source` — contact with `source="x"` and `source_tag IS NULL` → migration sets `source_tag="x"`.
- `test_does_not_overwrite_populated_source_tag` — contact with `source_tag="y"` already → migration leaves it.
- `test_handles_bare_start_command` — `/start` with no payload → ignored.
- `test_most_recent_start_payload_wins` — multiple historical `/start` payloads → newest wins.

### What is deliberately NOT tested

- No load tests (Walid has hundreds of contacts).
- No live-Telegram integration tests (existing suite mocks Telethon).
- No frontend Vitest test for the backfill button (no precedent in the project; over-investment for one button).

## Migration / deployment notes

1. Deploy backend. On first boot:
   - `_ensure_columns` adds the four new columns + `app_meta` table.
   - `_run_legacy_attribution_migration_v1` runs once. Look for the `Legacy attribution migration: tagged X contacts, recovered Y /start payloads in Zms` log line.
2. Deploy frontend. The new "Sync Telegram history" card appears in Settings → Telegram for `admin`/`developer` users.
3. Walid (or whoever connects Telegram) presses **Sync Telegram history** once after the deploy — this rebuilds historical stages with the new VIP-name detection applied.
4. From this point forward, any rename to include a VIP marker promotes that contact to member stage on the lead's next message.

No data is destroyed. The legacy `Contact.source` column stays for one stable week, after which a follow-up cleanup PR drops it (mirrors how the project handled the legacy `Contact.current_stage` int).

## Open questions

None — all six clarifying questions resolved during brainstorming. The locked decisions are listed inline above.
