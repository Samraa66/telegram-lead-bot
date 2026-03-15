"""
Database connection and session management.

Uses PostgreSQL when DATABASE_URL is set (production), otherwise falls back
to SQLite for local development. Exposes engine, SessionLocal, init_db, get_db.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

# Use DATABASE_URL if set (PostgreSQL); otherwise SQLite for local dev
_db_url = os.getenv("DATABASE_URL", "").strip()
if not _db_url:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sqlite_path = os.path.join(base_dir, "leadbot.db")
    _db_url = f"sqlite:///{sqlite_path}"

if _db_url.startswith("sqlite"):
    engine = create_engine(
        _db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(_db_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """
    Dependency that yields a DB session and ensures it is closed after use.
    Use with FastAPI's Depends().
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
