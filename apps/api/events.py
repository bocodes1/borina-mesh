"""In-process pub/sub event bus for the activity stream."""

import asyncio
from datetime import datetime
from typing import AsyncIterator, Literal
from dataclasses import dataclass, field, asdict


EventKind = Literal["started", "streaming", "completed", "failed", "scheduled"]


@dataclass
class ActivityEvent:
    agent_id: str
    kind: EventKind
    message: str
    job_id: int | None = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class EventBus:
    """Fan-out pub/sub - every subscriber gets every event."""

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    async def publish(self, event: ActivityEvent) -> None:
        _recent.append(event)
        if len(_recent) > _MAX_RECENT:
            _recent.pop(0)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncIterator[ActivityEvent]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers.remove(queue)


# Buffer last 50 events for polling fallback
_recent: list[ActivityEvent] = []
_MAX_RECENT = 50


def recent_events() -> list[ActivityEvent]:
    """Return the last 50 events, newest first."""
    return list(reversed(_recent))


# Global bus shared across the app
bus = EventBus()
