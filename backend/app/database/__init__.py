"""
Database connection, session management, and startup migrations.

Uses PostgreSQL when DATABASE_URL is set (production), otherwise falls back
to SQLite for local development.

Migration order in init_db():
  1. Rename `users` → `contacts` if the old table still exists (both dialects).
  2. create_all() — creates any missing tables (contacts, follow_up_queue,
     follow_up_templates, stage_history).
  3. _ensure_columns() — adds new columns to existing installs without dropping data.
  4. _seed_templates() — populates follow_up_templates on first run.
"""

import os
from pathlib import Path
from typing import Iterable, Tuple

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect, text

# Load .env before reading DATABASE_URL — database/__init__.py is often imported
# before config.py, so we must call load_dotenv() here as well.
load_dotenv(Path(__file__).parent.parent.parent / ".env")
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base, FollowUpTemplate, Workspace, StageKeyword, StageLabel, QuickReply, TeamMember

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

    if _table_exists("workspaces"):
        existing_ws = _existing_columns("workspaces")
        ws_needed = [
            ("meta_access_token", "TEXT"),
            ("meta_ad_account_id", "TEXT"),
            ("meta_pixel_id", "TEXT"),
            ("bot_token", "TEXT"),
            ("webhook_secret", "TEXT"),
            ("telethon_session", "TEXT"),
        ]
        for col, ddl in ws_needed:
            if col not in existing_ws:
                _add_column("workspaces", col, ddl)

    if _table_exists("campaigns"):
        existing_campaigns = _existing_columns("campaigns")
        if "workspace_id" not in existing_campaigns:
            _add_column("campaigns", "workspace_id", "INTEGER DEFAULT 1")

    if _table_exists("team_members"):
        existing_team = _existing_columns("team_members")
        team_needed = [
            ("auth_type", "TEXT NOT NULL DEFAULT 'password'"),
            ("telegram_id", "BIGINT"),
        ]
        for col, ddl in team_needed:
            if col not in existing_team:
                _add_column("team_members", col, ddl)

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
        # Credential columns (same DDL for both dialects)
        affiliates_needed += [
            ("login_username", "TEXT"),
            ("login_password_hash", "TEXT"),
        ]
        existing_affiliates = _existing_columns("affiliates")
        for col, ddl in affiliates_needed:
            if col not in existing_affiliates:
                _add_column("affiliates", col, ddl)


# ---------------------------------------------------------------------------
# Template seeding
# ---------------------------------------------------------------------------

_TEMPLATE_SEEDS = [
    (1, 1, "Hey, just checking in - happy to answer any questions!"),
    (1, 2, "Still here whenever you're ready. No pressure at all."),
    (2, 1, "Did you get a chance to think about your trading experience?"),
    (3, 1, "Hey, wanted to follow up - is there anything holding you back?"),
    (3, 2, "Still thinking it over? I'm here whenever you're ready."),
    (4, 1, "Quick check - did you manage to open your PuPrime account?"),
    (4, 2, "The account only takes a few minutes - want me to walk you through it?"),
    (4, 3, "Last nudge on the account - let me know if you hit any snags."),
    (5, 1, "You're almost there - any issues with the setup?"),
    (5, 2, "Let me know if you need help finishing the setup."),
    (6, 1, "How's the setup going? Happy to answer any questions."),
    (6, 2, "Just making sure everything went smoothly - any questions?"),
    (7, 1, "Welcome again! Let me know if you need anything."),
    (7, 2, "How are you finding the VIP signals so far?"),
    (7, 3, "Checking in - really happy to have you in the room!"),
]


def _seed_templates() -> None:
    """Populate follow_up_templates with placeholder texts if the table is empty."""
    db = SessionLocal()
    try:
        if db.query(FollowUpTemplate).count() > 0:
            return
        for stage, seq, text_body in _TEMPLATE_SEEDS:
            db.add(FollowUpTemplate(workspace_id=1, stage=stage, sequence_num=seq, message_text=text_body))
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Settings seeding (workspace 1 + hardcoded defaults)
# ---------------------------------------------------------------------------

_KEYWORD_SEEDS: list[tuple[str, int]] = [
    ("any experience trading", 2),
    ("is there something specific holding you back", 3),
    ("your link to open your free puprime account", 4),
    ("the hard part done", 5),
    ("exactly how to get set up", 6),
    ("welcome to the vip room", 7),
    ("really happy to have you here", 8),
]

_STAGE_LABEL_SEEDS: list[tuple[int, str]] = [
    (1, "New Lead"),
    (2, "Qualified"),
    (3, "Hesitant / Ghosting"),
    (4, "Link Sent"),
    (5, "Account Created"),
    (6, "Deposit Intent"),
    (7, "Deposited"),
    (8, "VIP Member"),
]

_QUICK_REPLY_SEEDS: list[tuple[int, str, str]] = [
    (1, "Qualify",      "Hey! Quick question — do you have any experience trading, or is this something new for you? 😊"),
    (1, "Re-engage",    "Hey, hope you're well! Just circling back — do you have any experience trading before?"),
    (2, "Objection",    "Totally understand! Is there something specific holding you back from getting started?"),
    (2, "Probe",        "Makes sense. Is there something specific holding you back right now that I can help with?"),
    (3, "Send link",    "Here's your link to open your free PuPrime account — takes about 2 minutes! 👇"),
    (3, "Re-send link", "Sending over your link to open your free PuPrime account again in case you missed it 🔗"),
    (4, "Confirm done", "Amazing — looks like you've got the hard part done! 🎉 Let me know once you're in and I'll sort your access."),
    (4, "Check in",     "Hey! Just checking in — is the hard part done with the account setup? Happy to help if you're stuck!"),
    (5, "Setup guide",  "Perfect! Let me walk you through exactly how to get set up with the signals 📊"),
    (5, "Next steps",   "Great news! I'll show you exactly how to get set up from here — just follow these steps 👇"),
    (6, "VIP access",   "Welcome to the VIP room! You're officially in 🔥 Here's everything you need to know to get started..."),
    (6, "VIP entry",    "Welcome to the vip room — so pumped to have you here! Let's get you fully set up 🚀"),
    (7, "Welcome",      "Really happy to have you here with us! Here's what to expect going forward 🙌"),
    (7, "Onboard",      "I'm really happy to have you here — let's make sure you're getting the most out of everything!"),
]


def seed_workspace_defaults(workspace_id: int, db) -> None:
    """
    Seed keywords, stage labels, quick replies, and follow-up templates for a workspace.
    Safe to call on existing workspaces — skips tables that already have data.
    """
    if db.query(StageKeyword).filter(StageKeyword.workspace_id == workspace_id).count() == 0:
        for kw, stage in _KEYWORD_SEEDS:
            db.add(StageKeyword(workspace_id=workspace_id, keyword=kw, target_stage=stage, is_active=True))
        db.commit()

    if db.query(StageLabel).filter(StageLabel.workspace_id == workspace_id).count() == 0:
        for stage_num, label in _STAGE_LABEL_SEEDS:
            db.add(StageLabel(workspace_id=workspace_id, stage_num=stage_num, label=label))
        db.commit()

    if db.query(QuickReply).filter(QuickReply.workspace_id == workspace_id).count() == 0:
        for i, (stage_num, label, text) in enumerate(_QUICK_REPLY_SEEDS):
            db.add(QuickReply(workspace_id=workspace_id, stage_num=stage_num, label=label, text=text, sort_order=i))
        db.commit()

    if db.query(FollowUpTemplate).filter(FollowUpTemplate.workspace_id == workspace_id).count() == 0:
        for stage, seq, text_body in _TEMPLATE_SEEDS:
            db.add(FollowUpTemplate(workspace_id=workspace_id, stage=stage, sequence_num=seq, message_text=text_body))
        db.commit()


def _seed_workspace() -> None:
    """Create workspace id=1 if it does not exist."""
    db = SessionLocal()
    try:
        if db.query(Workspace).filter(Workspace.id == 1).first():
            return
        db.add(Workspace(id=1, name="Default"))
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

def _promote_vip_names() -> None:
    """
    One-time migration: contacts whose name contains 'VIP' (case-insensitive)
    but are below stage 7 are promoted to stage 7.
    """
    from app.database.models import Contact, StageHistory
    db = SessionLocal()
    try:
        contacts = db.query(Contact).filter(Contact.current_stage < 7).all()
        now = __import__("datetime").datetime.utcnow()
        promoted = 0
        for c in contacts:
            full = f"{c.first_name or ''} {c.last_name or ''}".lower()
            if "vip" in full:
                old_stage = c.current_stage or 1
                c.current_stage = 7
                c.stage_entered_at = now
                db.add(StageHistory(
                    contact_id=c.id,
                    from_stage=old_stage,
                    to_stage=7,
                    moved_at=now,
                    moved_by="system",
                    trigger_keyword="vip_name_detected",
                ))
                promoted += 1
        if promoted:
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _sync_classifications() -> None:
    """
    Re-classify all contacts based on current stage and flags.
    Runs on startup to fix any contacts whose classification drifted.
    Skips noise and affiliate contacts (those are explicitly set).
    """
    db = SessionLocal()
    try:
        from app.database.models import Contact as C
        contacts = db.query(C).filter(
            C.classification.notin_(["noise", "affiliate"])
        ).all()
        for contact in contacts:
            stage = contact.current_stage or 1
            if contact.deposit_confirmed or stage >= 7:
                new_cls = "vip"
            elif stage >= 2:
                new_cls = "warm_lead"
            else:
                new_cls = "new_lead"
            if contact.classification != new_cls:
                contact.classification = new_cls
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def init_db() -> None:
    """
    Migrate schema and initialise tables on startup.

    Step 1: rename users → contacts (must happen before create_all so SQLAlchemy
            finds 'contacts' and does not try to recreate it).
    Step 2: create_all — creates any still-missing tables.
    Step 3: ensure new columns exist (older deployments).
    Step 4: seed follow_up_templates.
    Step 5: sync classifications.
    """
    _migrate_users_to_contacts()
    Base.metadata.create_all(bind=engine)
    try:
        _ensure_columns()
    except Exception:
        pass
    _seed_templates()
    try:
        _seed_workspace()
        _seed_settings()
    except Exception:
        pass
    try:
        _promote_vip_names()
    except Exception:
        pass
    try:
        _sync_classifications()
    except Exception:
        pass


def get_db():
    """FastAPI dependency: yield a DB session and close after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
