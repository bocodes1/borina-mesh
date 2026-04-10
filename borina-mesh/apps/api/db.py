"""Database engine + session management."""

import os
import sqlite3
from sqlmodel import create_engine, SQLModel, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./borina.db")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)


def _run_migrations(db_path: str) -> None:
    """Apply idempotent column migrations for schema upgrades on existing DBs."""
    migrations = [
        # Phase 5 tables (columns for upgrading existing DBs)
        ("morningbrief", "cost_summary", "TEXT DEFAULT ''"),
        ("morningbrief", "total_runs", "INTEGER DEFAULT 0"),
        ("morningbrief", "total_cost_usd", "REAL DEFAULT 0.0"),
        ("chatmessage", "job_id", "INTEGER"),
        ("agenttask", "output_data", "TEXT"),
        ("agenttask", "completed_at", "TEXT"),
        ("agentworkspace", "workspace_id", "TEXT"),
    ]
    conn = sqlite3.connect(db_path)
    try:
        for table, column, col_type in migrations:
            try:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            except sqlite3.OperationalError:
                # Column already exists or table doesn't exist yet — safe to skip
                pass
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables and run migrations. Safe to call multiple times."""
    SQLModel.metadata.create_all(engine)

    # Run column migrations for existing DBs (idempotent)
    if "sqlite" in DATABASE_URL:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        if db_path:
            _run_migrations(db_path)


def get_session():
    """FastAPI dependency for database sessions."""
    with Session(engine) as session:
        yield session
