"""SQLModel database models for Borina Mesh."""

from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
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
