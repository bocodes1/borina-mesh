"""Job CRUD routes."""

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from db import get_session, init_db
from models import Job, JobStatus, AgentRun
from agents.base import registry
from workers.handoff import HandoffPayload, HandoffResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    agent_id: str
    prompt: str


@router.post("")
async def create_job(body: JobCreate, session: Session = Depends(get_session)):
    """Create a new job for an agent."""
    if not registry.get(body.agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{body.agent_id}' not found")
    job = Job(agent_id=body.agent_id, prompt=body.prompt, status=JobStatus.PENDING)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post("/handoff", response_model=HandoffResponse)
async def create_handoff(body: HandoffPayload, session: Session = Depends(get_session)):
    """Create an overnight_code job and enqueue a headless worker."""
    if not os.path.isdir(os.path.join(body.repo_path, ".git")):
        raise HTTPException(400, f"Not a git repo: {body.repo_path}")
    job = Job(
        agent_id="qa_director",
        prompt=body.prompt,
        kind="overnight_code",
        repo_path=body.repo_path,
        base_branch=body.base_branch,
        status=JobStatus.PENDING,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    from workers.claude_code_worker import enqueue_worker
    enqueue_worker(job.id, body)
    dashboard = os.environ.get("BORINA_DASHBOARD_URL", "http://localhost:3000")
    return HandoffResponse(
        job_id=job.id,
        dashboard_url=f"{dashboard}/jobs/{job.id}",
        worktree_path=f".borina-workers/{job.id}",
    )


@router.get("")
async def list_jobs(
    agent_id: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    """List recent jobs, optionally filtered by agent."""
    query = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if agent_id:
        query = query.where(Job.agent_id == agent_id)
    return session.exec(query).all()


@router.get("/{job_id}")
async def get_job(job_id: int, session: Session = Depends(get_session)):
    """Get a single job by id."""
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/runs")
async def get_job_runs(job_id: int, session: Session = Depends(get_session)):
    """Get all AgentRun records for a specific job."""
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    runs = session.exec(select(AgentRun).where(AgentRun.job_id == job_id)).all()
    return runs
