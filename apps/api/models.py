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
    # Higher runs first (L4 self-management). user=100, follow-up=90, internal=60,
    # scheduled cron=50 (default), sweep/backfill=10.
    priority: int = Field(default=50, index=True)
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
    """Persistent per-agent configuration + the fleet roster source of truth.
    `state` is the lifecycle: active | parked | retired (see fleet_roster.py)."""
    agent_id: str = Field(primary_key=True)
    enabled: bool = True
    state: str = Field(default="active", index=True)
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


class Goal(SQLModel, table=True):
    """A long-horizon goal (L3). The durable unit; milestones are its plan. The
    live Job (kind='goal') carries the detached pid/log like the builder."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job.id", index=True)
    text: str
    status: str = Field(default="planning", index=True)  # planning|running|checkin|paused|done|aborted|failed
    cancel_requested: bool = Field(default=False)         # polled flag — NOT a kill
    cursor: int = Field(default=0)                         # index of current milestone
    chat_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Milestone(SQLModel, table=True):
    """One step of a Goal's plan (L3)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    seq: int = Field(index=True)
    title: str
    status: str = Field(default="pending")                # pending|active|done|skipped|blocked
    result: Optional[str] = None                           # cleaned summary for the check-in card
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TelegramThread(SQLModel, table=True):
    """Maps a bot-sent Telegram message to the job/agent that produced it, so
    a user reply to that message continues the topic with the same agent."""
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    message_id: int = Field(index=True)
    agent_id: str
    job_id: Optional[int] = None
    prompt: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationLog(SQLModel, table=True):
    """Durable log of Telegram messages (both directions) so the nightly learner
    (operator_brain) can mine what Bo actually talked about. Written fail-open —
    a logging failure never blocks dispatch. role: "user" | "borina"."""
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    role: str
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class OutreachItem(SQLModel, table=True):
    """A staged cold-email outreach (Phase 1). NEVER auto-sent — a send only
    happens when Bo approves this item via Telegram (the user-initiated action).
    status: proposed | sent | skipped | failed. Mirrors PlanItem's stage-then-
    approve lifecycle. Auto-created by init_db's create_all."""
    id: Optional[int] = Field(default=None, primary_key=True)
    track: str                                    # "swe" | "finance"
    company: str
    company_domain: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: str
    subject: str
    body: str
    status: str = Field(default="proposed", index=True)
    dedup_key: str = Field(index=True)            # normalized contact_email + domain
    send_via: Optional[str] = None                # "graph" | "browser"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    sent_at: Optional[datetime] = None


class PostingApplication(SQLModel, table=True):
    """A staged job-board posting application (Phase 2). NEVER auto-submitted —
    a submit only happens when Bo approves this item via Telegram (the
    user-initiated action). submit_method routes the act: "email" reuses
    outlook.send_mail; "form" uses BrowserFiller (fills, human submits);
    "external" hands Bo a deep link + prepared text. status: proposed | prepared
    | submitted | skipped | failed. Mirrors OutreachItem's lifecycle. Auto-created
    by init_db's create_all."""
    id: Optional[int] = Field(default=None, primary_key=True)
    track: str                                    # "swe" | "finance"
    source: str                                   # "wellfound" | "yc" | "career_page" | "clnx" | ...
    company: str
    role_title: str
    location: Optional[str] = None
    posting_url: str = Field(index=True)
    submit_method: str                            # "email" | "form" | "external"
    ats: Optional[str] = None                     # "greenhouse" | "lever" | "workday" | None
    cover_letter: Optional[str] = None
    answers_json: str = "{}"                       # common-question answers (JSON object)
    status: str = Field(default="proposed", index=True)
    dedup_key: str = Field(index=True)            # normalized company + role_title
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    submitted_at: Optional[datetime] = None
