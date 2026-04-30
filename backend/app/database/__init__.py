"""
Database connection, session management, and startup migrations.

Uses PostgreSQL when DATABASE_URL is set (production), otherwise falls back
to SQLite for local development.

Migration order in init_db():
  1. Rename `users` → `contacts` if the old table still exists (both dialects).
  2. create_all() — creates any missing tables (contacts, follow_up_queue,
     follow_up_templates, stage_history).
  3. _ensure_columns() — adds new columns to existing installs without dropping data.
  4. seed_workspace_defaults(1, db) — seeds the default pipeline template for workspace 1.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect, text

# Load .env before reading DATABASE_URL — database/__init__.py is often imported
# before config.py, so we must call load_dotenv() here as well.
load_dotenv(Path(__file__).parent.parent.parent / ".env")
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base, Organization, Workspace

# Use DATABASE_URL if set (PostgreSQL); otherwise SQLite for local dev
_db_url = os.getenv("DATABASE_URL", "").strip()
if not _db_url:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sqlite_path = os.path.join(base_dir, "leadbot.db")
    _db_url = f"sqlite:///{sqlite_path}"

if _db_url.startswith("sqlite"):
    # SQLite notes:
    # - Use WAL + busy_timeout to reduce "database is locked" under concurrent writes
    #   (webhook/API + scheduler).
    # - Avoid StaticPool for file-based DBs because it forces one shared connection.
    # - Keep StaticPool only for in-memory sqlite where one shared connection is needed.
    is_memory = _db_url in ("sqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:")
    if is_memory:
        engine = create_engine(
            _db_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(
            _db_url,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.close()
else:
    engine = create_engine(_db_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _table_exists(table_name: str) -> bool:
    return inspect(engine).has_table(table_name)


def _existing_columns(table_name: str) -> set:
    """Return set of existing column names for a table."""
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with engine.connect() as conn:
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        return {r[1] for r in rows}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
            ),
            {"t": table_name},
        ).fetchall()
    return {r[0] for r in rows}


def _add_column(table_name: str, col_name: str, col_ddl: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_ddl}"))
        conn.commit()


def _get_app_meta(conn, key: str):
    """Read a single value from the app_meta KV table. Returns None if missing."""
    row = conn.execute(
        text("SELECT value FROM app_meta WHERE key = :k"),
        {"k": key},
    ).fetchone()
    return row[0] if row else None


def _set_app_meta(conn, key: str, value: str) -> None:
    """Insert or update a key in app_meta. SQLite + Postgres both speak the same upsert dialect here."""
    conn.execute(
        text(
            "INSERT INTO app_meta (key, value, updated_at) "
            "VALUES (:k, :v, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP"
        ),
        {"k": key, "v": value},
    )
    conn.commit()


import re as _re_module

_START_PAYLOAD_RE = _re_module.compile(r"^/start\s+(\S+)", _re_module.IGNORECASE)


def _run_legacy_attribution_migration_v1(conn) -> None:
    """
    One-time migration. Tags all rows with NULL entry_path as
    'legacy_pre_attribution', carries Contact.source forward into
    Contact.source_tag, and best-effort recovers historical
    /start <payload> from message history.

    Idempotent: gated by app_meta['legacy_attribution_v1'] == 'done'.
    Safe to retry — every step is conditional on its target column being NULL.
    """
    import time
    if _get_app_meta(conn, "legacy_attribution_v1") == "done":
        return

    t0 = time.monotonic()

    # Step 1: carry source forward into source_tag where source_tag is NULL
    conn.execute(text(
        "UPDATE contacts SET source_tag = source "
        "WHERE source_tag IS NULL AND source IS NOT NULL"
    ))

    # Step 2: tag every row that doesn't yet have an entry_path
    tagged = conn.execute(text(
        "UPDATE contacts SET entry_path = 'legacy_pre_attribution' "
        "WHERE entry_path IS NULL"
    )).rowcount or 0

    # Step 3: best-effort /start payload recovery for rows where source_tag is still NULL
    rows = conn.execute(text(
        "SELECT id FROM contacts WHERE source_tag IS NULL"
    )).fetchall()
    recovered = 0
    for (contact_id,) in rows:
        msgs = conn.execute(
            text(
                "SELECT message_text FROM messages "
                "WHERE user_id = :id AND direction = 'inbound' "
                "ORDER BY timestamp DESC"
            ),
            {"id": contact_id},
        ).fetchall()
        for (text_val,) in msgs:
            if not text_val:
                continue
            m = _START_PAYLOAD_RE.match(text_val)
            if m:
                conn.execute(
                    text("UPDATE contacts SET source_tag = :tag WHERE id = :id"),
                    {"tag": m.group(1), "id": contact_id},
                )
                recovered += 1
                break

    conn.commit()
    _set_app_meta(conn, "legacy_attribution_v1", "done")

    import logging
    logging.getLogger(__name__).info(
        "Legacy attribution migration: tagged %d contacts, recovered %d /start payloads in %dms",
        tagged, recovered, int((time.monotonic() - t0) * 1000),
    )


# ---------------------------------------------------------------------------
# Migration: users → contacts
# ---------------------------------------------------------------------------

def _migrate_users_to_contacts() -> None:
    """
    If the legacy `users` table exists and `contacts` does not, rename it.

    Both PostgreSQL and SQLite 3.25+ support ALTER TABLE … RENAME TO.
    In PostgreSQL, FK constraints tracking the table by OID remain valid after rename.
    """
    if not _table_exists("users") or _table_exists("contacts"):
        return
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users RENAME TO contacts"))
        conn.commit()


# ---------------------------------------------------------------------------
# Column migrations (forward-compat for older deployments)
# ---------------------------------------------------------------------------

def _ensure_columns() -> None:
    """Add any new columns that may be missing from an older deployment."""
    dialect = engine.dialect.name

    if dialect == "sqlite":
        contacts_needed = [
            ("classification", "TEXT"),
            ("current_stage", "INTEGER DEFAULT 1"),
            ("stage_entered_at", "TIMESTAMP"),
            ("notes", "TEXT"),
            ("deposit_confirmed", "INTEGER DEFAULT 0"),
            ("deposit_date", "DATE"),
            ("is_affiliate", "INTEGER DEFAULT 0"),
            ("escalated", "INTEGER DEFAULT 0"),
            ("escalated_at", "TIMESTAMP"),
            ("first_name", "TEXT"),
            ("last_name", "TEXT"),
            ("activity_status", "TEXT"),
            ("workspace_id", "INTEGER DEFAULT 1"),
            # Task 1.5 columns
            ("current_stage_id", "INTEGER"),
            ("deposit_status", "TEXT NOT NULL DEFAULT 'none'"),
            ("deposited_at", "TIMESTAMP"),
            ("deposit_amount", "REAL"),
            ("deposit_currency", "TEXT"),
            ("deposit_source", "TEXT"),
            ("puprime_client_id", "TEXT"),
            ("source_tag", "TEXT"),
            ("entry_path", "TEXT"),
        ]
    else:
        contacts_needed = [
            ("classification", "VARCHAR(50)"),
            ("current_stage", "INTEGER DEFAULT 1"),
            ("stage_entered_at", "TIMESTAMP"),
            ("notes", "TEXT"),
            ("deposit_confirmed", "BOOLEAN DEFAULT FALSE"),
            ("deposit_date", "DATE"),
            ("is_affiliate", "BOOLEAN DEFAULT FALSE"),
            ("escalated", "BOOLEAN DEFAULT FALSE"),
            ("escalated_at", "TIMESTAMP"),
            ("first_name", "VARCHAR(255)"),
            ("last_name", "VARCHAR(255)"),
            ("activity_status", "VARCHAR(20)"),
            ("workspace_id", "INTEGER DEFAULT 1"),
            # Task 1.5 columns
            ("current_stage_id", "INTEGER"),
            ("deposit_status", "VARCHAR(20) NOT NULL DEFAULT 'none'"),
            ("deposited_at", "TIMESTAMP"),
            ("deposit_amount", "NUMERIC(18,4)"),
            ("deposit_currency", "VARCHAR(8)"),
            ("deposit_source", "VARCHAR(20)"),
            ("puprime_client_id", "VARCHAR(255)"),
            ("source_tag", "VARCHAR(255)"),
            ("entry_path", "VARCHAR(64)"),
        ]

    messages_needed = [
        ("direction", "TEXT"),
        ("content", "TEXT"),
        ("sender", "TEXT"),
    ]

    existing_contacts = _existing_columns("contacts")
    for col, ddl in contacts_needed:
        if col not in existing_contacts:
            _add_column("contacts", col, ddl)

    existing_messages = _existing_columns("messages")
    for col, ddl in messages_needed:
        if col not in existing_messages:
            _add_column("messages", col, ddl)

    if _table_exists("follow_up_templates"):
        existing_fut = _existing_columns("follow_up_templates")
        if "workspace_id" not in existing_fut:
            if dialect == "sqlite":
                _add_column("follow_up_templates", "workspace_id", "INTEGER DEFAULT 1")
            else:
                _add_column("follow_up_templates", "workspace_id", "INTEGER DEFAULT 1")
        # Task 1.5 columns
        fut_needed: list[tuple[str, str]] = [
            ("stage_id", "INTEGER"),
            ("hours_offset", "REAL DEFAULT 24" if dialect == "sqlite" else "DOUBLE PRECISION DEFAULT 24"),
        ]
        for col, ddl in fut_needed:
            if col not in existing_fut:
                _add_column("follow_up_templates", col, ddl)

    if _table_exists("workspaces"):
        existing_ws = _existing_columns("workspaces")
        ws_needed = [
            ("meta_access_token", "TEXT"),
            ("meta_ad_account_id", "TEXT"),
            ("meta_pixel_id", "TEXT"),
            ("bot_token", "TEXT"),
            ("webhook_secret", "TEXT"),
            ("telethon_session", "TEXT"),
            # Org hierarchy
            ("org_id", "INTEGER DEFAULT 1"),
            ("parent_workspace_id", "INTEGER"),
            ("root_workspace_id", "INTEGER"),
            ("workspace_role", "TEXT DEFAULT 'owner'"),
            ("onboarding_complete", "BOOLEAN DEFAULT FALSE"),
            ("landing_page_url", "TEXT"),
            ("source_channel_id", "TEXT"),
            ("destination_channel_ids", "TEXT"),
            # Task 1.5 columns
            ("niche", "TEXT"),
            ("language", "TEXT"),
            ("timezone", "TEXT"),
            ("country", "TEXT"),
            ("main_channel_url", "TEXT"),
            ("sales_telegram_username", "TEXT"),
            ("deposited_stage_id", "INTEGER"),
            ("member_stage_id", "INTEGER"),
            ("conversion_stage_id", "INTEGER"),
            ("vip_marker_phrases", "TEXT"),
            ("deposit_webhook_secret", "TEXT"),
            ("last_backfill_at", "TIMESTAMP"),
            ("last_backfill_summary", "TEXT"),
            ("last_signal_forwarded_at", "TIMESTAMP"),
            ("attribution_channel_id", "BIGINT"),
        ]
        for col, ddl in ws_needed:
            if col not in existing_ws:
                _add_column("workspaces", col, ddl)
        # Backfill root_workspace_id for existing rows where it is NULL
        with engine.connect() as conn:
            conn.execute(text(
                "UPDATE workspaces SET root_workspace_id = id WHERE root_workspace_id IS NULL"
            ))
            conn.commit()

    if _table_exists("campaigns"):
        existing_campaigns = _existing_columns("campaigns")
        if "workspace_id" not in existing_campaigns:
            _add_column("campaigns", "workspace_id", "INTEGER DEFAULT 1")

    if _table_exists("team_members"):
        existing_team = _existing_columns("team_members")
        team_needed = [
            ("auth_type", "TEXT NOT NULL DEFAULT 'password'"),
            ("telegram_id", "BIGINT"),
            ("workspace_id", "INTEGER DEFAULT 1"),
        ]
        for col, ddl in team_needed:
            if col not in existing_team:
                _add_column("team_members", col, ddl)

    for tbl in ("stage_keywords", "stage_labels", "quick_replies"):
        if _table_exists(tbl):
            if "workspace_id" not in _existing_columns(tbl):
                _add_column(tbl, "workspace_id", "INTEGER DEFAULT 1")

    # Task 1.5: stage_keywords — target_stage_id
    if _table_exists("stage_keywords"):
        existing_sk = _existing_columns("stage_keywords")
        sk_needed: list[tuple[str, str]] = [
            ("target_stage_id", "INTEGER"),
        ]
        for col, ddl in sk_needed:
            if col not in existing_sk:
                _add_column("stage_keywords", col, ddl)

    # Task 1.5: quick_replies — stage_id
    if _table_exists("quick_replies"):
        existing_qr = _existing_columns("quick_replies")
        qr_needed: list[tuple[str, str]] = [
            ("stage_id", "INTEGER"),
        ]
        for col, ddl in qr_needed:
            if col not in existing_qr:
                _add_column("quick_replies", col, ddl)

    # Task 1.5: stage_history — from_stage_id, to_stage_id
    if _table_exists("stage_history"):
        existing_sh = _existing_columns("stage_history")
        sh_needed: list[tuple[str, str]] = [
            ("from_stage_id", "INTEGER"),
            ("to_stage_id", "INTEGER"),
        ]
        for col, ddl in sh_needed:
            if col not in existing_sh:
                _add_column("stage_history", col, ddl)

    # Task 1.5: follow_up_queue — stage_id
    if _table_exists("follow_up_queue"):
        existing_fuq = _existing_columns("follow_up_queue")
        fuq_needed: list[tuple[str, str]] = [
            ("stage_id", "INTEGER"),
        ]
        for col, ddl in fuq_needed:
            if col not in existing_fuq:
                _add_column("follow_up_queue", col, ddl)

    # pipeline_stages — placeholder guard for future column additions
    if _table_exists("pipeline_stages"):
        existing_ps = _existing_columns("pipeline_stages")
        ps_needed: list[tuple[str, str]] = []  # populated by future tasks
        for col, ddl in ps_needed:
            if col not in existing_ps:
                _add_column("pipeline_stages", col, ddl)

    if _table_exists("affiliates"):
        if dialect == "sqlite":
            affiliates_needed = [
                ("esim_done", "INTEGER DEFAULT 0"),
                ("free_channel_id", "TEXT"),
                ("free_channel_members", "INTEGER DEFAULT 0"),
                ("bot_setup_done", "INTEGER DEFAULT 0"),
                ("vip_channel_id", "TEXT"),
                ("vip_channel_members", "INTEGER DEFAULT 0"),
                ("tutorial_channel_id", "TEXT"),
                ("tutorial_channel_members", "INTEGER DEFAULT 0"),
                ("sales_scripts_done", "INTEGER DEFAULT 0"),
                ("ib_profile_id", "TEXT"),
                ("ads_live", "INTEGER DEFAULT 0"),
                ("pixel_setup_done", "INTEGER DEFAULT 0"),
            ]
        else:
            affiliates_needed = [
                ("esim_done", "BOOLEAN DEFAULT FALSE"),
                ("free_channel_id", "VARCHAR(100)"),
                ("free_channel_members", "INTEGER DEFAULT 0"),
                ("bot_setup_done", "BOOLEAN DEFAULT FALSE"),
                ("vip_channel_id", "VARCHAR(100)"),
                ("vip_channel_members", "INTEGER DEFAULT 0"),
                ("tutorial_channel_id", "VARCHAR(100)"),
                ("tutorial_channel_members", "INTEGER DEFAULT 0"),
                ("sales_scripts_done", "BOOLEAN DEFAULT FALSE"),
                ("ib_profile_id", "VARCHAR(255)"),
                ("ads_live", "BOOLEAN DEFAULT FALSE"),
                ("pixel_setup_done", "BOOLEAN DEFAULT FALSE"),
            ]
        # Credential + workspace columns (same DDL for both dialects)
        affiliates_needed += [
            ("login_username", "TEXT"),
            ("login_password_hash", "TEXT"),
            ("workspace_id", "INTEGER DEFAULT 1"),
            ("affiliate_workspace_id", "INTEGER"),
            # Invite-link flow: affiliate sets their own password on first use
            ("invite_token", "VARCHAR(64)"),
            ("invite_expires_at", "TIMESTAMP"),
        ]
        existing_affiliates = _existing_columns("affiliates")
        for col, ddl in affiliates_needed:
            if col not in existing_affiliates:
                _add_column("affiliates", col, ddl)

        # pending_channels — workspace scope for per-workspace detection
        pending_needed = [("workspace_id", "INTEGER")]
        existing_pending = _existing_columns("pending_channels")
        if existing_pending:  # table may not exist on first boot; models.create_all handles that
            for col, ddl in pending_needed:
                if col not in existing_pending:
                    _add_column("pending_channels", col, ddl)


# ---------------------------------------------------------------------------
# Settings seeding (workspace 1 + hardcoded defaults)
# ---------------------------------------------------------------------------


def seed_workspace_defaults(workspace_id: int, db) -> None:
    """Delegate to services.pipeline_seed.seed_default_pipeline."""
    from app.services.pipeline_seed import seed_default_pipeline
    seed_default_pipeline(workspace_id, db)


def _seed_organization() -> None:
    """Create organization id=1 if it does not exist."""
    db = SessionLocal()
    try:
        if db.query(Organization).filter(Organization.id == 1).first():
            return
        db.add(Organization(id=1, name="Default"))
        db.commit()
    finally:
        db.close()


def _seed_workspace() -> None:
    """Create workspace id=1 if it does not exist. Backfill org hierarchy on existing rows."""
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        if not ws:
            db.add(Workspace(
                id=1, name="Default",
                org_id=1, parent_workspace_id=None,
                root_workspace_id=1, workspace_role="owner",
            ))
            db.commit()
        else:
            # Backfill hierarchy fields if missing (existing installations)
            changed = False
            if ws.org_id is None:
                ws.org_id = 1
                changed = True
            if ws.root_workspace_id is None:
                ws.root_workspace_id = ws.id
                changed = True
            if ws.workspace_role is None:
                ws.workspace_role = "owner"
                changed = True
            if changed:
                db.commit()
    finally:
        db.close()


def _seed_settings() -> None:
    """Seed default settings for workspace 1 if tables are empty."""
    db = SessionLocal()
    try:
        seed_workspace_defaults(1, db)
    finally:
        db.close()




# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Migrate schema and initialise tables on startup.

    Step 1: rename users → contacts (must happen before create_all so SQLAlchemy
            finds 'contacts' and does not try to recreate it).
    Step 2: create_all — creates any still-missing tables.
    Step 3: ensure new columns exist (older deployments).
    Step 4: seed default pipeline template via seed_workspace_defaults.
    Step 5: sync classifications.
    """
    _migrate_users_to_contacts()
    Base.metadata.create_all(bind=engine)
    try:
        _ensure_columns()
    except Exception:
        pass
    try:
        with engine.connect() as conn:
            _run_legacy_attribution_migration_v1(conn)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("legacy_attribution_v1 migration failed: %s", e)
    try:
        _seed_organization()
        _seed_workspace()
        _seed_settings()
    except Exception:
        pass
    try:
        _encrypt_legacy_secrets()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("legacy-secret encryption pass failed: %s", e)


def _encrypt_legacy_secrets() -> None:
    """
    One-time pass: encrypt any plaintext sensitive columns on the workspaces
    table. Bypasses the ORM and writes already-encrypted values via raw UPDATE,
    because SQLAlchemy's mutation tracker treats `obj.col = obj.col` as a no-op
    and skips the flush — so going through the ORM doesn't actually persist.

    Idempotent: rows already prefixed with enc:v1: are skipped.
    """
    from app.services.crypto import ENC_PREFIX, encrypt
    from sqlalchemy import text as _text
    db = SessionLocal()
    try:
        rows = db.execute(_text(
            "SELECT id, bot_token, webhook_secret, telethon_session, meta_access_token "
            "FROM workspaces"
        )).fetchall()
        encrypted_count = 0
        for r in rows:
            updates: dict = {}
            if r[1] and not r[1].startswith(ENC_PREFIX): updates["bot_token"] = encrypt(r[1])
            if r[2] and not r[2].startswith(ENC_PREFIX): updates["webhook_secret"] = encrypt(r[2])
            if r[3] and not r[3].startswith(ENC_PREFIX): updates["telethon_session"] = encrypt(r[3])
            if r[4] and not r[4].startswith(ENC_PREFIX): updates["meta_access_token"] = encrypt(r[4])
            if updates:
                set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                db.execute(
                    _text(f"UPDATE workspaces SET {set_clause} WHERE id = :id"),
                    {"id": r[0], **updates},
                )
                encrypted_count += 1
        db.commit()
        if encrypted_count:
            import logging
            logging.getLogger(__name__).info(
                "Encrypted legacy plaintext secrets in %d workspace(s)", encrypted_count
            )
    finally:
        db.close()


def get_db():
    """FastAPI dependency: yield a DB session and close after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
