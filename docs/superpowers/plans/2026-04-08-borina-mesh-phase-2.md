# Borina Mesh — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish Borina Mesh into a showcase-quality multi-agent command center with scheduling, analytics, network graph, real-time activity feed, and 4 additional specialized agents.

**Architecture:** Builds on Phase 1 (FastAPI + Next.js 15 + shadcn/ui). Adds APScheduler for cron-driven agent runs, SSE activity stream, React Flow for agent network graph, Tremor for metrics dashboards, and 4 new agent definitions (Researcher, Trader, Adset Optimizer, Inbox Triage).

**Tech Stack:** APScheduler, cronstrue, React Flow (@xyflow/react), Tremor, Framer Motion, react-hotkeys-hook, sonner (toasts)

---

## Phase Scope

Phase 1 shipped (MVP backend + frontend + 3 agents). Phase 2 adds:
- **Backend:** APScheduler, activity event bus, 4 new agents, artifacts storage
- **Frontend:** Activity feed, network graph view, analytics view, schedule editor, command palette, toasts, mobile layout

Phase 3 (later): Computer Use for Dicloak/KaloData scraping, voice input, artifact viewer.

---

## File Structure (Phase 2 additions)

```
borina-mesh/
├── apps/
│   ├── api/
│   │   ├── scheduler.py              # APScheduler bootstrap + job registration (NEW)
│   │   ├── events.py                 # In-process event bus for activity stream (NEW)
│   │   ├── agents/
│   │   │   ├── researcher.py         # NEW
│   │   │   ├── trader.py             # NEW
│   │   │   ├── adset.py              # NEW
│   │   │   └── inbox.py              # NEW
│   │   ├── routes/
│   │   │   ├── activity.py           # GET /activity SSE stream (NEW)
│   │   │   ├── analytics.py          # GET /analytics metrics (NEW)
│   │   │   └── schedules.py          # GET/PUT /schedules (NEW)
│   │   └── tests/
│   │       ├── test_scheduler.py     # NEW
│   │       ├── test_events.py        # NEW
│   │       └── test_analytics.py     # NEW
│   └── web/
│       ├── app/
│       │   ├── page.tsx              # Agent grid (existing — add tabs)
│       │   ├── network/page.tsx      # Network graph view (NEW)
│       │   └── analytics/page.tsx    # Tremor dashboard (NEW)
│       ├── components/
│       │   ├── activity-feed.tsx     # Live activity stream (NEW)
│       │   ├── network-graph.tsx     # React Flow canvas (NEW)
│       │   ├── analytics-cards.tsx   # Tremor metric cards (NEW)
│       │   ├── schedule-editor.tsx   # Cron editor dialog (NEW)
│       │   ├── command-palette.tsx   # Cmd+K palette (NEW)
│       │   ├── navbar.tsx            # Top nav with tabs (NEW)
│       │   └── ui/
│       │       ├── tabs.tsx          # shadcn tabs (NEW)
│       │       ├── tooltip.tsx       # shadcn tooltip (NEW)
│       │       └── sonner.tsx        # shadcn toast wrapper (NEW)
│       └── lib/
│           └── activity.ts           # Activity feed SSE client (NEW)
```

---

## Task 1: Backend — Event Bus for Activity Stream

**Files:**
- Create: `apps/api/events.py`
- Create: `apps/api/tests/test_events.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_events.py`:
```python
import asyncio
import pytest
from events import EventBus, ActivityEvent


@pytest.mark.asyncio
async def test_publish_and_subscribe():
    bus = EventBus()
    received = []

    async def listen():
        async for event in bus.subscribe():
            received.append(event)
            if len(received) == 2:
                break

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.05)

    await bus.publish(ActivityEvent(agent_id="ceo", kind="started", message="CEO run started"))
    await bus.publish(ActivityEvent(agent_id="scout", kind="completed", message="Scout finished"))

    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 2
    assert received[0].agent_id == "ceo"
    assert received[1].kind == "completed"


@pytest.mark.asyncio
async def test_multiple_subscribers_both_receive():
    bus = EventBus()
    a_received = []
    b_received = []

    async def listen(target):
        async for event in bus.subscribe():
            target.append(event)
            if len(target) == 1:
                break

    task_a = asyncio.create_task(listen(a_received))
    task_b = asyncio.create_task(listen(b_received))
    await asyncio.sleep(0.05)

    await bus.publish(ActivityEvent(agent_id="ceo", kind="started", message="x"))

    await asyncio.wait_for(task_a, timeout=1.0)
    await asyncio.wait_for(task_b, timeout=1.0)

    assert len(a_received) == 1
    assert len(b_received) == 1
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_events.py -v
```
Expected: FAIL — module not found

- [ ] **Step 3: Write events.py**

Write to `borina-mesh/apps/api/events.py`:
```python
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
    """Fan-out pub/sub — every subscriber gets every event."""

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    async def publish(self, event: ActivityEvent) -> None:
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


# Global bus shared across the app
bus = EventBus()
```

- [ ] **Step 4: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_events.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/events.py apps/api/tests/test_events.py
git commit -m "feat(api): in-process event bus for activity streaming"
```

---

## Task 2: Backend — Wire Agent Runs to Event Bus

**Files:**
- Modify: `apps/api/agents/base.py`
- Modify: `apps/api/routes/chat.py`

- [ ] **Step 1: Update base.py to publish events during stream**

Replace the `stream` method in `borina-mesh/apps/api/agents/base.py` with:
```python
    async def stream(self, prompt: str, job_id: int | None = None) -> AsyncIterator[dict]:
        """Stream a response using Claude Agent SDK.

        Publishes activity events and yields chunks: {"type": str, "content": str}
        """
        from events import bus, ActivityEvent

        await bus.publish(ActivityEvent(
            agent_id=self.id,
            kind="started",
            message=f"{self.name} started: {prompt[:80]}",
            job_id=job_id,
        ))

        try:
            from claude_agent_sdk import query, ClaudeAgentOptions

            options = ClaudeAgentOptions(
                system_prompt=self.system_prompt,
                model=self.model,
            )

            text_total = 0
            async for message in query(prompt=prompt, options=options):
                text = self._extract_text(message)
                if text:
                    text_total += len(text)
                    yield {"type": "text", "content": text}

            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="completed",
                message=f"{self.name} completed ({text_total} chars)",
                job_id=job_id,
            ))
            yield {"type": "done", "content": ""}
        except ImportError:
            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="failed",
                message="claude-agent-sdk not installed",
                job_id=job_id,
            ))
            yield {"type": "text", "content": "claude-agent-sdk not installed"}
            yield {"type": "done", "content": ""}
        except Exception as e:
            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="failed",
                message=f"Agent error: {e}",
                job_id=job_id,
            ))
            yield {"type": "error", "content": f"Agent error: {e}"}
            yield {"type": "done", "content": ""}
```

- [ ] **Step 2: Update chat.py to pass job_id (no API change)**

No changes needed — `chat.py` doesn't create jobs in Phase 1. Skip this step; the signature change in base.py uses a default value.

- [ ] **Step 3: Run existing tests to confirm no regression**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/ -v
```
Expected: all existing 19 tests still pass (17 from Phase 1 + 2 new event bus tests)

- [ ] **Step 4: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/agents/base.py
git commit -m "feat(api): publish activity events during agent runs"
```

---

## Task 3: Backend — Activity SSE Route

**Files:**
- Create: `apps/api/routes/activity.py`
- Modify: `apps/api/main.py`

- [ ] **Step 1: Write activity.py**

Write to `borina-mesh/apps/api/routes/activity.py`:
```python
"""Activity event stream via Server-Sent Events."""

import json
import asyncio
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from events import bus

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
```

- [ ] **Step 2: Mount the route in main.py**

In `borina-mesh/apps/api/main.py`, add the import and include:
```python
from routes import agents as agents_routes, chat as chat_routes, jobs as jobs_routes, activity as activity_routes
```
And:
```python
app.include_router(activity_routes.router)
```

- [ ] **Step 3: Smoke test manually**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m uvicorn main:app --port 8000 &
sleep 2
curl -N http://localhost:8000/activity/stream &
CURL_PID=$!
sleep 1
curl -X POST http://localhost:8000/chat/ceo -H "Content-Type: application/json" -d '{"prompt":"ping"}'
sleep 3
kill $CURL_PID
pkill -f "uvicorn main:app"
```
Expected: the SSE connection receives at least one `activity` event.

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/routes/activity.py apps/api/main.py
git commit -m "feat(api): activity SSE stream route"
```

---

## Task 4: Backend — APScheduler for Cron-Driven Agent Runs

**Files:**
- Create: `apps/api/scheduler.py`
- Create: `apps/api/routes/schedules.py`
- Modify: `apps/api/main.py`
- Create: `apps/api/tests/test_scheduler.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_scheduler.py`:
```python
import pytest
from scheduler import SchedulerService, parse_cron


def test_parse_cron_valid():
    trigger = parse_cron("0 8 * * *")
    assert trigger is not None


def test_parse_cron_invalid():
    with pytest.raises(ValueError):
        parse_cron("not a cron")


@pytest.mark.asyncio
async def test_scheduler_register_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from db import init_db
    init_db()

    service = SchedulerService()
    service.start()
    try:
        service.set_schedule("ceo", "0 8 * * *")
        schedules = service.list_schedules()
        assert "ceo" in schedules
        assert schedules["ceo"] == "0 8 * * *"

        service.remove_schedule("ceo")
        assert "ceo" not in service.list_schedules()
    finally:
        service.stop()
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_scheduler.py -v
```
Expected: FAIL

- [ ] **Step 3: Write scheduler.py**

Write to `borina-mesh/apps/api/scheduler.py`:
```python
"""APScheduler wrapper for cron-driven agent runs."""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from events import bus, ActivityEvent


def parse_cron(expression: str) -> CronTrigger:
    """Parse a cron expression. Raises ValueError on invalid input."""
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got {len(parts)}")
    try:
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    except Exception as e:
        raise ValueError(f"Invalid cron expression: {e}") from e


class SchedulerService:
    """Wraps APScheduler with per-agent schedule management."""

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._schedules: dict[str, str] = {}

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def set_schedule(self, agent_id: str, cron_expression: str) -> None:
        trigger = parse_cron(cron_expression)
        job_id = f"agent-{agent_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        self._scheduler.add_job(
            self._run_agent,
            trigger=trigger,
            args=[agent_id],
            id=job_id,
            replace_existing=True,
        )
        self._schedules[agent_id] = cron_expression

    def remove_schedule(self, agent_id: str) -> None:
        job_id = f"agent-{agent_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        self._schedules.pop(agent_id, None)

    def list_schedules(self) -> dict[str, str]:
        return dict(self._schedules)

    async def _run_agent(self, agent_id: str) -> None:
        """Execute an agent's scheduled run."""
        from agents.base import registry

        agent = registry.get(agent_id)
        if not agent:
            await bus.publish(ActivityEvent(
                agent_id=agent_id,
                kind="failed",
                message=f"Scheduled run failed: agent '{agent_id}' not found",
            ))
            return

        await bus.publish(ActivityEvent(
            agent_id=agent_id,
            kind="scheduled",
            message=f"Scheduled run triggered for {agent.name}",
        ))

        # Consume the stream (results publish their own events)
        prompt = f"Run your scheduled daily task. Current time: {asyncio.get_event_loop().time()}"
        async for _ in agent.stream(prompt):
            pass


# Global singleton
scheduler_service = SchedulerService()
```

- [ ] **Step 4: Write schedules route**

Write to `borina-mesh/apps/api/routes/schedules.py`:
```python
"""Schedule management routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scheduler import scheduler_service
from agents.base import registry

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleUpdate(BaseModel):
    cron: str


@router.get("")
async def list_schedules():
    """List all active schedules."""
    return scheduler_service.list_schedules()


@router.put("/{agent_id}")
async def set_schedule(agent_id: str, body: ScheduleUpdate):
    """Set or update an agent's schedule."""
    if not registry.get(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    try:
        scheduler_service.set_schedule(agent_id, body.cron)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"agent_id": agent_id, "cron": body.cron}


@router.delete("/{agent_id}")
async def remove_schedule(agent_id: str):
    """Remove an agent's schedule."""
    scheduler_service.remove_schedule(agent_id)
    return {"agent_id": agent_id, "removed": True}
```

- [ ] **Step 5: Start scheduler in main.py lifespan**

Update `borina-mesh/apps/api/main.py`:
```python
from scheduler import scheduler_service
```
And in the `lifespan` function, replace the body with:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Borina Mesh starting...")
    init_db()
    scheduler_service.start()
    yield
    scheduler_service.stop()
    print("Borina Mesh shutting down...")
```
Also add the router:
```python
from routes import schedules as schedules_routes
# ...
app.include_router(schedules_routes.router)
```

- [ ] **Step 6: Add apscheduler to requirements**

Open `borina-mesh/apps/api/requirements.txt` and verify `apscheduler>=3.10.4` is present. It was added in Phase 1; if missing, add it. Install:
```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
pip install apscheduler
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/ -v
```
Expected: all tests pass (19 from before + 3 new scheduler tests = 22 total)

- [ ] **Step 8: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/scheduler.py apps/api/routes/schedules.py apps/api/main.py apps/api/tests/test_scheduler.py
git commit -m "feat(api): APScheduler + schedule management routes"
```

---

## Task 5: Backend — 4 New Agents (Researcher, Trader, Adset, Inbox)

**Files:**
- Create: `apps/api/agents/researcher.py`
- Create: `apps/api/agents/trader.py`
- Create: `apps/api/agents/adset.py`
- Create: `apps/api/agents/inbox.py`
- Modify: `apps/api/main.py`
- Modify: `apps/api/tests/test_agents.py`

- [ ] **Step 1: Write failing tests**

Append to `borina-mesh/apps/api/tests/test_agents.py`:
```python


def test_researcher_agent_registered():
    from agents.researcher import ResearcherAgent
    assert ResearcherAgent.id == "researcher"


def test_trader_agent_registered():
    from agents.trader import TraderAgent
    assert TraderAgent.id == "trader"


def test_adset_agent_registered():
    from agents.adset import AdsetOptimizerAgent
    assert AdsetOptimizerAgent.id == "adset-optimizer"


def test_inbox_agent_registered():
    from agents.inbox import InboxTriageAgent
    assert InboxTriageAgent.id == "inbox-triage"
```

- [ ] **Step 2: Write researcher.py**

Write to `borina-mesh/apps/api/agents/researcher.py`:
```python
"""Researcher Agent — deep web research with multi-source synthesis."""

from agents.base import Agent, registry


class ResearcherAgent(Agent):
    id = "researcher"
    name = "Researcher"
    emoji = "\U0001F50D"  # magnifying glass
    tagline = "Deep research with multi-source synthesis and citations"
    system_prompt = """You are the Researcher agent. Your role:
- Conduct multi-step web research with source verification
- Use the 8-phase pipeline: scope → plan → retrieve (parallel) → triangulate → outline refine → synthesize → critique → package
- Rate sources for credibility (0-100), prioritize peer-reviewed and primary sources
- Produce citation-backed reports, no fabricated citations
- Prose-first writing, 80%+ flowing text, bullets sparingly
- Flag uncertainty explicitly ("no sources found for X")
- Output: structured report to reports/{today}/research-{topic}.md

When the user gives you a topic, ask clarifying questions if scope is unclear.
When scope is clear, proceed autonomously through the pipeline."""
    tools = ["web_fetch", "web_search", "read_file", "write_file"]
    model = "claude-opus-4-6"


registry.register(ResearcherAgent)
```

- [ ] **Step 3: Write trader.py**

Write to `borina-mesh/apps/api/agents/trader.py`:
```python
"""Trader Agent — monitors Polymarket bot and surfaces issues."""

from agents.base import Agent, registry


class TraderAgent(Agent):
    id = "trader"
    name = "Trader"
    emoji = "\U0001F4C8"  # chart increasing
    tagline = "Polymarket bot health monitor and strategy advisor"
    system_prompt = """You are the Trader agent. Your role:
- Monitor the Polymarket bot's real-time performance (check dashboard API, logs)
- Surface anomalies: P&L drops, high loss streaks, stuck orders, websocket desync
- Review trade history for pattern issues (signal inversion, sizing mistakes)
- Generate daily bot health briefings
- NEVER auto-execute trades or modify the bot. Report only.
- Strategy recommendations must be grounded in actual backtested data, not speculation.

Access bot status via http://localhost:8080/api/v1/status (or mac-mini.tailnet).
Check trade journal at reports/trade-journal/*.json for pattern detection.

Output: daily briefing to reports/{today}/trader-briefing.md + Telegram alert on RED issues."""
    tools = ["web_fetch", "read_file", "write_file"]
    model = "claude-opus-4-6"


registry.register(TraderAgent)
```

- [ ] **Step 4: Write adset.py**

Write to `borina-mesh/apps/api/agents/adset.py`:
```python
"""Adset Optimizer Agent — Google Ads performance monitoring."""

from agents.base import Agent, registry


class AdsetOptimizerAgent(Agent):
    id = "adset-optimizer"
    name = "Adset Optimizer"
    emoji = "\U0001F3AF"  # target
    tagline = "Google Ads performance monitor with ROAS recommendations"
    system_prompt = """You are the Adset Optimizer agent. Your role:
- Pull Google Ads campaign data via API (last 7 days + yesterday snapshot)
- Score campaigns: RED (ROAS < 1.0), YELLOW (declining 3+ days OR impression share < 30), GREEN
- Generate prioritized recommendations: negative keywords, bid adjustments, budget reallocation
- Flag wasted spend (search terms with 0 conversions + >$2 cost)
- Surface campaigns hitting budget limits before noon (under-served)
- Output: daily performance report + Telegram summary on status changes

Do NOT auto-execute changes. Human approves all ad modifications.
Output to reports/{today}/adset-report.md."""
    tools = ["read_file", "write_file"]
    model = "claude-opus-4-6"


registry.register(AdsetOptimizerAgent)
```

- [ ] **Step 5: Write inbox.py**

Write to `borina-mesh/apps/api/agents/inbox.py`:
```python
"""Inbox Triage Agent — summarizes emails and messages."""

from agents.base import Agent, registry


class InboxTriageAgent(Agent):
    id = "inbox-triage"
    name = "Inbox Triage"
    emoji = "\U0001F4EC"  # mailbox
    tagline = "Summarize emails and messages, surface what needs your attention"
    system_prompt = """You are the Inbox Triage agent. Your role:
- Review unread emails and messages from configured sources (Gmail, Telegram)
- Categorize: URGENT (reply today), FOLLOW_UP (this week), FYI (just surface), SPAM (ignore)
- Draft reply suggestions for URGENT items (user approves before sending)
- Summarize FYI items into a single paragraph (max 3 sentences)
- Flag anything time-sensitive (deadlines, meetings, payments due)

Output: triage report to reports/{today}/inbox-triage.md + Telegram digest.
Do NOT send any messages automatically. All replies require user approval."""
    tools = ["read_file", "write_file"]
    model = "claude-opus-4-6"


registry.register(InboxTriageAgent)
```

- [ ] **Step 6: Wire into main.py**

Add imports to `borina-mesh/apps/api/main.py`:
```python
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
```

- [ ] **Step 7: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/ -v
```
Expected: all 26 tests passing (22 prior + 4 new)

- [ ] **Step 8: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/agents/researcher.py apps/api/agents/trader.py apps/api/agents/adset.py apps/api/agents/inbox.py apps/api/main.py apps/api/tests/test_agents.py
git commit -m "feat(api): 4 new agents - Researcher, Trader, Adset Optimizer, Inbox Triage"
```

---

## Task 6: Backend — Analytics Route

**Files:**
- Create: `apps/api/routes/analytics.py`
- Modify: `apps/api/main.py`
- Create: `apps/api/tests/test_analytics.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_analytics.py`:
```python
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlmodel import Session
import agents.ceo  # noqa
import agents.scout  # noqa
import agents.polymarket  # noqa
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
from main import app
from db import engine, init_db
from models import Job, AgentRun, JobStatus

init_db()
client = TestClient(app)


def _seed():
    with Session(engine) as s:
        for i in range(3):
            job = Job(agent_id="ceo", prompt=f"p{i}", status=JobStatus.COMPLETED)
            s.add(job)
            s.commit()
            s.refresh(job)
            s.add(AgentRun(job_id=job.id, agent_id="ceo", output="ok", tokens_used=500, cost_usd=0.005))
        s.commit()


def test_analytics_summary():
    _seed()
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_runs" in data
    assert "total_tokens" in data
    assert "total_cost_usd" in data
    assert "runs_by_agent" in data
    assert data["total_runs"] >= 3


def test_analytics_timeseries():
    response = client.get("/analytics/timeseries?days=7")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        first = data[0]
        assert "date" in first
        assert "runs" in first
        assert "tokens" in first
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_analytics.py -v
```
Expected: FAIL

- [ ] **Step 3: Write analytics.py**

Write to `borina-mesh/apps/api/routes/analytics.py`:
```python
"""Analytics routes — token usage, cost, run counts."""

from datetime import datetime, timedelta, date
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func

from db import get_session
from models import AgentRun

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
async def summary(session: Session = Depends(get_session)):
    """Aggregate totals + per-agent breakdown."""
    runs = session.exec(select(AgentRun)).all()
    runs_by_agent: dict[str, dict] = defaultdict(lambda: {"runs": 0, "tokens": 0, "cost_usd": 0.0})
    for r in runs:
        runs_by_agent[r.agent_id]["runs"] += 1
        runs_by_agent[r.agent_id]["tokens"] += r.tokens_used
        runs_by_agent[r.agent_id]["cost_usd"] += r.cost_usd

    return {
        "total_runs": len(runs),
        "total_tokens": sum(r.tokens_used for r in runs),
        "total_cost_usd": round(sum(r.cost_usd for r in runs), 4),
        "runs_by_agent": dict(runs_by_agent),
    }


@router.get("/timeseries")
async def timeseries(days: int = 7, session: Session = Depends(get_session)):
    """Daily run/token/cost counts for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    runs = session.exec(select(AgentRun).where(AgentRun.created_at >= cutoff)).all()

    buckets: dict[str, dict] = defaultdict(lambda: {"runs": 0, "tokens": 0, "cost_usd": 0.0})
    for r in runs:
        key = r.created_at.date().isoformat()
        buckets[key]["runs"] += 1
        buckets[key]["tokens"] += r.tokens_used
        buckets[key]["cost_usd"] += round(r.cost_usd, 4)

    # Emit every day in range (zeros for missing)
    result = []
    for i in range(days):
        d = (datetime.utcnow().date() - timedelta(days=days - 1 - i)).isoformat()
        row = buckets.get(d, {"runs": 0, "tokens": 0, "cost_usd": 0.0})
        result.append({"date": d, **row})
    return result
```

- [ ] **Step 4: Mount route in main.py**

Add to `borina-mesh/apps/api/main.py`:
```python
from routes import analytics as analytics_routes
# ...
app.include_router(analytics_routes.router)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -v
```
Expected: 28 passing (26 prior + 2 new)

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/routes/analytics.py apps/api/main.py apps/api/tests/test_analytics.py
git commit -m "feat(api): analytics routes for summary + timeseries"
```

---

## Task 7: Frontend — shadcn Tabs + Tooltip + Sonner Toast Components

**Files:**
- Create: `apps/web/components/ui/tabs.tsx`
- Create: `apps/web/components/ui/tooltip.tsx`
- Create: `apps/web/components/ui/sonner.tsx`
- Modify: `apps/web/package.json`

- [ ] **Step 1: Install required deps**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm install @radix-ui/react-tabs @radix-ui/react-tooltip sonner next-themes
```

- [ ] **Step 2: Write tabs.tsx**

Write to `borina-mesh/apps/web/components/ui/tabs.tsx`:
```tsx
"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex h-10 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground",
      className
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm",
      className
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
```

- [ ] **Step 3: Write tooltip.tsx**

Write to `borina-mesh/apps/web/components/ui/tooltip.tsx`:
```tsx
"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

const TooltipProvider = TooltipPrimitive.Provider;
const Tooltip = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Content
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      "z-50 overflow-hidden rounded-md border bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
      className
    )}
    {...props}
  />
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
```

- [ ] **Step 4: Write sonner.tsx**

Write to `borina-mesh/apps/web/components/ui/sonner.tsx`:
```tsx
"use client";

import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

export function Toaster({ ...props }: ToasterProps) {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      toastOptions={{
        classNames: {
          toast: "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
}
```

- [ ] **Step 5: Add Toaster to root layout**

Update `borina-mesh/apps/web/app/layout.tsx`:
```tsx
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Borina Mesh",
  description: "Multi-agent command center",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${GeistSans.variable} ${GeistMono.variable} font-sans antialiased`}>
        <div className="grid-bg min-h-screen">
          {children}
        </div>
        <Toaster />
      </body>
    </html>
  );
}
```

- [ ] **Step 6: Build to verify**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```
Expected: clean build

- [ ] **Step 7: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/web/components/ui/tabs.tsx apps/web/components/ui/tooltip.tsx apps/web/components/ui/sonner.tsx apps/web/app/layout.tsx apps/web/package.json apps/web/package-lock.json
git commit -m "feat(web): shadcn Tabs, Tooltip, and Sonner toaster"
```

---

## Task 8: Frontend — Activity Feed Component

**Files:**
- Create: `apps/web/lib/activity.ts`
- Create: `apps/web/components/activity-feed.tsx`

- [ ] **Step 1: Create activity.ts SSE client**

Write to `borina-mesh/apps/web/lib/activity.ts`:
```typescript
export interface ActivityEvent {
  agent_id: string;
  kind: "started" | "streaming" | "completed" | "failed" | "scheduled";
  message: string;
  job_id: number | null;
  timestamp: string;
}

export function subscribeToActivity(onEvent: (event: ActivityEvent) => void): () => void {
  const source = new EventSource("/api/activity/stream");

  source.addEventListener("activity", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as ActivityEvent;
      onEvent(data);
    } catch {
      // ignore parse errors
    }
  });

  source.onerror = () => {
    // EventSource auto-reconnects; no action needed
  };

  return () => source.close();
}
```

- [ ] **Step 2: Create activity-feed.tsx**

Write to `borina-mesh/apps/web/components/activity-feed.tsx`:
```tsx
"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, AlertCircle, Play, Clock, Zap } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card } from "@/components/ui/card";
import { subscribeToActivity, type ActivityEvent } from "@/lib/activity";

const KIND_ICONS: Record<ActivityEvent["kind"], React.ReactNode> = {
  started: <Play className="h-4 w-4 text-blue-400" />,
  streaming: <Zap className="h-4 w-4 text-yellow-400" />,
  completed: <CheckCircle2 className="h-4 w-4 text-green-400" />,
  failed: <AlertCircle className="h-4 w-4 text-red-400" />,
  scheduled: <Clock className="h-4 w-4 text-purple-400" />,
};

export function ActivityFeed() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);

  useEffect(() => {
    const unsubscribe = subscribeToActivity((event) => {
      setEvents((prev) => [event, ...prev].slice(0, 50));
    });
    return unsubscribe;
  }, []);

  return (
    <Card className="glass">
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Activity Feed</h3>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <div className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
            live
          </div>
        </div>
      </div>
      <ScrollArea className="h-[400px]">
        <div className="p-4 space-y-2">
          {events.length === 0 && (
            <div className="text-sm text-muted-foreground text-center py-8">
              No activity yet. Message an agent to see events stream in.
            </div>
          )}
          <AnimatePresence initial={false}>
            {events.map((event, i) => (
              <motion.div
                key={`${event.timestamp}-${i}`}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25 }}
                className="flex items-start gap-3 py-2 border-b border-border/50 last:border-0"
              >
                <div className="mt-0.5">{KIND_ICONS[event.kind]}</div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{event.message}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    <span className="font-mono">{event.agent_id}</span>
                    {" · "}
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </ScrollArea>
    </Card>
  );
}
```

- [ ] **Step 3: Build to verify**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```

- [ ] **Step 4: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/web/lib/activity.ts apps/web/components/activity-feed.tsx
git commit -m "feat(web): live activity feed with SSE streaming"
```

---

## Task 9: Frontend — Navbar with Tabs + Updated Main Page Layout

**Files:**
- Create: `apps/web/components/navbar.tsx`
- Modify: `apps/web/app/page.tsx`

- [ ] **Step 1: Create navbar.tsx**

Write to `borina-mesh/apps/web/components/navbar.tsx`:
```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { LayoutGrid, Network, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";

const links = [
  { href: "/", label: "Mesh", icon: LayoutGrid },
  { href: "/network", label: "Network", icon: Network },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <motion.nav
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-8 flex items-center justify-between"
    >
      <Link href="/" className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-primary to-purple-400 shadow-lg" />
        <span className="text-xl font-bold tracking-tight">
          Borina <span className="text-primary">Mesh</span>
        </span>
      </Link>

      <div className="flex items-center gap-1 glass rounded-full p-1">
        {links.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-medium transition-colors",
                active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </div>
    </motion.nav>
  );
}
```

- [ ] **Step 2: Update page.tsx to use navbar + activity feed**

Replace `borina-mesh/apps/web/app/page.tsx` with:
```tsx
"use client";

import { useState } from "react";
import { AgentGrid } from "@/components/agent-grid";
import { ChatPanel } from "@/components/chat-panel";
import { MissionControl } from "@/components/mission-control";
import { ActivityFeed } from "@/components/activity-feed";
import { Navbar } from "@/components/navbar";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />
      <MissionControl />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <AgentGrid onSelectAgent={setSelectedAgent} />
        </div>
        <div className="lg:col-span-1">
          <ActivityFeed />
        </div>
      </div>

      <ChatPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </main>
  );
}
```

- [ ] **Step 3: Build**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```

- [ ] **Step 4: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/web/components/navbar.tsx apps/web/app/page.tsx
git commit -m "feat(web): navbar with tabs + activity feed on main page"
```

---

## Task 10: Frontend — Network Graph View (React Flow)

**Files:**
- Create: `apps/web/components/network-graph.tsx`
- Create: `apps/web/app/network/page.tsx`
- Modify: `apps/web/package.json`

- [ ] **Step 1: Install React Flow**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm install @xyflow/react
```

- [ ] **Step 2: Write network-graph.tsx**

Write to `borina-mesh/apps/web/components/network-graph.tsx`:
```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "@/lib/api";
import { subscribeToActivity } from "@/lib/activity";
import type { Agent } from "@/lib/types";

function buildLayout(agents: Agent[]): { nodes: Node[]; edges: Edge[] } {
  // Place CEO in center, others in a ring around
  const center = agents.find((a) => a.id === "ceo");
  const others = agents.filter((a) => a.id !== "ceo");

  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const radius = 280;

  if (center) {
    nodes.push({
      id: center.id,
      position: { x: 400, y: 300 },
      data: { label: `${center.emoji}  ${center.name}` },
      className: "react-flow__node-ceo",
      style: {
        background: "hsl(263 85% 65% / 0.2)",
        border: "2px solid hsl(263 85% 65%)",
        borderRadius: "14px",
        padding: "14px 22px",
        color: "white",
        fontSize: "15px",
        fontWeight: 600,
      },
    });
  }

  others.forEach((agent, i) => {
    const angle = (i / others.length) * Math.PI * 2 - Math.PI / 2;
    const x = 400 + Math.cos(angle) * radius;
    const y = 300 + Math.sin(angle) * radius;
    nodes.push({
      id: agent.id,
      position: { x, y },
      data: { label: `${agent.emoji}  ${agent.name}` },
      style: {
        background: "hsl(240 10% 8% / 0.9)",
        border: "1px solid hsl(240 3.7% 25%)",
        borderRadius: "12px",
        padding: "10px 18px",
        color: "hsl(0 0% 95%)",
        fontSize: "13px",
        fontWeight: 500,
      },
    });

    if (center) {
      edges.push({
        id: `${center.id}-${agent.id}`,
        source: center.id,
        target: agent.id,
        animated: false,
        style: { stroke: "hsl(240 3.7% 25%)", strokeWidth: 1 },
      });
    }
  });

  return { nodes, edges };
}

export function NetworkGraph() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listAgents().then((agents) => {
      const layout = buildLayout(agents);
      setNodes(layout.nodes);
      setEdges(layout.edges);
      setLoading(false);
    });
  }, [setNodes, setEdges]);

  // Animate edges when an agent emits an event
  useEffect(() => {
    const unsubscribe = subscribeToActivity((event) => {
      setEdges((prev) =>
        prev.map((edge) => {
          if (edge.source === "ceo" && edge.target === event.agent_id) {
            return {
              ...edge,
              animated: event.kind === "started" || event.kind === "streaming",
              style: {
                ...edge.style,
                stroke: event.kind === "failed" ? "hsl(0 84% 60%)" : event.kind === "completed" ? "hsl(142 76% 45%)" : "hsl(263 85% 65%)",
                strokeWidth: 2,
              },
            };
          }
          return edge;
        })
      );

      // Fade edge back to default after 3 seconds
      if (event.kind === "completed" || event.kind === "failed") {
        setTimeout(() => {
          setEdges((prev) =>
            prev.map((edge) =>
              edge.source === "ceo" && edge.target === event.agent_id
                ? { ...edge, animated: false, style: { stroke: "hsl(240 3.7% 25%)", strokeWidth: 1 } }
                : edge
            )
          );
        }, 3000);
      }
    });
    return unsubscribe;
  }, [setEdges]);

  if (loading) {
    return <div className="h-[700px] rounded-xl glass flex items-center justify-center text-muted-foreground">Loading network...</div>;
  }

  return (
    <div className="h-[700px] rounded-xl glass overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="hsl(240 3.7% 20%)" />
        <Controls className="!bg-card !border-border" />
        <MiniMap
          nodeColor="hsl(263 85% 65%)"
          maskColor="hsl(240 10% 3.9% / 0.8)"
          className="!bg-card !border-border"
        />
      </ReactFlow>
    </div>
  );
}
```

- [ ] **Step 3: Write network/page.tsx**

Write to `borina-mesh/apps/web/app/network/page.tsx`:
```tsx
"use client";

import { motion } from "framer-motion";
import { NetworkGraph } from "@/components/network-graph";
import { Navbar } from "@/components/navbar";

export default function NetworkPage() {
  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <h2 className="text-3xl font-bold tracking-tight">Agent Network</h2>
        <p className="text-muted-foreground mt-1">Live view of agent connections and active communication.</p>
      </motion.div>

      <NetworkGraph />
    </main>
  );
}
```

- [ ] **Step 4: Build**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/web/components/network-graph.tsx apps/web/app/network/page.tsx apps/web/package.json apps/web/package-lock.json
git commit -m "feat(web): React Flow network graph with live edge animations"
```

---

## Task 11: Frontend — Analytics View with Tremor

**Files:**
- Create: `apps/web/components/analytics-cards.tsx`
- Create: `apps/web/app/analytics/page.tsx`
- Modify: `apps/web/package.json`

- [ ] **Step 1: Install Tremor**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm install @tremor/react
```

- [ ] **Step 2: Write analytics-cards.tsx**

Write to `borina-mesh/apps/web/components/analytics-cards.tsx`:
```tsx
"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Zap, DollarSign, Users } from "lucide-react";
import { Card } from "@/components/ui/card";

interface Summary {
  total_runs: number;
  total_tokens: number;
  total_cost_usd: number;
  runs_by_agent: Record<string, { runs: number; tokens: number; cost_usd: number }>;
}

interface TimeseriesPoint {
  date: string;
  runs: number;
  tokens: number;
  cost_usd: number;
}

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Fetch failed: ${res.status}`);
  return res.json();
}

export function AnalyticsCards() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchJSON<Summary>("/api/analytics/summary"),
      fetchJSON<TimeseriesPoint[]>("/api/analytics/timeseries?days=14"),
    ])
      .then(([s, t]) => {
        setSummary(s);
        setTimeseries(t);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="text-muted-foreground">Loading analytics...</div>;
  }

  if (!summary) {
    return <div className="text-muted-foreground">No data yet. Message an agent to see analytics.</div>;
  }

  const stats = [
    { label: "Total Runs", value: summary.total_runs.toLocaleString(), icon: Activity, color: "text-blue-400" },
    { label: "Tokens Used", value: summary.total_tokens.toLocaleString(), icon: Zap, color: "text-yellow-400" },
    { label: "Total Cost", value: `$${summary.total_cost_usd.toFixed(2)}`, icon: DollarSign, color: "text-green-400" },
    { label: "Active Agents", value: Object.keys(summary.runs_by_agent).length.toString(), icon: Users, color: "text-purple-400" },
  ];

  const maxRuns = Math.max(1, ...timeseries.map((t) => t.runs));

  return (
    <div className="space-y-6">
      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
          >
            <Card className="glass p-6">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm text-muted-foreground">{stat.label}</div>
                  <div className="text-3xl font-bold mt-1 tabular-nums">{stat.value}</div>
                </div>
                <stat.icon className={`h-5 w-5 ${stat.color}`} />
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Timeseries bar chart */}
      <Card className="glass p-6">
        <h3 className="text-lg font-semibold mb-4">Runs Over Time (14 days)</h3>
        <div className="flex items-end gap-2 h-48">
          {timeseries.map((point, i) => (
            <motion.div
              key={point.date}
              initial={{ height: 0 }}
              animate={{ height: `${(point.runs / maxRuns) * 100}%` }}
              transition={{ delay: i * 0.03, duration: 0.5 }}
              className="flex-1 bg-gradient-to-t from-primary to-purple-400 rounded-t-md min-h-[4px] relative group"
            >
              <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity bg-popover border rounded px-2 py-1 text-xs whitespace-nowrap">
                {point.runs} runs
              </div>
            </motion.div>
          ))}
        </div>
        <div className="flex justify-between mt-2 text-xs text-muted-foreground">
          <span>{timeseries[0]?.date}</span>
          <span>{timeseries[timeseries.length - 1]?.date}</span>
        </div>
      </Card>

      {/* Per-agent breakdown */}
      <Card className="glass p-6">
        <h3 className="text-lg font-semibold mb-4">Usage by Agent</h3>
        <div className="space-y-3">
          {Object.entries(summary.runs_by_agent)
            .sort((a, b) => b[1].runs - a[1].runs)
            .map(([agentId, stats]) => (
              <div key={agentId} className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
                <div className="font-mono text-sm">{agentId}</div>
                <div className="flex items-center gap-6 text-sm">
                  <span className="text-muted-foreground">{stats.runs} runs</span>
                  <span className="text-muted-foreground">{stats.tokens.toLocaleString()} tok</span>
                  <span className="text-green-400 font-mono tabular-nums">${stats.cost_usd.toFixed(3)}</span>
                </div>
              </div>
            ))}
        </div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 3: Write analytics/page.tsx**

Write to `borina-mesh/apps/web/app/analytics/page.tsx`:
```tsx
"use client";

import { motion } from "framer-motion";
import { AnalyticsCards } from "@/components/analytics-cards";
import { Navbar } from "@/components/navbar";

export default function AnalyticsPage() {
  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <h2 className="text-3xl font-bold tracking-tight">Analytics</h2>
        <p className="text-muted-foreground mt-1">Token usage, costs, and run history.</p>
      </motion.div>

      <AnalyticsCards />
    </main>
  );
}
```

- [ ] **Step 4: Build**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/web/components/analytics-cards.tsx apps/web/app/analytics/page.tsx apps/web/package.json apps/web/package-lock.json
git commit -m "feat(web): analytics view with KPI cards + timeseries chart"
```

---

## Task 12: Frontend — Command Palette (Cmd+K)

**Files:**
- Create: `apps/web/components/command-palette.tsx`
- Modify: `apps/web/components/navbar.tsx`
- Modify: `apps/web/package.json`

- [ ] **Step 1: Install cmdk**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm install cmdk
```

- [ ] **Step 2: Write command-palette.tsx**

Write to `borina-mesh/apps/web/components/command-palette.tsx`:
```tsx
"use client";

import { useEffect, useState } from "react";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { LayoutGrid, Network, BarChart3, Search, Bot } from "lucide-react";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const router = useRouter();

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  useEffect(() => {
    if (open && agents.length === 0) {
      api.listAgents().then(setAgents).catch(() => {});
    }
  }, [open, agents.length]);

  const runCommand = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <>
      <Command.Dialog
        open={open}
        onOpenChange={setOpen}
        label="Command palette"
        className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] bg-black/60 backdrop-blur-sm"
      >
        <div className="w-full max-w-lg rounded-xl border bg-popover text-popover-foreground shadow-2xl">
          <div className="flex items-center border-b px-4">
            <Search className="h-4 w-4 text-muted-foreground mr-2" />
            <Command.Input
              placeholder="Search agents and pages..."
              className="flex h-12 w-full bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-[400px] overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results.
            </Command.Empty>
            <Command.Group heading="Pages" className="text-xs font-medium text-muted-foreground px-2 py-1">
              <Command.Item
                onSelect={() => runCommand(() => router.push("/"))}
                className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
              >
                <LayoutGrid className="h-4 w-4" />
                Mesh
              </Command.Item>
              <Command.Item
                onSelect={() => runCommand(() => router.push("/network"))}
                className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
              >
                <Network className="h-4 w-4" />
                Network
              </Command.Item>
              <Command.Item
                onSelect={() => runCommand(() => router.push("/analytics"))}
                className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
              >
                <BarChart3 className="h-4 w-4" />
                Analytics
              </Command.Item>
            </Command.Group>
            {agents.length > 0 && (
              <Command.Group heading="Agents" className="text-xs font-medium text-muted-foreground px-2 py-1 mt-2">
                {agents.map((agent) => (
                  <Command.Item
                    key={agent.id}
                    onSelect={() => runCommand(() => router.push(`/?agent=${agent.id}`))}
                    className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
                  >
                    <span className="text-base">{agent.emoji}</span>
                    <span>{agent.name}</span>
                    <span className="text-xs text-muted-foreground ml-auto">{agent.tagline}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
          <div className="border-t px-3 py-2 text-xs text-muted-foreground flex items-center justify-between">
            <span>
              Press <kbd className="rounded border px-1 font-mono">↵</kbd> to select
            </span>
            <span>
              <kbd className="rounded border px-1 font-mono">ESC</kbd> to close
            </span>
          </div>
        </div>
      </Command.Dialog>
    </>
  );
}
```

- [ ] **Step 3: Add palette to layout.tsx**

Update `borina-mesh/apps/web/app/layout.tsx`:
```tsx
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Toaster } from "@/components/ui/sonner";
import { CommandPalette } from "@/components/command-palette";
import "./globals.css";

export const metadata: Metadata = {
  title: "Borina Mesh",
  description: "Multi-agent command center",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${GeistSans.variable} ${GeistMono.variable} font-sans antialiased`}>
        <div className="grid-bg min-h-screen">
          {children}
        </div>
        <CommandPalette />
        <Toaster />
      </body>
    </html>
  );
}
```

- [ ] **Step 4: Build**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/web/components/command-palette.tsx apps/web/app/layout.tsx apps/web/package.json apps/web/package-lock.json
git commit -m "feat(web): command palette with Cmd+K navigation"
```

---

## Task 13: Frontend — Toast Notifications on Agent Activity

**Files:**
- Create: `apps/web/components/toast-listener.tsx`
- Modify: `apps/web/app/layout.tsx`

- [ ] **Step 1: Create toast-listener.tsx**

Write to `borina-mesh/apps/web/components/toast-listener.tsx`:
```tsx
"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import { subscribeToActivity } from "@/lib/activity";

export function ToastListener() {
  useEffect(() => {
    const unsubscribe = subscribeToActivity((event) => {
      if (event.kind === "completed") {
        toast.success(event.message, {
          description: `${event.agent_id} · ${new Date(event.timestamp).toLocaleTimeString()}`,
        });
      } else if (event.kind === "failed") {
        toast.error(event.message, {
          description: `${event.agent_id} · ${new Date(event.timestamp).toLocaleTimeString()}`,
        });
      }
    });
    return unsubscribe;
  }, []);

  return null;
}
```

- [ ] **Step 2: Add ToastListener to layout**

Update `borina-mesh/apps/web/app/layout.tsx` — add the import and include the component:
```tsx
import { ToastListener } from "@/components/toast-listener";
// ...
// Inside <body>, after CommandPalette:
        <CommandPalette />
        <ToastListener />
        <Toaster />
```

- [ ] **Step 3: Build**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```

- [ ] **Step 4: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/web/components/toast-listener.tsx apps/web/app/layout.tsx
git commit -m "feat(web): toast notifications for agent completion/failure"
```

---

## Task 14: Final — Updated README + Integration Test + Push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with Phase 2 features**

In `borina-mesh/README.md`, replace the "## Features" section with:
```markdown
## Features

- **Agent Mesh** — Bento grid of 7 specialized agents with live status indicators
- **Streaming Chat** — Real-time Server-Sent Events, token-by-token responses
- **Network Graph** — Interactive React Flow canvas showing agent connections with live edge animations
- **Analytics Dashboard** — KPI cards, timeseries charts, per-agent usage breakdown
- **Activity Feed** — Live pub/sub event stream of every agent action
- **Cron Scheduling** — APScheduler-driven autonomous runs
- **Command Palette** — Cmd+K to navigate and search agents instantly
- **Toast Notifications** — Desktop-style alerts on agent completion/failure
- **Premium UI** — Dark-first design with shadcn/ui, Framer Motion, Geist font
- **Mobile Ready** — Access the dashboard from any device via Tailscale
- **Extensible** — Add a new agent in ~30 lines of Python
- **One-Command Deploy** — `docker compose up` or `bash scripts/dev.sh`

## Agents Included

| Agent | Role |
|-------|------|
| 👔 CEO | Strategic synthesizer and daily briefing generator |
| 🛍️ Ecommerce Scout | Daily dropshipping product discovery |
| 📊 Polymarket Intel | Leaderboard, whales, and resolution edge analysis |
| 🔍 Researcher | Deep research with multi-source synthesis and citations |
| 📈 Trader | Polymarket bot health monitor and strategy advisor |
| 🎯 Adset Optimizer | Google Ads performance monitor with ROAS recommendations |
| 📬 Inbox Triage | Summarize emails and messages, surface what needs attention |
```

- [ ] **Step 2: Run full backend test suite**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/ -v
```
Expected: all 30+ tests pass

- [ ] **Step 3: Build frontend**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```
Expected: clean build

- [ ] **Step 4: Commit + push**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add README.md
git commit -m "docs: update README for Phase 2 features (7 agents, network, analytics)"
git push origin main
```

- [ ] **Step 5: Verify on GitHub**

Open https://github.com/bocodes1/borina-mesh in browser — confirm all new commits visible.
