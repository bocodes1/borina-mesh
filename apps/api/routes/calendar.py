"""Calendar API (spec §6).

Mounted at `/calendar` (frontend: `/api/calendar/...`). Reading is open;
**event creation requires an explicit user-initiated request** — the POST
rejects anything not flagged `user_initiated=True`, so an agent path can never
create events. Task deadlines surface as all-day chips so /daily and /calendar
stay consistent.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Task
from integrations import google_calendar

router = APIRouter(prefix="/calendar", tags=["calendar"])


class EventCreate(BaseModel):
    summary: str
    start: str  # ISO datetime
    end: str    # ISO datetime
    location: Optional[str] = None
    attendees: Optional[list[str]] = None
    # Security gate: must be True, set by the UI in response to a real click.
    user_initiated: bool = False


def _task_chips(session: Session, time_min: str, time_max: str) -> list[dict]:
    """Open tasks with a due date become all-day chips."""
    tasks = session.exec(
        select(Task).where(Task.done == False, Task.due != None)  # noqa: E711,E712
    ).all()
    chips = []
    for t in tasks:
        due_iso = t.due.isoformat() if t.due else None
        if due_iso and time_min <= due_iso <= time_max:
            chips.append(
                {
                    "id": f"task-{t.id}",
                    "title": f"Due: {t.title}",
                    "start": due_iso,
                    "end": due_iso,
                    "all_day": True,
                    "kind": "task",
                    "tag": t.tag,
                }
            )
    return chips


@router.get("/events")
def list_events(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    session: Session = Depends(get_session),
):
    cal = google_calendar.list_events(from_, to)
    events = cal.data if cal.connected else []
    return {
        "calendar": cal.to_dict(),
        "events": events,
        "task_chips": _task_chips(session, from_, to),
    }


@router.post("/events", status_code=201)
def create_event(body: EventCreate):
    if not body.user_initiated:
        # Hard gate — never auto-create from an agent/non-UI path.
        raise HTTPException(
            403, "calendar event creation requires an explicit user action"
        )
    event = {
        "summary": body.summary,
        "start": {"dateTime": body.start},
        "end": {"dateTime": body.end},
    }
    if body.location:
        event["location"] = body.location
    if body.attendees:
        event["attendees"] = [{"email": a} for a in body.attendees]
    result = google_calendar.create_event(event, user_initiated=True)
    return result.to_dict()
