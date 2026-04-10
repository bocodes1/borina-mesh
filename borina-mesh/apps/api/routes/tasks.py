"""Agent task board routes — kanban CRUD."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import AgentTask

router = APIRouter(prefix="/tasks", tags=["tasks"])

VALID_STATUSES = {"backlog", "assigned", "in_progress", "review", "done"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}


class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    assigned_agent: str | None = None
    priority: str = "medium"


class TaskUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    assigned_agent: str | None = None
    status: str | None = None
    priority: str | None = None
    output_data: str | None = None


@router.get("")
async def list_tasks(
    status: str | None = None,
    agent_id: str | None = None,
    session: Session = Depends(get_session),
):
    query = select(AgentTask).order_by(AgentTask.created_at.desc())
    if status:
        query = query.where(AgentTask.status == status)
    if agent_id:
        query = query.where(AgentTask.assigned_agent == agent_id)
    return list(session.exec(query).all())


@router.post("")
async def create_task(
    body: TaskCreateRequest,
    session: Session = Depends(get_session),
):
    if body.priority not in VALID_PRIORITIES:
        raise HTTPException(400, f"Invalid priority. Use: {VALID_PRIORITIES}")
    status = "assigned" if body.assigned_agent else "backlog"
    task = AgentTask(
        title=body.title,
        description=body.description,
        assigned_agent=body.assigned_agent,
        status=status,
        priority=body.priority,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.patch("/{task_id}")
async def update_task(
    task_id: int,
    body: TaskUpdateRequest,
    session: Session = Depends(get_session),
):
    task = session.get(AgentTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if body.status and body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Use: {VALID_STATUSES}")
    if body.priority and body.priority not in VALID_PRIORITIES:
        raise HTTPException(400, f"Invalid priority. Use: {VALID_PRIORITIES}")
    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    if body.assigned_agent is not None:
        task.assigned_agent = body.assigned_agent
    if body.status is not None:
        task.status = body.status
        if body.status == "done":
            task.completed_at = datetime.utcnow()
    if body.priority is not None:
        task.priority = body.priority
    if body.output_data is not None:
        task.output_data = body.output_data
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    session: Session = Depends(get_session),
):
    task = session.get(AgentTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    session.delete(task)
    session.commit()
    return {"id": task_id, "deleted": True}
