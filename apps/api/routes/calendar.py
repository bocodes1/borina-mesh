"""Calendar API (spec §6).

Mounted at `/calendar` (frontend: `/api/calendar/...`). Reading is open;
**event creation requires an explicit user-initiated request** — the POST
rejects anything not flagged `user_initiated=True`, so an agent path can never
create events. Task deadlines surface as all-day chips so /daily and /calendar
stay consistent.
"""
from datetime import datetime, timezone
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


def _parse_dt(s: str) -> datetime:
    """Parse an ISO datetime/date into a naive (UTC) datetime for comparison.

    Tolerates a trailing 'Z', explicit offsets, and date-only strings so the
    window bounds and task due dates are compared as instants, not as raw
    lexicographic ISO strings (which mis-sorts across differing precisions/zones).
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.fromisoformat(s + "T00:00:00")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _task_chips(session: Session, time_min: str, time_max: str) -> list[dict]:
    """Open tasks with a due date become all-day chips."""
    tasks = session.exec(
        select(Task).where(Task.done == False, Task.due != None)  # noqa: E711,E712
    ).all()
    tmin = _parse_dt(time_min)
    tmax = _parse_dt(time_max)
    chips = []
    for t in tasks:
        due_iso = t.due.isoformat() if t.due else None
        if t.due and tmin <= t.due <= tmax:
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


# ── Google OAuth consent flow (Phase 5) ──────────────────────────────────────
# Tokens are exchanged and stored server-side only (integrations/google_oauth);
# nothing sensitive transits the frontend. `state` is generated at /start and
# validated at /callback (CSRF guard).

@router.get("/oauth/start")
def oauth_start():
    """Redirect the browser to Google's consent screen."""
    from fastapi.responses import RedirectResponse
    from integrations import google_oauth

    if not google_oauth.configured():
        raise HTTPException(400, "GOOGLE_OAUTH_CLIENT_ID/SECRET not set")
    return RedirectResponse(google_oauth.auth_url(state=google_oauth.new_state()))


@router.get("/oauth/callback")
def oauth_callback(code: Optional[str] = Query(None), state: Optional[str] = Query(None), error: Optional[str] = Query(None)):
    """Exchange the consent code for tokens (stored server-side)."""
    import html as _html
    from fastapi.responses import HTMLResponse
    from integrations import google_oauth

    if error:
        return HTMLResponse(f"<h3>Google OAuth failed: {_html.escape(error)}</h3>", status_code=400)
    if not code:
        raise HTTPException(400, "missing code")
    if not google_oauth.check_state(state or ""):
        raise HTTPException(400, "state mismatch — restart at /calendar/oauth/start")
    google_oauth.exchange_code(code)
    return HTMLResponse("<h3>Google Calendar connected. You can close this tab.</h3>")
