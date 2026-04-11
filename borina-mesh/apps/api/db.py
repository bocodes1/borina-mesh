"""Database engine + session management."""

import os
import sqlite3
from contextlib import contextmanager
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
        # Phase 4 migrations
        ("job", "kind", "TEXT DEFAULT 'agent_run'"),
        ("job", "repo_path", "TEXT"),
        ("job", "base_branch", "TEXT"),
        ("job", "worker_branch", "TEXT"),
        ("job", "worker_pid", "INTEGER"),
        ("job", "log_path", "TEXT"),
        ("job", "qa_verdict", "TEXT"),
        ("job", "qa_notes", "TEXT"),
        ("agentrun", "qa_verdict", "TEXT"),
        ("agentrun", "qa_notes", "TEXT"),
        # Phase 5 migrations
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


@contextmanager
def session_scope():
    """Context manager for database sessions (non-FastAPI usage)."""
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()
