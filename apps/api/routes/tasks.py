"""Tasks CRUD backing the /daily tab's task column (spec §5.3).

Mounted at `/tasks` so the frontend reaches it via the Next proxy at
`/api/tasks`. Fields: title, due, priority, tag, done, sort_order.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Task, TASK_TAGS, TASK_PRIORITIES

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    due: Optional[datetime] = None
    priority: str = "medium"
    tag: str = "personal"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    due: Optional[datetime] = None
    priority: Optional[str] = None
    tag: Optional[str] = None
    done: Optional[bool] = None
    sort_order: Optional[int] = None


def _validate(tag: Optional[str], priority: Optional[str]) -> None:
    if tag is not None and tag not in TASK_TAGS:
        raise HTTPException(422, f"tag must be one of {TASK_TAGS}")
    if priority is not None and priority not in TASK_PRIORITIES:
        raise HTTPException(422, f"priority must be one of {TASK_PRIORITIES}")


@router.get("")
def list_tasks(
    done: Optional[bool] = None,
    tag: Optional[str] = None,
    session: Session = Depends(get_session),
):
    query = select(Task)
    if done is not None:
        query = query.where(Task.done == done)
    if tag is not None:
        query = query.where(Task.tag == tag)
    query = query.order_by(Task.done, Task.sort_order, Task.created_at)
    return session.exec(query).all()


@router.post("", status_code=201)
def create_task(body: TaskCreate, session: Session = Depends(get_session)):
    _validate(body.tag, body.priority)
    task = Task(title=body.title, due=body.due, priority=body.priority, tag=body.tag)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskUpdate, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    _validate(body.tag, body.priority)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(task, key, value)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    session.delete(task)
    session.commit()
    return None
