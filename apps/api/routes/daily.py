"""Daily command-surface API (spec §5).

Mounted at `/daily` (frontend: `/api/daily/...`). Tasks CRUD lives in
`routes/tasks.py`; this exposes the rolled-up summary the /daily tab renders:
the brief's daily-relevant sections + live weather + open tasks.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import Task
from daily_brief import sections_for, today_str
from integrations import weather

router = APIRouter(prefix="/daily", tags=["daily"])

# Sections of the daily brief that the /daily tab consumes.
DAILY_SECTIONS = ["tldr", "tasks_focus", "nudges", "weather_logistics"]


@router.get("/summary")
def daily_summary(session: Session = Depends(get_session)):
    sections = sections_for(None, DAILY_SECTIONS)
    open_tasks = session.exec(
        select(Task).where(Task.done == False).order_by(Task.sort_order, Task.due)  # noqa: E712
    ).all()
    return {
        "date": today_str(),
        "has_brief": any(v is not None for v in sections.values()),
        "brief": sections,
        "weather": weather.get_current().to_dict(),
        "open_tasks": open_tasks,
    }
