"""Google Calendar — read events + USER-INITIATED create only.

Safety (spec §6/§7): reading is free; **creating/editing an event must be an
explicit user action**. `create_event` hard-refuses unless `user_initiated=True`
is passed by the route handler in response to a real UI click — an agent path
can never reach the write branch. OAuth tokens live server-side, never in URLs.
"""
from __future__ import annotations

from typing import Optional

from .base import (
    IntegrationResult,
    env,
    http_get_json,
    http_post_json,
    not_connected,
    ok,
    safe,
)

SOURCE = "google_calendar"
API_BASE = "https://www.googleapis.com/calendar/v3"


def _oauth_configured() -> bool:
    return bool(env("GOOGLE_OAUTH_CLIENT_ID") and env("GOOGLE_OAUTH_CLIENT_SECRET"))


def _access_token() -> str:
    # Server-side token file with auto-refresh (env var override still wins).
    from .google_oauth import get_access_token

    return get_access_token()


def status() -> IntegrationResult:
    if not _oauth_configured():
        return not_connected(SOURCE, "GOOGLE_OAUTH_CLIENT_ID/SECRET not set")
    if not _access_token():
        return not_connected(SOURCE, "not authorized — complete Google OAuth consent")
    return ok(SOURCE, {"authorized": True})


@safe(SOURCE)
def list_events(time_min: str, time_max: str, calendar_id: str = "primary") -> IntegrationResult:
    if not _oauth_configured() or not _access_token():
        return not_connected(SOURCE, "Google Calendar not authorized")
    raw = http_get_json(
        f"{API_BASE}/calendars/{calendar_id}/events",
        params={
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
        },
        headers={"Authorization": f"Bearer {_access_token()}"},
    )
    items = raw.get("items", []) if isinstance(raw, dict) else []
    events = [
        {
            "id": it.get("id"),
            "title": it.get("summary"),
            "start": (it.get("start") or {}).get("dateTime") or (it.get("start") or {}).get("date"),
            "end": (it.get("end") or {}).get("dateTime") or (it.get("end") or {}).get("date"),
            "location": it.get("location"),
            "join_link": it.get("hangoutLink"),
            "all_day": "date" in (it.get("start") or {}),
        }
        for it in items
    ]
    return ok(SOURCE, events)


@safe(SOURCE)
def create_event(
    event: dict,
    *,
    user_initiated: bool = False,
    calendar_id: str = "primary",
) -> IntegrationResult:
    """Create an event. HARD safety gate: refuses unless `user_initiated` is True.

    This is the only write path and is never reachable from an agent/auto path —
    the route handler must pass user_initiated=True only for a real UI click.
    """
    if not user_initiated:
        return not_connected(
            SOURCE,
            "refused: calendar event creation requires an explicit user action",
        )
    if not _oauth_configured() or not _access_token():
        return not_connected(SOURCE, "Google Calendar not authorized")
    created = http_post_json(
        f"{API_BASE}/calendars/{calendar_id}/events",
        json=event,
        headers={"Authorization": f"Bearer {_access_token()}"},
    )
    return ok(SOURCE, {"id": created.get("id"), "htmlLink": created.get("htmlLink")})
