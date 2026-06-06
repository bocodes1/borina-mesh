"""SQLModel database models for Borina Mesh."""

from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(SQLModel, table=True):
    """A job dispatched to an agent."""
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    prompt: str
    status: JobStatus = Field(default=JobStatus.PENDING, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    kind: str = Field(default="agent_run", index=True)
    repo_path: Optional[str] = None
    base_branch: Optional[str] = None
    worker_branch: Optional[str] = None
    worker_pid: Optional[int] = None
    log_path: Optional[str] = None
    qa_verdict: Optional[str] = None
    qa_notes: Optional[str] = None
    # Telegram background dispatch: idempotency key + reply target.
    telegram_update_id: Optional[int] = Field(default=None, index=True)
    telegram_chat_id: Optional[int] = None


class AgentRun(SQLModel, table=True):
    """Result of an agent execution."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    agent_id: str = Field(index=True)
    output: str
    tokens_used: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    qa_verdict: Optional[str] = None
    qa_notes: Optional[str] = None


class AgentConfig(SQLModel, table=True):
    """Persistent per-agent configuration (schedule, enabled, etc.)."""
    agent_id: str = Field(primary_key=True)
    enabled: bool = True
    schedule_cron: Optional[str] = None
    last_run_at: Optional[datetime] = None


# Allowed task tags (spec §5.3) — validated at the route layer.
TASK_TAGS = ("work", "borina", "trading", "personal")
TASK_PRIORITIES = ("low", "medium", "high")


class PlanItem(SQLModel, table=True):
    """A staged proposal item from the `planner` agent. NEVER auto-committed —
    a calendar write or task creation only happens when Bo approves this item
    (the user-initiated action). status: proposed | approved | rejected."""
    id: Optional[int] = Field(default=None, primary_key=True)
    day: str = Field(index=True)
    kind: str  # "task" | "calendar"
    status: str = Field(default="proposed", index=True)
    title: str
    rationale: Optional[str] = None
    payload_json: str = "{}"  # task fields, or calendar event fields
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    decided_at: Optional[datetime] = None
    committed_ref: Optional[str] = None  # created task id / calendar event id


class Task(SQLModel, table=True):
    """A personal task backing the /daily tab's task column."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    due: Optional[datetime] = Field(default=None, index=True)
    priority: str = Field(default="medium")          # low | medium | high
    tag: str = Field(default="personal", index=True)  # work | borina | trading | personal
    done: bool = Field(default=False, index=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
