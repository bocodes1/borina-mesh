"""Activity event stream via Server-Sent Events."""

import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from events import bus, recent_events

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/stream")
async def activity_stream():
    """Stream live activity events to the client."""

    async def event_generator():
        async for event in bus.subscribe():
            yield {
                "event": "activity",
                "data": json.dumps(event.to_dict()),
            }

    return EventSourceResponse(event_generator())


@router.get("/recent")
async def recent_activity():
    """Return last 50 activity events (polling fallback for SSE)."""
    return [e.to_dict() for e in recent_events()]
