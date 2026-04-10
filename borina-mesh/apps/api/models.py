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


class AgentRun(SQLModel, table=True):
    """Result of an agent execution."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    agent_id: str = Field(index=True)
    output: str
    tokens_used: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentConfig(SQLModel, table=True):
    """Persistent per-agent configuration (schedule, enabled, etc.)."""
    agent_id: str = Field(primary_key=True)
    enabled: bool = True
    schedule_cron: Optional[str] = None
    last_run_at: Optional[datetime] = None


class MorningBrief(SQLModel, table=True):
    """Daily morning brief synthesized by CEO agent."""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True, sa_column_kwargs={"unique": True})
    summary: str = ""
    cost_summary: str = ""
    total_runs: int = 0
    total_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentWorkspace(SQLModel, table=True):
    """Shared blackboard entry for inter-agent communication."""
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    key: str
    value: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    """A single message in a chat thread with an agent."""
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    role: str  # "user" or "assistant"
    content: str
    job_id: Optional[int] = Field(default=None, foreign_key="job.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
