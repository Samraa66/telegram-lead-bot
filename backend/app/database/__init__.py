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

from .models import Base, FollowUpTemplate

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


# ---------------------------------------------------------------------------
# Template seeding
# ---------------------------------------------------------------------------

_TEMPLATE_SEEDS = [
    (1, 1, "[Stage 1 / Follow-up 1] Hey, just checking in — happy to answer any questions!"),
    (1, 2, "[Stage 1 / Follow-up 2] Still here whenever you're ready. No pressure at all."),
    (2, 1, "[Stage 2 / Follow-up 1] Did you get a chance to think about your trading experience?"),
    (3, 1, "[Stage 3 / Follow-up 1] Hey, wanted to follow up — is there anything holding you back?"),
    (3, 2, "[Stage 3 / Follow-up 2] Still thinking it over? I'm here whenever you're ready."),
    (4, 1, "[Stage 4 / Follow-up 1] Quick check — did you manage to open your PuPrime account?"),
    (4, 2, "[Stage 4 / Follow-up 2] The account only takes a few minutes — want me to walk you through it?"),
    (4, 3, "[Stage 4 / Follow-up 3] Last nudge on the account — let me know if you hit any snags."),
    (5, 1, "[Stage 5 / Follow-up 1] You're almost there — any issues with the setup?"),
    (5, 2, "[Stage 5 / Follow-up 2] Let me know if you need help finishing the setup."),
    (6, 1, "[Stage 6 / Follow-up 1] How's the setup going? Happy to answer any questions."),
    (6, 2, "[Stage 6 / Follow-up 2] Just making sure everything went smoothly — any questions?"),
    (7, 1, "[Stage 7 / Follow-up 1] Welcome again! Let me know if you need anything."),
    (7, 2, "[Stage 7 / Follow-up 2] How are you finding the VIP signals so far?"),
    (7, 3, "[Stage 7 / Follow-up 3] Checking in — really happy to have you in the room!"),
]


def _seed_templates() -> None:
    """Populate follow_up_templates with placeholder texts if the table is empty."""
    db = SessionLocal()
    try:
        if db.query(FollowUpTemplate).count() > 0:
            return
        for stage, seq, text_body in _TEMPLATE_SEEDS:
            db.add(FollowUpTemplate(stage=stage, sequence_num=seq, message_text=text_body))
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
            else:
                new_cls = "warm_lead"
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
