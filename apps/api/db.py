"""Database engine + session management."""

import os
from contextlib import contextmanager
from sqlmodel import create_engine, SQLModel, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./borina.db")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)


def init_db() -> None:
    """Create all tables. Safe to call multiple times."""
    SQLModel.metadata.create_all(engine)

    # Idempotent column migration for existing DBs
    if "sqlite" in DATABASE_URL:
        import sqlite3
        conn = sqlite3.connect(DATABASE_URL.replace("sqlite:///", ""))
        cursor = conn.cursor()
        migrations = [
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
        ]
        for table, col, col_type in migrations:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
        conn.close()


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
