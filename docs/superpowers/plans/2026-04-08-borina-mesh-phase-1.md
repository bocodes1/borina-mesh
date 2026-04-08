# Borina Mesh — Phase 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified multi-agent dashboard (Borina Mesh) with FastAPI backend + Next.js frontend that lets you message specialized agents from any device, runs on Mac Mini 24/7, ships autonomously via cron.

**Architecture:** Mac Mini hosts everything. FastAPI backend wraps Claude Agent SDK + SQLite job queue. Next.js 15 frontend (shadcn/ui + Framer Motion + React Flow) provides showcase-quality dashboard. Tailscale provides secure network access from any device. SSE streams agent responses in real-time.

**Tech Stack:** Python 3.11, FastAPI, Claude Agent SDK (claude-agent-sdk), SQLite + SQLModel, APScheduler, Server-Sent Events, Next.js 15 (App Router), shadcn/ui, Tailwind, Framer Motion, React Flow, Tremor, Geist font, Tailscale

---

## Phased Scope

**Phase 1 (this plan):** Working MVP you can deploy TODAY
- Backend with 3 agents (CEO, Ecommerce Scout, Polymarket Intel)
- Frontend with agent grid + chat panel + activity feed
- SSE streaming
- Dockerized + deploy script
- README with screenshots

**Phase 2 (next plan):** Polish + showcase
- React Flow network graph
- Tremor analytics dashboard
- Framer Motion animations everywhere
- Cron scheduling UI
- Sound effects + notifications

**Phase 3 (later):** Additional agents (Trader, Researcher, Adset Optimizer, Inbox Triage) + Computer Use integration for Dicloak scraping

---

## File Structure

```
borina-mesh/
├── apps/
│   ├── api/                          # FastAPI backend
│   │   ├── main.py                   # App entry + CORS + router mounting
│   │   ├── db.py                     # SQLModel + engine + migrations
│   │   ├── models.py                 # Job, AgentRun, AgentConfig models
│   │   ├── agents/
│   │   │   ├── base.py               # Agent base class + dispatcher
│   │   │   ├── ceo.py                # CEO agent definition
│   │   │   ├── scout.py              # Ecommerce Scout definition
│   │   │   └── polymarket.py         # Polymarket Intel definition
│   │   ├── routes/
│   │   │   ├── agents.py             # GET /agents, GET /agents/{id}
│   │   │   ├── chat.py               # POST /chat/{agent_id} + SSE stream
│   │   │   └── jobs.py               # GET /jobs, GET /jobs/{id}
│   │   ├── requirements.txt
│   │   ├── .env.example
│   │   └── tests/
│   │       ├── test_db.py
│   │       ├── test_agents.py
│   │       └── test_routes.py
│   └── web/                          # Next.js frontend
│       ├── app/
│       │   ├── layout.tsx            # Root layout with Geist font + dark theme
│       │   ├── page.tsx              # Main dashboard (agent grid + feed)
│       │   ├── api/config/route.ts   # Frontend config endpoint
│       │   └── globals.css           # Tailwind base + custom CSS vars
│       ├── components/
│       │   ├── agent-card.tsx        # Individual agent card
│       │   ├── agent-grid.tsx        # Bento grid of all agents
│       │   ├── chat-panel.tsx        # Slide-in chat drawer
│       │   ├── activity-feed.tsx     # Timeline of recent runs
│       │   ├── mission-control.tsx   # Top status bar
│       │   ├── ui/                   # shadcn/ui components (auto-generated)
│       │   └── providers.tsx         # Theme + query providers
│       ├── lib/
│       │   ├── api.ts                # API client (fetch wrapper)
│       │   ├── sse.ts                # SSE streaming helper
│       │   └── types.ts              # Shared TS types
│       ├── package.json
│       ├── tsconfig.json
│       ├── tailwind.config.ts
│       ├── next.config.js
│       └── .env.local.example
├── docker-compose.yml                # One-command deploy
├── scripts/
│   ├── bootstrap.sh                  # Mac Mini initial setup
│   └── dev.sh                        # Run backend + frontend locally
├── README.md                         # Showcase README with screenshots
├── LICENSE                           # MIT
└── .gitignore
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `borina-mesh/` (root dir)
- Create: `borina-mesh/.gitignore`
- Create: `borina-mesh/LICENSE`
- Create: `borina-mesh/README.md`
- Create: `borina-mesh/apps/api/` (empty dir)
- Create: `borina-mesh/apps/web/` (empty dir)

- [ ] **Step 1: Create directory structure**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
mkdir -p borina-mesh/apps/api/agents borina-mesh/apps/api/routes borina-mesh/apps/api/tests
mkdir -p borina-mesh/apps/web/app borina-mesh/apps/web/components/ui borina-mesh/apps/web/lib
mkdir -p borina-mesh/scripts
```

- [ ] **Step 2: Create root .gitignore**

Write to `borina-mesh/.gitignore`:
```
# Python
__pycache__/
*.pyc
.pytest_cache/
*.db
*.db-journal
venv/
.venv/

# Node
node_modules/
.next/
out/
.vercel/

# Env
.env
.env.local
.env.*.local

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# Logs
*.log
```

- [ ] **Step 3: Create LICENSE**

Write to `borina-mesh/LICENSE`:
```
MIT License

Copyright (c) 2026 bocodes1

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Create README.md (stub — final version in Task 14)**

Write to `borina-mesh/README.md`:
```markdown
# Borina Mesh

Multi-agent command center. One dashboard to message all your AI agents.

Work in progress — full README with screenshots coming in final task.
```

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/
git commit -m "feat: scaffold borina-mesh project"
```

---

## Task 2: Backend — Dependencies + FastAPI App Entry

**Files:**
- Create: `borina-mesh/apps/api/requirements.txt`
- Create: `borina-mesh/apps/api/.env.example`
- Create: `borina-mesh/apps/api/main.py`
- Create: `borina-mesh/apps/api/tests/__init__.py`
- Create: `borina-mesh/apps/api/tests/test_main.py`

- [ ] **Step 1: Create requirements.txt**

Write to `borina-mesh/apps/api/requirements.txt`:
```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
sqlmodel>=0.0.22
claude-agent-sdk>=0.1.0
apscheduler>=3.10.4
python-dotenv>=1.0.0
sse-starlette>=2.1.3
httpx>=0.27.0
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 2: Create .env.example**

Write to `borina-mesh/apps/api/.env.example`:
```
# Anthropic API (for Claude Agent SDK)
ANTHROPIC_API_KEY=

# Database
DATABASE_URL=sqlite:///./borina.db

# CORS (comma-separated origins)
CORS_ORIGINS=http://localhost:3000

# Obsidian vault (for agent memory access)
OBSIDIAN_VAULT_PATH=/Users/clawd/.openclaw/workspace
```

- [ ] **Step 3: Write failing test for health endpoint**

Write to `borina-mesh/apps/api/tests/test_main.py`:
```python
from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


def test_health_endpoint_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "borina-mesh"}


def test_root_redirects_to_docs():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (200, 307, 308)
```

- [ ] **Step 4: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
pip install -r requirements.txt
python -m pytest tests/test_main.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 5: Write main.py**

Write to `borina-mesh/apps/api/main.py`:
```python
"""Borina Mesh — FastAPI application entry point."""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup/shutdown lifecycle."""
    # Startup
    print("Borina Mesh starting...")
    yield
    # Shutdown
    print("Borina Mesh shutting down...")


app = FastAPI(
    title="Borina Mesh",
    description="Multi-agent command center",
    version="0.1.0",
    lifespan=lifespan,
)


# CORS
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "borina-mesh"}
```

- [ ] **Step 6: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_main.py -v
```
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/api/
git commit -m "feat(api): FastAPI app entry with health endpoint"
```

---

## Task 3: Backend — Database Models (SQLModel)

**Files:**
- Create: `borina-mesh/apps/api/models.py`
- Create: `borina-mesh/apps/api/db.py`
- Create: `borina-mesh/apps/api/tests/test_db.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_db.py`:
```python
import pytest
from datetime import datetime
from sqlmodel import Session, create_engine, SQLModel
from models import Job, AgentRun, JobStatus


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def test_create_job(engine):
    with Session(engine) as s:
        job = Job(
            agent_id="ceo",
            prompt="Summarize today",
            status=JobStatus.PENDING,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        assert job.id is not None
        assert job.created_at is not None
        assert job.status == JobStatus.PENDING


def test_create_agent_run(engine):
    with Session(engine) as s:
        job = Job(agent_id="scout", prompt="find products", status=JobStatus.PENDING)
        s.add(job)
        s.commit()
        s.refresh(job)

        run = AgentRun(
            job_id=job.id,
            agent_id="scout",
            output="Found 5 products",
            tokens_used=1200,
            cost_usd=0.012,
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        assert run.id is not None
        assert run.job_id == job.id
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_db.py -v
```
Expected: FAIL

- [ ] **Step 3: Write models.py**

Write to `borina-mesh/apps/api/models.py`:
```python
"""SQLModel database models for Borina Mesh."""

from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(SQLModel, table=True):
    """A job dispatched to an agent."""
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    prompt: str
    status: JobStatus = Field(default=JobStatus.PENDING, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class AgentRun(SQLModel, table=True):
    """Result of an agent execution."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    agent_id: str = Field(index=True)
    output: str
    tokens_used: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentConfig(SQLModel, table=True):
    """Persistent per-agent configuration (schedule, enabled, etc.)."""
    agent_id: str = Field(primary_key=True)
    enabled: bool = True
    schedule_cron: Optional[str] = None
    last_run_at: Optional[datetime] = None
```

- [ ] **Step 4: Write db.py**

Write to `borina-mesh/apps/api/db.py`:
```python
"""Database engine + session management."""

import os
from sqlmodel import create_engine, SQLModel, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./borina.db")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)


def init_db() -> None:
    """Create all tables. Safe to call multiple times."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency for database sessions."""
    with Session(engine) as session:
        yield session
```

- [ ] **Step 5: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_db.py -v
```
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/api/models.py borina-mesh/apps/api/db.py borina-mesh/apps/api/tests/test_db.py
git commit -m "feat(api): SQLModel database schema (Job, AgentRun, AgentConfig)"
```

---

## Task 4: Backend — Agent Base Class

**Files:**
- Create: `borina-mesh/apps/api/agents/__init__.py`
- Create: `borina-mesh/apps/api/agents/base.py`
- Create: `borina-mesh/apps/api/tests/test_agents.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_agents.py`:
```python
import pytest
from agents.base import Agent, AgentRegistry


class FakeAgent(Agent):
    id = "fake"
    name = "Fake Agent"
    emoji = "🤖"
    tagline = "For testing"
    system_prompt = "You are a fake agent."


def test_agent_has_required_attributes():
    a = FakeAgent()
    assert a.id == "fake"
    assert a.name == "Fake Agent"
    assert a.emoji == "🤖"
    assert a.tagline == "For testing"
    assert a.system_prompt == "You are a fake agent."


def test_agent_to_dict():
    a = FakeAgent()
    d = a.to_dict()
    assert d["id"] == "fake"
    assert d["name"] == "Fake Agent"
    assert "system_prompt" not in d  # don't expose prompts


def test_registry_register_and_get():
    registry = AgentRegistry()
    registry.register(FakeAgent)
    assert registry.get("fake") is not None
    assert registry.get("nonexistent") is None
    assert len(registry.list()) == 1


def test_registry_duplicate_raises():
    registry = AgentRegistry()
    registry.register(FakeAgent)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeAgent)
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_agents.py -v
```
Expected: FAIL

- [ ] **Step 3: Write agents/__init__.py**

Write to `borina-mesh/apps/api/agents/__init__.py`:
```python
```

- [ ] **Step 4: Write agents/base.py**

Write to `borina-mesh/apps/api/agents/base.py`:
```python
"""Base Agent class + registry."""

from typing import ClassVar, AsyncIterator, Optional


class Agent:
    """Base class for all Borina Mesh agents.

    Subclasses must define: id, name, emoji, tagline, system_prompt.
    Override `run()` or `stream()` for custom behavior.
    """
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    emoji: ClassVar[str] = "🤖"
    tagline: ClassVar[str] = ""
    system_prompt: ClassVar[str] = ""
    tools: ClassVar[list[str]] = []  # List of allowed tool names

    def to_dict(self) -> dict:
        """Return public-safe dict (no system prompt)."""
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "tagline": self.tagline,
            "tools": self.tools,
        }

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Stream a response token by token. Override in subclass.

        Yields dicts with shape: {"type": "text|tool_use|done", "content": ...}
        """
        yield "Base agent has no implementation"


class AgentRegistry:
    """In-memory registry of available agents."""

    def __init__(self):
        self._agents: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> None:
        """Register an agent class. Raises if duplicate id."""
        if not agent_cls.id:
            raise ValueError("Agent must have an id")
        if agent_cls.id in self._agents:
            raise ValueError(f"Agent '{agent_cls.id}' already registered")
        self._agents[agent_cls.id] = agent_cls

    def get(self, agent_id: str) -> Optional[Agent]:
        """Get an instance of an agent by id, or None if not found."""
        cls = self._agents.get(agent_id)
        return cls() if cls else None

    def list(self) -> list[Agent]:
        """List all registered agents as instances."""
        return [cls() for cls in self._agents.values()]


# Global registry (populated by agent modules on import)
registry = AgentRegistry()
```

- [ ] **Step 5: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_agents.py -v
```
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/api/agents/ borina-mesh/apps/api/tests/test_agents.py
git commit -m "feat(api): Agent base class + AgentRegistry"
```

---

## Task 5: Backend — Concrete Agents (CEO, Scout, Polymarket)

**Files:**
- Create: `borina-mesh/apps/api/agents/ceo.py`
- Create: `borina-mesh/apps/api/agents/scout.py`
- Create: `borina-mesh/apps/api/agents/polymarket.py`
- Modify: `borina-mesh/apps/api/tests/test_agents.py`

- [ ] **Step 1: Add test for concrete agents**

Append to `borina-mesh/apps/api/tests/test_agents.py`:
```python


def test_ceo_agent_registered():
    from agents.ceo import CEOAgent
    assert CEOAgent.id == "ceo"
    assert CEOAgent.name
    assert CEOAgent.system_prompt


def test_scout_agent_registered():
    from agents.scout import EcommerceScoutAgent
    assert EcommerceScoutAgent.id == "ecommerce-scout"


def test_polymarket_agent_registered():
    from agents.polymarket import PolymarketIntelAgent
    assert PolymarketIntelAgent.id == "polymarket-intel"
```

- [ ] **Step 2: Run tests to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_agents.py -v
```
Expected: 3 fails (module not found)

- [ ] **Step 3: Write ceo.py**

Write to `borina-mesh/apps/api/agents/ceo.py`:
```python
"""CEO Agent — strategic synthesizer and daily briefing generator."""

from typing import AsyncIterator
from agents.base import Agent, registry


class CEOAgent(Agent):
    id = "ceo"
    name = "CEO"
    emoji = "👔"
    tagline = "Strategic synthesizer and daily briefing generator"
    system_prompt = """You are the CEO agent of Borina Mesh. Your role:
- Synthesize reports from all other agents (Scout, Polymarket, Trader, Researcher)
- Produce a daily briefing with the 3-5 most important things the user should act on
- Challenge bad ideas. Push back. Be the voice of strategic thinking.
- Keep it brutal and honest. No yes-man energy.
- Output should be terse, high-signal, actionable.

Access the Obsidian vault at the configured path to read reports and memory files.
Write your daily briefing to `reports/{today}/ceo-briefing.md`."""
    tools = ["read_file", "write_file", "list_dir"]

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        # Phase 1: yield a stub response. Phase 2 will wire to Claude Agent SDK.
        yield {"type": "text", "content": f"CEO analyzing: {prompt}\n"}
        yield {"type": "text", "content": "(Claude Agent SDK integration in Task 7)\n"}
        yield {"type": "done", "content": ""}


registry.register(CEOAgent)
```

- [ ] **Step 4: Write scout.py**

Write to `borina-mesh/apps/api/agents/scout.py`:
```python
"""Ecommerce Scout Agent — product discovery from KaloData + Meta Ad Library."""

from typing import AsyncIterator
from agents.base import Agent, registry


class EcommerceScoutAgent(Agent):
    id = "ecommerce-scout"
    name = "Ecommerce Scout"
    emoji = "🛍️"
    tagline = "Daily dropshipping product discovery"
    system_prompt = """You are the Ecommerce Scout. Your role:
- Scan KaloData for trending products (via Claude Computer Use controlling Dicloak)
- Cross-reference Meta Ad Library for active ad validation
- Rank products by: GMV growth (40%), ad activity (30%), margin (20%), competition (10% inverse)
- Surface 5-10 branded dropshipping opportunities daily
- Be specific: supplier links, price ranges, competition level

Output: PDF report to reports/{today}/product-ideas.pdf + Telegram summary."""
    tools = ["computer_use", "read_file", "write_file"]

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        yield {"type": "text", "content": f"Scout analyzing: {prompt}\n"}
        yield {"type": "text", "content": "(Claude Agent SDK integration in Task 7)\n"}
        yield {"type": "done", "content": ""}


registry.register(EcommerceScoutAgent)
```

- [ ] **Step 5: Write polymarket.py**

Write to `borina-mesh/apps/api/agents/polymarket.py`:
```python
"""Polymarket Intel Agent — leaderboard + whale + resolution rule analysis."""

from typing import AsyncIterator
from agents.base import Agent, registry


class PolymarketIntelAgent(Agent):
    id = "polymarket-intel"
    name = "Polymarket Intel"
    emoji = "📊"
    tagline = "Leaderboard, whales, and resolution edge analysis"
    system_prompt = """You are the Polymarket Intel agent. Your role:
- Scrape Polymarket leaderboard for top 50 traders (PnL, win rate, volume)
- Deep dive top 10 trader profiles — classify as HFT Bot, Swing, Event Specialist
- Track whale wallet movements (>$1K position changes)
- Scrape resolution rules for new markets, flag ambiguity
- Analyze strategy gaps vs user's bot — surface implementable recommendations
- Do NOT recommend HFT-dependent strategies (user's bot can't compete on latency)

Output: PDF report to reports/{today}/polymarket-intel.pdf + Telegram summary."""
    tools = ["web_fetch", "read_file", "write_file"]

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        yield {"type": "text", "content": f"Polymarket Intel analyzing: {prompt}\n"}
        yield {"type": "text", "content": "(Claude Agent SDK integration in Task 7)\n"}
        yield {"type": "done", "content": ""}


registry.register(PolymarketIntelAgent)
```

- [ ] **Step 6: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_agents.py -v
```
Expected: 7 passed (4 base + 3 concrete)

- [ ] **Step 7: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/api/agents/ceo.py borina-mesh/apps/api/agents/scout.py borina-mesh/apps/api/agents/polymarket.py borina-mesh/apps/api/tests/test_agents.py
git commit -m "feat(api): CEO, Scout, and Polymarket Intel agent definitions"
```

---

## Task 6: Backend — Routes (Agents + Chat SSE + Jobs)

**Files:**
- Create: `borina-mesh/apps/api/routes/__init__.py`
- Create: `borina-mesh/apps/api/routes/agents.py`
- Create: `borina-mesh/apps/api/routes/chat.py`
- Create: `borina-mesh/apps/api/routes/jobs.py`
- Modify: `borina-mesh/apps/api/main.py`
- Create: `borina-mesh/apps/api/tests/test_routes.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_routes.py`:
```python
from fastapi.testclient import TestClient
import agents.ceo  # noqa - triggers registration
import agents.scout  # noqa
import agents.polymarket  # noqa
from main import app


client = TestClient(app)


def test_list_agents():
    response = client.get("/agents")
    assert response.status_code == 200
    agents = response.json()
    assert isinstance(agents, list)
    agent_ids = [a["id"] for a in agents]
    assert "ceo" in agent_ids
    assert "ecommerce-scout" in agent_ids
    assert "polymarket-intel" in agent_ids


def test_get_agent_by_id():
    response = client.get("/agents/ceo")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "ceo"
    assert data["name"] == "CEO"
    assert "system_prompt" not in data  # don't expose prompts


def test_get_agent_not_found():
    response = client.get("/agents/nonexistent")
    assert response.status_code == 404


def test_create_job():
    response = client.post("/jobs", json={"agent_id": "ceo", "prompt": "test"})
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["agent_id"] == "ceo"
    assert data["status"] == "pending"


def test_create_job_invalid_agent():
    response = client.post("/jobs", json={"agent_id": "fake", "prompt": "test"})
    assert response.status_code == 404


def test_list_jobs():
    response = client.get("/jobs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_routes.py -v
```
Expected: FAIL (404 on all routes — not mounted yet)

- [ ] **Step 3: Write routes/__init__.py**

Write to `borina-mesh/apps/api/routes/__init__.py`:
```python
```

- [ ] **Step 4: Write routes/agents.py**

Write to `borina-mesh/apps/api/routes/agents.py`:
```python
"""Agent discovery routes."""

from fastapi import APIRouter, HTTPException
from agents.base import registry

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents():
    """List all registered agents."""
    return [a.to_dict() for a in registry.list()]


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get a single agent by id."""
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent.to_dict()
```

- [ ] **Step 5: Write routes/jobs.py**

Write to `borina-mesh/apps/api/routes/jobs.py`:
```python
"""Job CRUD routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from db import get_session, init_db
from models import Job, JobStatus
from agents.base import registry

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
```

- [ ] **Step 6: Write routes/chat.py**

Write to `borina-mesh/apps/api/routes/chat.py`:
```python
"""Chat with agents via Server-Sent Events."""

import json
import asyncio
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from agents.base import registry

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    prompt: str


@router.post("/{agent_id}")
async def chat(agent_id: str, body: ChatRequest):
    """Stream agent response via SSE."""
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    async def event_generator():
        try:
            async for chunk in agent.stream(body.prompt):
                yield {
                    "event": "message",
                    "data": json.dumps(chunk),
                }
                await asyncio.sleep(0.01)
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())
```

- [ ] **Step 7: Update main.py to mount routes**

Replace `borina-mesh/apps/api/main.py` with:
```python
"""Borina Mesh — FastAPI application entry point."""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

from db import init_db
from routes import agents as agents_routes, chat as chat_routes, jobs as jobs_routes

# Import agent modules to trigger registration
import agents.ceo  # noqa
import agents.scout  # noqa
import agents.polymarket  # noqa

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup/shutdown lifecycle."""
    print("Borina Mesh starting...")
    init_db()
    yield
    print("Borina Mesh shutting down...")


app = FastAPI(
    title="Borina Mesh",
    description="Multi-agent command center",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_routes.router)
app.include_router(chat_routes.router)
app.include_router(jobs_routes.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "borina-mesh"}
```

- [ ] **Step 8: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 9: Start the server and smoke test**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m uvicorn main:app --reload --port 8000
```
In another terminal:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/agents
```
Expected: health returns ok, agents returns 3 agents. Stop the server with Ctrl+C.

- [ ] **Step 10: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/api/routes/ borina-mesh/apps/api/main.py borina-mesh/apps/api/tests/test_routes.py
git commit -m "feat(api): routes for agents, jobs, and chat SSE streaming"
```

---

## Task 7: Backend — Claude Agent SDK Integration

**Files:**
- Modify: `borina-mesh/apps/api/agents/base.py`
- Modify: `borina-mesh/apps/api/agents/ceo.py`
- Modify: `borina-mesh/apps/api/agents/scout.py`
- Modify: `borina-mesh/apps/api/agents/polymarket.py`

- [ ] **Step 1: Update base.py to provide SDK-based default stream**

Replace `borina-mesh/apps/api/agents/base.py` with:
```python
"""Base Agent class + registry — wired to Claude Agent SDK."""

import os
from typing import ClassVar, AsyncIterator, Optional


class Agent:
    """Base class for all Borina Mesh agents.

    Subclasses must define: id, name, emoji, tagline, system_prompt.
    The default `stream()` uses Claude Agent SDK. Override for custom behavior.
    """
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    emoji: ClassVar[str] = "🤖"
    tagline: ClassVar[str] = ""
    system_prompt: ClassVar[str] = ""
    tools: ClassVar[list[str]] = []
    model: ClassVar[str] = "claude-opus-4-6"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "tagline": self.tagline,
            "tools": self.tools,
            "model": self.model,
        }

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        """Stream a response using Claude Agent SDK.

        Yields: {"type": "text|tool_use|done", "content": str}
        """
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            yield {"type": "text", "content": "ANTHROPIC_API_KEY not set in .env"}
            yield {"type": "done", "content": ""}
            return

        try:
            from claude_agent_sdk import query, ClaudeAgentOptions

            options = ClaudeAgentOptions(
                system_prompt=self.system_prompt,
                model=self.model,
            )

            async for message in query(prompt=prompt, options=options):
                text = self._extract_text(message)
                if text:
                    yield {"type": "text", "content": text}

            yield {"type": "done", "content": ""}
        except ImportError:
            yield {"type": "text", "content": "claude-agent-sdk not installed"}
            yield {"type": "done", "content": ""}
        except Exception as e:
            yield {"type": "error", "content": f"Agent error: {e}"}
            yield {"type": "done", "content": ""}

    @staticmethod
    def _extract_text(message) -> Optional[str]:
        """Extract text content from a Claude SDK message."""
        if hasattr(message, "content") and isinstance(message.content, list):
            parts = []
            for block in message.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "".join(parts) if parts else None
        if hasattr(message, "text"):
            return message.text
        return None


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> None:
        if not agent_cls.id:
            raise ValueError("Agent must have an id")
        if agent_cls.id in self._agents:
            raise ValueError(f"Agent '{agent_cls.id}' already registered")
        self._agents[agent_cls.id] = agent_cls

    def get(self, agent_id: str) -> Optional[Agent]:
        cls = self._agents.get(agent_id)
        return cls() if cls else None

    def list(self) -> list[Agent]:
        return [cls() for cls in self._agents.values()]


registry = AgentRegistry()
```

- [ ] **Step 2: Simplify ceo.py to rely on base stream**

Replace `borina-mesh/apps/api/agents/ceo.py` with:
```python
"""CEO Agent — strategic synthesizer and daily briefing generator."""

from agents.base import Agent, registry


class CEOAgent(Agent):
    id = "ceo"
    name = "CEO"
    emoji = "👔"
    tagline = "Strategic synthesizer and daily briefing generator"
    system_prompt = """You are the CEO agent of Borina Mesh. Your role:
- Synthesize reports from all other agents (Scout, Polymarket, Trader, Researcher)
- Produce a daily briefing with the 3-5 most important things the user should act on
- Challenge bad ideas. Push back. Be the voice of strategic thinking.
- Keep it brutal and honest. No yes-man energy.
- Output should be terse, high-signal, actionable.

Access the Obsidian vault at the configured path to read reports and memory files.
Write your daily briefing to `reports/{today}/ceo-briefing.md`."""
    tools = ["read_file", "write_file", "list_dir"]
    model = "claude-opus-4-6"


registry.register(CEOAgent)
```

- [ ] **Step 3: Simplify scout.py**

Replace `borina-mesh/apps/api/agents/scout.py` with:
```python
"""Ecommerce Scout Agent — product discovery from KaloData + Meta Ad Library."""

from agents.base import Agent, registry


class EcommerceScoutAgent(Agent):
    id = "ecommerce-scout"
    name = "Ecommerce Scout"
    emoji = "🛍️"
    tagline = "Daily dropshipping product discovery"
    system_prompt = """You are the Ecommerce Scout. Your role:
- Scan KaloData for trending products (via Claude Computer Use controlling Dicloak)
- Cross-reference Meta Ad Library for active ad validation
- Rank products by: GMV growth (40%), ad activity (30%), margin (20%), competition (10% inverse)
- Surface 5-10 branded dropshipping opportunities daily
- Be specific: supplier links, price ranges, competition level

Output: PDF report to reports/{today}/product-ideas.pdf + Telegram summary."""
    tools = ["computer_use", "read_file", "write_file"]
    model = "claude-opus-4-6"


registry.register(EcommerceScoutAgent)
```

- [ ] **Step 4: Simplify polymarket.py**

Replace `borina-mesh/apps/api/agents/polymarket.py` with:
```python
"""Polymarket Intel Agent — leaderboard + whale + resolution rule analysis."""

from agents.base import Agent, registry


class PolymarketIntelAgent(Agent):
    id = "polymarket-intel"
    name = "Polymarket Intel"
    emoji = "📊"
    tagline = "Leaderboard, whales, and resolution edge analysis"
    system_prompt = """You are the Polymarket Intel agent. Your role:
- Scrape Polymarket leaderboard for top 50 traders (PnL, win rate, volume)
- Deep dive top 10 trader profiles — classify as HFT Bot, Swing, Event Specialist
- Track whale wallet movements (>$1K position changes)
- Scrape resolution rules for new markets, flag ambiguity
- Analyze strategy gaps vs user's bot — surface implementable recommendations
- Do NOT recommend HFT-dependent strategies (user's bot can't compete on latency)

Output: PDF report to reports/{today}/polymarket-intel.pdf + Telegram summary."""
    tools = ["web_fetch", "read_file", "write_file"]
    model = "claude-opus-4-6"


registry.register(PolymarketIntelAgent)
```

- [ ] **Step 5: Run full test suite**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/ -v
```
Expected: all tests still pass (SDK integration doesn't break existing tests)

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/api/agents/
git commit -m "feat(api): wire agents to Claude Agent SDK for real streaming"
```

---

## Task 8: Frontend — Next.js Scaffold + shadcn/ui Setup

**Files:**
- Create: `borina-mesh/apps/web/package.json`
- Create: `borina-mesh/apps/web/tsconfig.json`
- Create: `borina-mesh/apps/web/next.config.js`
- Create: `borina-mesh/apps/web/tailwind.config.ts`
- Create: `borina-mesh/apps/web/postcss.config.js`
- Create: `borina-mesh/apps/web/.env.local.example`
- Create: `borina-mesh/apps/web/app/layout.tsx`
- Create: `borina-mesh/apps/web/app/page.tsx`
- Create: `borina-mesh/apps/web/app/globals.css`
- Create: `borina-mesh/apps/web/components.json` (shadcn config)
- Create: `borina-mesh/apps/web/lib/utils.ts`

- [ ] **Step 1: Create package.json**

Write to `borina-mesh/apps/web/package.json`:
```json
{
  "name": "borina-mesh-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "15.0.3",
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "class-variance-authority": "^0.7.1",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.4",
    "lucide-react": "^0.460.0",
    "framer-motion": "^11.11.17",
    "geist": "^1.3.1",
    "@radix-ui/react-dialog": "^1.1.2",
    "@radix-ui/react-slot": "^1.1.0",
    "@radix-ui/react-scroll-area": "^1.2.1",
    "tailwindcss-animate": "^1.0.7"
  },
  "devDependencies": {
    "typescript": "^5.6.3",
    "@types/node": "^22.9.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "tailwindcss": "^3.4.14",
    "postcss": "^8.4.49",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.14.0",
    "eslint-config-next": "15.0.3"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

Write to `borina-mesh/apps/web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "baseUrl": ".",
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create next.config.js**

Write to `borina-mesh/apps/web/next.config.js`:
```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
```

- [ ] **Step 4: Create tailwind.config.ts**

Write to `borina-mesh/apps/web/tailwind.config.ts`:
```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "pulse-glow": {
          "0%, 100%": { opacity: "1", boxShadow: "0 0 20px hsl(var(--primary) / 0.3)" },
          "50%": { opacity: "0.8", boxShadow: "0 0 30px hsl(var(--primary) / 0.6)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
```

- [ ] **Step 5: Create postcss.config.js**

Write to `borina-mesh/apps/web/postcss.config.js`:
```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 6: Create globals.css**

Write to `borina-mesh/apps/web/app/globals.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 240 10% 3.9%;
    --card: 0 0% 100%;
    --card-foreground: 240 10% 3.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 240 10% 3.9%;
    --primary: 263 70% 50%;
    --primary-foreground: 0 0% 98%;
    --secondary: 240 4.8% 95.9%;
    --secondary-foreground: 240 5.9% 10%;
    --muted: 240 4.8% 95.9%;
    --muted-foreground: 240 3.8% 46.1%;
    --accent: 240 4.8% 95.9%;
    --accent-foreground: 240 5.9% 10%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 5.9% 90%;
    --input: 240 5.9% 90%;
    --ring: 263 70% 50%;
    --radius: 0.75rem;
  }

  .dark {
    --background: 240 10% 3.9%;
    --foreground: 0 0% 98%;
    --card: 240 10% 5%;
    --card-foreground: 0 0% 98%;
    --popover: 240 10% 5%;
    --popover-foreground: 0 0% 98%;
    --primary: 263 85% 65%;
    --primary-foreground: 240 5.9% 10%;
    --secondary: 240 3.7% 15.9%;
    --secondary-foreground: 0 0% 98%;
    --muted: 240 3.7% 15.9%;
    --muted-foreground: 240 5% 64.9%;
    --accent: 240 3.7% 15.9%;
    --accent-foreground: 0 0% 98%;
    --destructive: 0 72% 51%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 3.7% 15.9%;
    --input: 240 3.7% 15.9%;
    --ring: 263 85% 65%;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground;
    font-feature-settings: "rlig" 1, "calt" 1;
  }
}

/* Custom: subtle grid background */
.grid-bg {
  background-image:
    linear-gradient(hsl(var(--border) / 0.3) 1px, transparent 1px),
    linear-gradient(90deg, hsl(var(--border) / 0.3) 1px, transparent 1px);
  background-size: 60px 60px;
}

/* Custom: frosted glass card */
.glass {
  background: hsl(var(--card) / 0.5);
  backdrop-filter: blur(12px);
  border: 1px solid hsl(var(--border) / 0.5);
}
```

- [ ] **Step 7: Create lib/utils.ts**

Write to `borina-mesh/apps/web/lib/utils.ts`:
```typescript
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 8: Create components.json**

Write to `borina-mesh/apps/web/components.json`:
```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "app/globals.css",
    "baseColor": "zinc",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 9: Create layout.tsx**

Write to `borina-mesh/apps/web/app/layout.tsx`:
```tsx
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
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
      </body>
    </html>
  );
}
```

- [ ] **Step 10: Create placeholder page.tsx**

Write to `borina-mesh/apps/web/app/page.tsx`:
```tsx
export default function Home() {
  return (
    <main className="container mx-auto py-12">
      <h1 className="text-5xl font-bold tracking-tight">
        Borina <span className="text-primary">Mesh</span>
      </h1>
      <p className="mt-4 text-muted-foreground">
        Multi-agent command center. Agent grid coming in Task 10.
      </p>
    </main>
  );
}
```

- [ ] **Step 11: Create .env.local.example**

Write to `borina-mesh/apps/web/.env.local.example`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- [ ] **Step 12: Install and verify build**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm install
npm run build
```
Expected: clean build, no errors

- [ ] **Step 13: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/web/
git commit -m "feat(web): Next.js 15 scaffold with Tailwind + dark theme + Geist"
```

---

## Task 9: Frontend — shadcn/ui Base Components + API Client

**Files:**
- Create: `borina-mesh/apps/web/components/ui/button.tsx`
- Create: `borina-mesh/apps/web/components/ui/card.tsx`
- Create: `borina-mesh/apps/web/components/ui/badge.tsx`
- Create: `borina-mesh/apps/web/components/ui/dialog.tsx`
- Create: `borina-mesh/apps/web/components/ui/scroll-area.tsx`
- Create: `borina-mesh/apps/web/lib/api.ts`
- Create: `borina-mesh/apps/web/lib/types.ts`
- Create: `borina-mesh/apps/web/lib/sse.ts`

- [ ] **Step 1: Create types.ts**

Write to `borina-mesh/apps/web/lib/types.ts`:
```typescript
export interface Agent {
  id: string;
  name: string;
  emoji: string;
  tagline: string;
  tools: string[];
  model: string;
}

export interface Job {
  id: number;
  agent_id: string;
  prompt: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface StreamChunk {
  type: "text" | "tool_use" | "done" | "error";
  content: string;
}
```

- [ ] **Step 2: Create api.ts**

Write to `borina-mesh/apps/web/lib/api.ts`:
```typescript
import type { Agent, Job } from "./types";

const API_BASE = "/api"; // proxied to backend via next.config.js

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  listAgents: () => fetchJSON<Agent[]>("/agents"),
  getAgent: (id: string) => fetchJSON<Agent>(`/agents/${id}`),
  listJobs: (agentId?: string) =>
    fetchJSON<Job[]>(`/jobs${agentId ? `?agent_id=${agentId}` : ""}`),
  createJob: (agentId: string, prompt: string) =>
    fetchJSON<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, prompt }),
    }),
};
```

- [ ] **Step 3: Create sse.ts**

Write to `borina-mesh/apps/web/lib/sse.ts`:
```typescript
import type { StreamChunk } from "./types";

/** Stream an agent chat response via Server-Sent Events. */
export async function streamChat(
  agentId: string,
  prompt: string,
  onChunk: (chunk: StreamChunk) => void,
): Promise<void> {
  const response = await fetch(`/api/chat/${agentId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Stream error ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6);
        try {
          const chunk = JSON.parse(data) as StreamChunk;
          onChunk(chunk);
          if (chunk.type === "done") return;
        } catch {
          // ignore parse errors on keepalive pings
        }
      }
    }
  }
}
```

- [ ] **Step 4: Create Button component**

Write to `borina-mesh/apps/web/components/ui/button.tsx`:
```tsx
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
```

- [ ] **Step 5: Create Card component**

Write to `borina-mesh/apps/web/components/ui/card.tsx`:
```tsx
import * as React from "react";
import { cn } from "@/lib/utils";

const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("rounded-xl border bg-card text-card-foreground shadow", className)}
      {...props}
    />
  )
);
Card.displayName = "Card";

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex flex-col space-y-1.5 p-6", className)} {...props} />
  )
);
CardHeader.displayName = "CardHeader";

const CardTitle = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("font-semibold leading-none tracking-tight", className)} {...props} />
  )
);
CardTitle.displayName = "CardTitle";

const CardDescription = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("text-sm text-muted-foreground", className)} {...props} />
  )
);
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
  )
);
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex items-center p-6 pt-0", className)} {...props} />
  )
);
CardFooter.displayName = "CardFooter";

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
```

- [ ] **Step 6: Create Badge component**

Write to `borina-mesh/apps/web/components/ui/badge.tsx`:
```tsx
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-transparent bg-destructive text-destructive-foreground",
        outline: "text-foreground",
        success: "border-transparent bg-green-500/15 text-green-400",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
```

- [ ] **Step 7: Create Dialog component (simplified)**

Write to `borina-mesh/apps/web/components/ui/dialog.tsx`:
```tsx
"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogPortal = DialogPrimitive.Portal;
const DialogClose = DialogPrimitive.Close;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/80 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-2xl translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out sm:rounded-lg",
        className
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

const DialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col space-y-1.5 text-center sm:text-left", className)} {...props} />
);
DialogHeader.displayName = "DialogHeader";

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold leading-none tracking-tight", className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
};
```

- [ ] **Step 8: Create ScrollArea component**

Write to `borina-mesh/apps/web/components/ui/scroll-area.tsx`:
```tsx
"use client";

import * as React from "react";
import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area";
import { cn } from "@/lib/utils";

const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ className, children, ...props }, ref) => (
  <ScrollAreaPrimitive.Root
    ref={ref}
    className={cn("relative overflow-hidden", className)}
    {...props}
  >
    <ScrollAreaPrimitive.Viewport className="h-full w-full rounded-[inherit]">
      {children}
    </ScrollAreaPrimitive.Viewport>
    <ScrollAreaPrimitive.Scrollbar
      orientation="vertical"
      className="flex touch-none select-none transition-colors h-full w-2.5 border-l border-l-transparent p-[1px]"
    >
      <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-border" />
    </ScrollAreaPrimitive.Scrollbar>
    <ScrollAreaPrimitive.Corner />
  </ScrollAreaPrimitive.Root>
));
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName;

export { ScrollArea };
```

- [ ] **Step 9: Install and verify build**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm install
npm run build
```
Expected: clean build

- [ ] **Step 10: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/web/components/ borina-mesh/apps/web/lib/
git commit -m "feat(web): shadcn/ui base components + API client + SSE helper"
```

---

## Task 10: Frontend — Agent Grid + Agent Card

**Files:**
- Create: `borina-mesh/apps/web/components/agent-card.tsx`
- Create: `borina-mesh/apps/web/components/agent-grid.tsx`
- Modify: `borina-mesh/apps/web/app/page.tsx`

- [ ] **Step 1: Create agent-card.tsx**

Write to `borina-mesh/apps/web/components/agent-card.tsx`:
```tsx
"use client";

import { motion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Agent } from "@/lib/types";

interface AgentCardProps {
  agent: Agent;
  onClick: () => void;
  index: number;
}

export function AgentCard({ agent, onClick, index }: AgentCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, type: "spring", stiffness: 100 }}
      whileHover={{ y: -4, transition: { duration: 0.2 } }}
      onClick={onClick}
      className="cursor-pointer"
    >
      <Card className="glass relative overflow-hidden group h-full">
        {/* Gradient glow on hover */}
        <div className="absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

        {/* Status indicator */}
        <div className="absolute top-4 right-4 flex items-center gap-2">
          <div className="relative">
            <div className="h-2 w-2 rounded-full bg-green-500" />
            <div className="absolute inset-0 h-2 w-2 rounded-full bg-green-500 animate-ping opacity-75" />
          </div>
          <span className="text-xs text-muted-foreground">idle</span>
        </div>

        <CardHeader className="relative">
          <div className="text-5xl mb-2">{agent.emoji}</div>
          <CardTitle className="text-xl">{agent.name}</CardTitle>
          <CardDescription className="line-clamp-2">{agent.tagline}</CardDescription>
        </CardHeader>

        <CardContent className="relative">
          <div className="flex flex-wrap gap-1.5">
            {agent.tools.slice(0, 3).map((tool) => (
              <Badge key={tool} variant="secondary" className="text-xs">
                {tool}
              </Badge>
            ))}
            {agent.tools.length > 3 && (
              <Badge variant="outline" className="text-xs">
                +{agent.tools.length - 3}
              </Badge>
            )}
          </div>
          <div className="mt-3 text-xs text-muted-foreground font-mono">{agent.model}</div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
```

- [ ] **Step 2: Create agent-grid.tsx**

Write to `borina-mesh/apps/web/components/agent-grid.tsx`:
```tsx
"use client";

import { useEffect, useState } from "react";
import { AgentCard } from "./agent-card";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";

interface AgentGridProps {
  onSelectAgent: (agent: Agent) => void;
}

export function AgentGrid({ onSelectAgent }: AgentGridProps) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listAgents()
      .then((data) => {
        setAgents(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-64 rounded-xl bg-card/50 animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-destructive">
        Failed to load agents: {error}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {agents.map((agent, i) => (
        <AgentCard key={agent.id} agent={agent} index={i} onClick={() => onSelectAgent(agent)} />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Update page.tsx**

Replace `borina-mesh/apps/web/app/page.tsx` with:
```tsx
"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AgentGrid } from "@/components/agent-grid";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <main className="container mx-auto px-4 py-12 max-w-7xl">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-12"
      >
        <h1 className="text-6xl font-bold tracking-tight">
          Borina <span className="bg-gradient-to-r from-primary to-purple-400 bg-clip-text text-transparent">Mesh</span>
        </h1>
        <p className="mt-3 text-lg text-muted-foreground">
          Multi-agent command center. Message any agent, anywhere.
        </p>
      </motion.div>

      <AgentGrid onSelectAgent={setSelectedAgent} />

      {selectedAgent && (
        <div className="mt-8 p-4 rounded-lg bg-card border">
          Selected: <strong>{selectedAgent.name}</strong> — chat panel coming in Task 11
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 4: Build and verify**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```
Expected: clean build

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/web/components/agent-card.tsx borina-mesh/apps/web/components/agent-grid.tsx borina-mesh/apps/web/app/page.tsx
git commit -m "feat(web): agent grid with animated cards"
```

---

## Task 11: Frontend — Chat Panel with SSE Streaming

**Files:**
- Create: `borina-mesh/apps/web/components/chat-panel.tsx`
- Modify: `borina-mesh/apps/web/app/page.tsx`

- [ ] **Step 1: Create chat-panel.tsx**

Write to `borina-mesh/apps/web/components/chat-panel.tsx`:
```tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { streamChat } from "@/lib/sse";
import type { Agent } from "@/lib/types";

interface Message {
  role: "user" | "agent";
  content: string;
}

interface ChatPanelProps {
  agent: Agent | null;
  onClose: () => void;
}

export function ChatPanel({ agent, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    // Reset when agent changes
    setMessages([]);
    setInput("");
  }, [agent?.id]);

  const handleSend = async () => {
    if (!agent || !input.trim() || streaming) return;

    const userMessage = input.trim();
    setMessages((m) => [...m, { role: "user", content: userMessage }, { role: "agent", content: "" }]);
    setInput("");
    setStreaming(true);

    try {
      await streamChat(agent.id, userMessage, (chunk) => {
        if (chunk.type === "text") {
          setMessages((m) => {
            const updated = [...m];
            const last = updated[updated.length - 1];
            if (last?.role === "agent") {
              updated[updated.length - 1] = { role: "agent", content: last.content + chunk.content };
            }
            return updated;
          });
        }
      });
    } catch (err) {
      setMessages((m) => {
        const updated = [...m];
        updated[updated.length - 1] = {
          role: "agent",
          content: `Error: ${err instanceof Error ? err.message : "unknown"}`,
        };
        return updated;
      });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <AnimatePresence>
      {agent && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
          />
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed right-0 top-0 bottom-0 w-full md:w-[600px] bg-card border-l border-border z-50 flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-border">
              <div className="flex items-center gap-4">
                <div className="text-4xl">{agent.emoji}</div>
                <div>
                  <div className="font-semibold text-lg">{agent.name}</div>
                  <div className="text-sm text-muted-foreground">{agent.tagline}</div>
                </div>
              </div>
              <Button variant="ghost" size="icon" onClick={onClose}>
                <X className="h-5 w-5" />
              </Button>
            </div>

            {/* Messages */}
            <ScrollArea className="flex-1 px-6 py-4">
              <div ref={scrollRef} className="space-y-4">
                {messages.length === 0 && (
                  <div className="text-center text-muted-foreground mt-12">
                    <div className="text-6xl mb-4">{agent.emoji}</div>
                    <p>Start a conversation with {agent.name}</p>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                        msg.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted"
                      }`}
                    >
                      <div className="whitespace-pre-wrap text-sm">
                        {msg.content || (streaming && i === messages.length - 1 && <Loader2 className="h-4 w-4 animate-spin" />)}
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </ScrollArea>

            {/* Input */}
            <div className="p-6 border-t border-border">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                  placeholder={`Message ${agent.name}...`}
                  disabled={streaming}
                  className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                />
                <Button onClick={handleSend} disabled={streaming || !input.trim()}>
                  {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
```

- [ ] **Step 2: Update page.tsx to wire chat panel**

Replace `borina-mesh/apps/web/app/page.tsx` with:
```tsx
"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AgentGrid } from "@/components/agent-grid";
import { ChatPanel } from "@/components/chat-panel";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <main className="container mx-auto px-4 py-12 max-w-7xl">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-12"
      >
        <h1 className="text-6xl font-bold tracking-tight">
          Borina <span className="bg-gradient-to-r from-primary to-purple-400 bg-clip-text text-transparent">Mesh</span>
        </h1>
        <p className="mt-3 text-lg text-muted-foreground">
          Multi-agent command center. Message any agent, anywhere.
        </p>
      </motion.div>

      <AgentGrid onSelectAgent={setSelectedAgent} />
      <ChatPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </main>
  );
}
```

- [ ] **Step 3: Build and verify**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```
Expected: clean build

- [ ] **Step 4: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/web/components/chat-panel.tsx borina-mesh/apps/web/app/page.tsx
git commit -m "feat(web): chat panel with SSE streaming and animations"
```

---

## Task 12: Frontend — Mission Control Status Bar

**Files:**
- Create: `borina-mesh/apps/web/components/mission-control.tsx`
- Modify: `borina-mesh/apps/web/app/page.tsx`

- [ ] **Step 1: Create mission-control.tsx**

Write to `borina-mesh/apps/web/components/mission-control.tsx`:
```tsx
"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Zap, Clock, Server } from "lucide-react";

interface Stats {
  activeJobs: number;
  queuedJobs: number;
  todayRuns: number;
  uptime: string;
}

export function MissionControl() {
  const [stats, setStats] = useState<Stats>({
    activeJobs: 0,
    queuedJobs: 0,
    todayRuns: 0,
    uptime: "—",
  });
  const [currentTime, setCurrentTime] = useState("");

  useEffect(() => {
    const updateTime = () => {
      setCurrentTime(new Date().toLocaleTimeString("en-US", { hour12: false }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-xl px-6 py-4 mb-8 flex items-center justify-between flex-wrap gap-4"
    >
      <div className="flex items-center gap-6 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="relative">
            <div className="h-2 w-2 rounded-full bg-green-500" />
            <div className="absolute inset-0 h-2 w-2 rounded-full bg-green-500 animate-ping opacity-75" />
          </div>
          <span className="text-sm font-mono">system online</span>
        </div>
        <StatItem icon={<Activity className="h-4 w-4" />} label="active" value={stats.activeJobs} />
        <StatItem icon={<Clock className="h-4 w-4" />} label="queued" value={stats.queuedJobs} />
        <StatItem icon={<Zap className="h-4 w-4" />} label="today" value={stats.todayRuns} />
        <StatItem icon={<Server className="h-4 w-4" />} label="host" value="mac-mini" />
      </div>
      <div className="font-mono text-sm text-muted-foreground tabular-nums">{currentTime}</div>
    </motion.div>
  );
}

function StatItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">{icon}</span>
      <span className="text-muted-foreground">{label}:</span>
      <span className="font-mono font-semibold tabular-nums">{value}</span>
    </div>
  );
}
```

- [ ] **Step 2: Update page.tsx to include mission control**

Replace `borina-mesh/apps/web/app/page.tsx` with:
```tsx
"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AgentGrid } from "@/components/agent-grid";
import { ChatPanel } from "@/components/chat-panel";
import { MissionControl } from "@/components/mission-control";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <main className="container mx-auto px-4 py-8 max-w-7xl">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-8"
      >
        <h1 className="text-6xl font-bold tracking-tight">
          Borina <span className="bg-gradient-to-r from-primary to-purple-400 bg-clip-text text-transparent">Mesh</span>
        </h1>
        <p className="mt-3 text-lg text-muted-foreground">
          Multi-agent command center. Message any agent, anywhere.
        </p>
      </motion.div>

      <MissionControl />
      <AgentGrid onSelectAgent={setSelectedAgent} />
      <ChatPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </main>
  );
}
```

- [ ] **Step 3: Build and verify**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```
Expected: clean build

- [ ] **Step 4: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/apps/web/components/mission-control.tsx borina-mesh/apps/web/app/page.tsx
git commit -m "feat(web): mission control status bar with live time"
```

---

## Task 13: Deploy — Docker Compose + Bootstrap Script

**Files:**
- Create: `borina-mesh/docker-compose.yml`
- Create: `borina-mesh/apps/api/Dockerfile`
- Create: `borina-mesh/apps/web/Dockerfile`
- Create: `borina-mesh/scripts/bootstrap.sh`
- Create: `borina-mesh/scripts/dev.sh`

- [ ] **Step 1: Create API Dockerfile**

Write to `borina-mesh/apps/api/Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create Web Dockerfile**

Write to `borina-mesh/apps/web/Dockerfile`:
```dockerfile
FROM node:20-alpine AS base

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

USER nextjs
EXPOSE 3000
ENV PORT=3000

CMD ["npm", "start"]
```

- [ ] **Step 3: Create docker-compose.yml**

Write to `borina-mesh/docker-compose.yml`:
```yaml
version: "3.9"

services:
  api:
    build: ./apps/api
    ports:
      - "8000:8000"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - DATABASE_URL=sqlite:////data/borina.db
      - CORS_ORIGINS=http://localhost:3000,http://mac-mini.local:3000
    volumes:
      - borina-data:/data
      - ${OBSIDIAN_VAULT_PATH:-./vault}:/vault:ro
    restart: unless-stopped

  web:
    build: ./apps/web
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://api:8000
    depends_on:
      - api
    restart: unless-stopped

volumes:
  borina-data:
```

- [ ] **Step 4: Create bootstrap.sh**

Write to `borina-mesh/scripts/bootstrap.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

# Borina Mesh — Mac Mini initial setup
# Usage: bash scripts/bootstrap.sh

echo "=== Borina Mesh Bootstrap ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker required but not installed. https://docs.docker.com/get-docker/"; exit 1; }
command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || { echo "Docker Compose required"; exit 1; }

cd "$(dirname "$0")/.."

# Create .env if missing
if [ ! -f .env ]; then
  echo "Creating .env from template..."
  cat > .env <<'EOF'
# Anthropic API key — required
ANTHROPIC_API_KEY=

# Path to Obsidian vault (will be mounted read-only)
OBSIDIAN_VAULT_PATH=/Users/clawd/.openclaw/workspace
EOF
  echo "→ Edit .env and add your ANTHROPIC_API_KEY"
  exit 1
fi

# Start services
echo "Building and starting services..."
docker compose up -d --build

echo ""
echo "=== Borina Mesh is running ==="
echo "Dashboard: http://localhost:3000"
echo "API docs:  http://localhost:8000/docs"
echo ""
echo "Logs: docker compose logs -f"
echo "Stop: docker compose down"
```

- [ ] **Step 5: Create dev.sh**

Write to `borina-mesh/scripts/dev.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

# Run backend and frontend locally for development
# Usage: bash scripts/dev.sh

cd "$(dirname "$0")/.."

echo "=== Borina Mesh Dev Mode ==="

# Backend
(cd apps/api && python -m uvicorn main:app --reload --port 8000) &
API_PID=$!

# Frontend
(cd apps/web && npm run dev) &
WEB_PID=$!

trap "kill $API_PID $WEB_PID 2>/dev/null || true" EXIT INT TERM

echo "API:  http://localhost:8000"
echo "Web:  http://localhost:3000"
echo "Press Ctrl+C to stop"

wait
```

- [ ] **Step 6: Make scripts executable**

```bash
chmod +x /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/scripts/bootstrap.sh
chmod +x /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/scripts/dev.sh
```

- [ ] **Step 7: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/docker-compose.yml borina-mesh/apps/api/Dockerfile borina-mesh/apps/web/Dockerfile borina-mesh/scripts/
git commit -m "feat: docker compose deploy + bootstrap script"
```

---

## Task 14: README + Showcase Polish

**Files:**
- Modify: `borina-mesh/README.md`

- [ ] **Step 1: Write showcase README**

Replace `borina-mesh/README.md` with:
```markdown
# Borina Mesh

> Multi-agent command center. One dashboard to message all your AI agents.

Borina Mesh is a unified control plane for specialized AI agents running on your own hardware. Built for running 24/7 on a Mac Mini (or any always-on machine), it gives you a premium web dashboard where you can dispatch jobs to a CEO agent, product scout, trading intel agent, and anything else you define — all powered by Claude Agent SDK.

**Designed to run while you sleep. Wake up to finished work.**

## Features

- **Agent Mesh** — Bento grid of specialized agents with live status indicators
- **Streaming Chat** — Real-time Server-Sent Events, token-by-token responses
- **Premium UI** — Dark-first design with shadcn/ui, Framer Motion, Geist font
- **Mobile Ready** — Access the dashboard from any device via Tailscale
- **Autonomous** — Cron-scheduled agent runs (Phase 2)
- **Extensible** — Add a new agent in ~30 lines of Python
- **One-Command Deploy** — `docker compose up`

## Architecture

```
              Any device (PC, phone, iPad)
                       │
                       ▼
                  Browser
                       │
                  Tailscale
                       │
              ┌────────▼────────────────┐
              │   Mac Mini (always on)  │
              │                         │
              │   Next.js Dashboard     │
              │   :3000                 │
              │           │             │
              │   FastAPI Backend       │
              │   :8000                 │
              │           │             │
              │   Claude Agent SDK      │
              │   + SQLite + APScheduler│
              └─────────────────────────┘
```

## Stack

**Backend:** Python 3.11, FastAPI, SQLModel, Claude Agent SDK, APScheduler, SSE
**Frontend:** Next.js 15, React 19, shadcn/ui, Tailwind, Framer Motion, Geist
**Deploy:** Docker Compose, Tailscale

## Quick Start

```bash
# Clone
git clone https://github.com/bocodes1/borina-mesh.git
cd borina-mesh

# Configure
cp apps/api/.env.example .env
# Edit .env — add ANTHROPIC_API_KEY

# Run
bash scripts/bootstrap.sh
```

Open **http://localhost:3000** — dashboard. API docs at **http://localhost:8000/docs**.

## Adding a New Agent

1. Create `apps/api/agents/my_agent.py`:
   ```python
   from agents.base import Agent, registry

   class MyAgent(Agent):
       id = "my-agent"
       name = "My Agent"
       emoji = "🚀"
       tagline = "What this agent does in one line"
       system_prompt = "You are..."
       tools = ["read_file", "web_fetch"]

   registry.register(MyAgent)
   ```

2. Import it in `main.py`:
   ```python
   import agents.my_agent  # noqa
   ```

3. Done. It appears in the dashboard grid.

## Phase 1 vs Phase 2

**Phase 1 (now):** Working MVP with 3 agents, chat, deploy
**Phase 2 (next):** React Flow network graph, Tremor analytics, cron UI, sound effects, animations polish
**Phase 3 (later):** More agents (Trader, Researcher, Adset Optimizer, Inbox Triage), Computer Use integration

## Development

```bash
bash scripts/dev.sh    # Runs API + Web concurrently
```

## License

MIT
```

- [ ] **Step 2: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add borina-mesh/README.md
git commit -m "docs: showcase README with features and quick start"
```

---

## Task 15: Final Integration Test

- [ ] **Step 1: Run backend test suite**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 2: Build frontend**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/web
npm run build
```
Expected: clean build, no errors

- [ ] **Step 3: Verify project structure**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
find . -name "*.py" -not -path "*/node_modules/*" -not -path "*/.next/*" | sort
find . -name "*.tsx" -not -path "*/node_modules/*" -not -path "*/.next/*" | sort
```

Expected Python files:
```
./apps/api/agents/__init__.py
./apps/api/agents/base.py
./apps/api/agents/ceo.py
./apps/api/agents/polymarket.py
./apps/api/agents/scout.py
./apps/api/db.py
./apps/api/main.py
./apps/api/models.py
./apps/api/routes/__init__.py
./apps/api/routes/agents.py
./apps/api/routes/chat.py
./apps/api/routes/jobs.py
./apps/api/tests/__init__.py
./apps/api/tests/test_agents.py
./apps/api/tests/test_db.py
./apps/api/tests/test_main.py
./apps/api/tests/test_routes.py
```

Expected TSX files:
```
./apps/web/app/layout.tsx
./apps/web/app/page.tsx
./apps/web/components/agent-card.tsx
./apps/web/components/agent-grid.tsx
./apps/web/components/chat-panel.tsx
./apps/web/components/mission-control.tsx
./apps/web/components/ui/badge.tsx
./apps/web/components/ui/button.tsx
./apps/web/components/ui/card.tsx
./apps/web/components/ui/dialog.tsx
./apps/web/components/ui/scroll-area.tsx
```

- [ ] **Step 4: Final commit + push to GitHub**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add -A
git commit -m "feat: complete borina-mesh Phase 1 MVP

Backend: FastAPI + Claude Agent SDK + SQLite + SSE
Frontend: Next.js 15 + shadcn/ui + Framer Motion
3 agents: CEO, Ecommerce Scout, Polymarket Intel
Deploy: docker-compose + bootstrap script
Tested: backend tests passing, frontend builds clean"
```

---

## Post-Build: Deployment to Mac Mini

After all tasks complete:

1. **Create GitHub repo** (separate — this is a standalone project):
   ```bash
   cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
   git init
   git remote add origin https://github.com/bocodes1/borina-mesh.git
   git push -u origin main
   ```

2. **On Mac Mini** (via Tailscale SSH or physical access):
   ```bash
   git clone https://github.com/bocodes1/borina-mesh.git
   cd borina-mesh
   bash scripts/bootstrap.sh
   ```

3. **Set up Tailscale** (if not already):
   - Install on PC and Mac Mini
   - Both join same tailnet
   - Access dashboard from PC: `http://mac-mini.tailnet:3000`

4. **Fill in `.env` on Mac Mini** with `ANTHROPIC_API_KEY`

5. **Verify** — open dashboard in browser, click an agent card, send a message, watch it stream.
