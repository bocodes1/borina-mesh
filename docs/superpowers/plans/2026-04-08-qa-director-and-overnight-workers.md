# QA Director, Model Tiering, Overnight Workers, UI Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tier agent models (Opus/Sonnet/Haiku), introduce a QA Director that dispatches and gatekeeps all agent output, enable Claude Code → borina-mesh overnight handoffs that run headless `claude -p` in git worktrees, and replace the emoji agent grid with status-rich tiles.

**Architecture:** Central model registry replaces hardcoded `model` class attrs. New `qa_director` agent exposes a `dispatch` tool plus a `review()` gatekeeper called from chat, scheduler, and worker completion paths. New `workers/claude_code_worker.py` spawns `claude -p` subprocesses inside per-job git worktrees, streaming logs over SSE. Job model gets columns for `kind`, repo state, worker pid, QA verdict. A `/handoff` Claude Code slash command posts the originating context to a new `POST /jobs/handoff` endpoint. Front-page agent cards switch to Lucide line-art icons + status dot + model badge.

**Tech Stack:** Python 3.11, FastAPI, SQLModel, claude-agent-sdk, Claude Code CLI (`claude -p`), Next.js 14, React, Lucide React, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-04-08-qa-director-and-overnight-workers-design.md`

---

## File Structure

**Created:**
- `apps/api/agents/models.py` — central `AGENT_MODELS` registry + env override resolver.
- `apps/api/agents/qa_director.py` — QA Director agent class (dispatch tool + review).
- `apps/api/workers/__init__.py`
- `apps/api/workers/claude_code_worker.py` — subprocess + worktree manager.
- `apps/api/workers/handoff.py` — Pydantic models for handoff payload.
- `apps/api/tests/test_models_registry.py`
- `apps/api/tests/test_qa_director.py`
- `apps/api/tests/test_claude_code_worker.py`
- `apps/api/tests/test_handoff_route.py`
- `apps/api/tests/fakes/fake_claude.py` — fake `claude` binary emitting canned stream-json for worker tests.
- `apps/web/components/model-badge.tsx`
- `apps/web/components/status-dot.tsx`
- `apps/web/lib/agent-icons.ts` — agent_id → Lucide icon + accent color mapping.
- `~/.claude/commands/handoff.md` — Claude Code slash command (user home, not repo).

**Modified:**
- `apps/api/agents/base.py` — read model from registry, drop hardcoded default.
- `apps/api/agents/{ceo,researcher,scout,trader,polymarket,adset,inbox}.py` — remove `model = ...` lines.
- `apps/api/models.py` — add `Job` columns: `kind`, `repo_path`, `base_branch`, `worker_branch`, `worker_pid`, `log_path`, `qa_verdict`, `qa_notes`.
- `apps/api/routes/jobs.py` — add `POST /jobs/handoff`, `GET /jobs/{id}/log`, `POST /jobs/{id}/cancel`, `POST /jobs/{id}/cleanup`.
- `apps/api/routes/chat.py` — route through QA Director by default; honor `?raw=true` bypass.
- `apps/api/scheduler.py` — pipe artifacts through `qa_director.review()` before publishing events.
- `apps/api/main.py` — register `qa_director` agent + workers router; add `/agents/models` endpoint.
- `apps/web/components/agent-card.tsx` — full rewrite to status-rich tile.
- `apps/web/app/page.tsx` — drop emoji prop, import icon map.
- `apps/web/lib/types.ts` — extend `Agent` type with `model`, `last_run_at`, `next_run_at`, `qa_verdict`.
- `apps/web/lib/api.ts` — add `getAgentModels()`, `createHandoff()`, `streamJobLog()`.
- `apps/web/app/jobs/page.tsx` — add "Overnight Workers" section + live log viewer.

---

## Phase 1 — Model Tiering

### Task 1: Central model registry

**Files:**
- Create: `apps/api/agents/models.py`
- Test: `apps/api/tests/test_models_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_models_registry.py
import os
import pytest
from agents.models import AGENT_MODELS, resolve_model

def test_registry_contains_all_agents():
    expected = {"ceo", "researcher", "scout", "polymarket", "qa_director",
                "trader", "adset", "inbox"}
    assert expected.issubset(AGENT_MODELS.keys())

def test_resolve_model_returns_registry_value():
    assert resolve_model("ceo") == "claude-opus-4-6"
    assert resolve_model("inbox") == "claude-haiku-4-5-20251001"

def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("BORINA_MODEL_INBOX", "claude-sonnet-4-6")
    assert resolve_model("inbox") == "claude-sonnet-4-6"

def test_unknown_agent_raises():
    with pytest.raises(KeyError):
        resolve_model("nope")
```

- [ ] **Step 2: Run test, expect failure** — `pytest apps/api/tests/test_models_registry.py -v` → ImportError.

- [ ] **Step 3: Implement**

```python
# apps/api/agents/models.py
"""Central model tiering registry. Env vars override per agent."""
import os

AGENT_MODELS: dict[str, str] = {
    "ceo":         "claude-opus-4-6",
    "researcher":  "claude-opus-4-6",
    "scout":       "claude-opus-4-6",
    "polymarket":  "claude-opus-4-6",
    "qa_director": "claude-opus-4-6",
    "trader":      "claude-sonnet-4-6",
    "adset":       "claude-sonnet-4-6",
    "inbox":       "claude-haiku-4-5-20251001",
}

def resolve_model(agent_id: str) -> str:
    if agent_id not in AGENT_MODELS:
        raise KeyError(f"Unknown agent_id: {agent_id}")
    env_key = f"BORINA_MODEL_{agent_id.upper()}"
    return os.environ.get(env_key, AGENT_MODELS[agent_id])
```

- [ ] **Step 4: Run test, expect pass.**

- [ ] **Step 5: Commit**

```bash
git add apps/api/agents/models.py apps/api/tests/test_models_registry.py
git commit -m "feat(agents): central model registry with env override"
```

### Task 2: Wire base.Agent to registry, remove hardcoded models

**Files:**
- Modify: `apps/api/agents/base.py:18`
- Modify: `apps/api/agents/{ceo,researcher,scout,trader,polymarket,adset,inbox}.py` (remove `model = "..."` lines)

- [ ] **Step 1: Edit `base.py`** — replace the `model: ClassVar[str] = "claude-opus-4-6"` line and `to_dict`/`stream` references with a property:

```python
# inside class Agent:
    # remove: model: ClassVar[str] = "claude-opus-4-6"
    @property
    def model(self) -> str:
        from agents.models import resolve_model
        return resolve_model(self.id)
```

And in `to_dict`, `self.model` already works. In `stream`, `model=self.model` already works.

- [ ] **Step 2: Remove `model = "..."` from each subclass.** Use Grep first:

```
Grep pattern: ^    model = "
```

Edit each match to delete the line.

- [ ] **Step 3: Run existing agent tests** — `pytest apps/api/tests/test_agents.py -v`. Expect pass (model behavior unchanged for registered agents).

- [ ] **Step 4: Commit**

```bash
git add apps/api/agents/
git commit -m "refactor(agents): read model from central registry"
```

### Task 3: Expose `/agents/models` endpoint

**Files:**
- Modify: `apps/api/main.py` (add route or wire into existing agents router)

- [ ] **Step 1: Write test**

```python
# apps/api/tests/test_models_registry.py (append)
from fastapi.testclient import TestClient
from main import app

def test_agents_models_endpoint():
    client = TestClient(app)
    r = client.get("/agents/models")
    assert r.status_code == 200
    data = r.json()
    assert data["ceo"] == "claude-opus-4-6"
    assert data["inbox"] == "claude-haiku-4-5-20251001"
```

- [ ] **Step 2: Run, expect 404.**

- [ ] **Step 3: Add endpoint in `main.py`** (place near other simple routes):

```python
from agents.models import AGENT_MODELS, resolve_model

@app.get("/agents/models")
def get_agent_models() -> dict[str, str]:
    return {aid: resolve_model(aid) for aid in AGENT_MODELS}
```

- [ ] **Step 4: Run, expect pass.**

- [ ] **Step 5: Commit**

```bash
git add apps/api/main.py apps/api/tests/test_models_registry.py
git commit -m "feat(api): expose /agents/models endpoint"
```

---

## Phase 2 — QA Director Agent

### Task 4: QA Director skeleton + dispatch tool

**Files:**
- Create: `apps/api/agents/qa_director.py`
- Test: `apps/api/tests/test_qa_director.py`

- [ ] **Step 1: Write test for dispatch tool**

```python
# apps/api/tests/test_qa_director.py
import pytest
from agents.qa_director import QADirector, ReviewVerdict

@pytest.mark.asyncio
async def test_dispatch_calls_registered_agent(monkeypatch):
    captured = {}
    class FakeAgent:
        id = "fake"
        async def stream(self, prompt, job_id=None):
            captured["prompt"] = prompt
            yield {"type": "text", "content": "fake-output"}
            yield {"type": "done", "content": ""}

    from agents import base
    monkeypatch.setitem(base.registry._agents, "fake", lambda: FakeAgent())
    qa = QADirector()
    result = await qa.dispatch("fake", "do the thing")
    assert "fake-output" in result
    assert captured["prompt"] == "do the thing"

@pytest.mark.asyncio
async def test_dispatch_unknown_agent_raises():
    qa = QADirector()
    with pytest.raises(ValueError, match="Unknown agent"):
        await qa.dispatch("ghost", "x")
```

- [ ] **Step 2: Run, expect ImportError.**

- [ ] **Step 3: Implement**

```python
# apps/api/agents/qa_director.py
"""QA Director — director-of-work + gatekeeper for every user-bound artifact."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from agents.base import Agent, registry


class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_NOTES = "approve_with_notes"
    REQUEST_RERUN = "request_rerun"
    BLOCK = "block"


@dataclass
class ReviewResult:
    verdict: ReviewVerdict
    notes: str = ""


class QADirector(Agent):
    id = "qa_director"
    name = "QA Director"
    tagline = "Plans, dispatches, reviews. Nothing reaches you unchecked."
    system_prompt = (
        "You are the QA Director for Borina Mesh. Your job has two halves:\n"
        "1) DIRECT: Given a user request, decide which sub-agents to dispatch "
        "(any subset of registered agents). Use the `dispatch` tool. Run them "
        "in parallel when independent. Synthesize one coherent answer.\n"
        "2) REVIEW: When asked to review an artifact, check it for factual "
        "grounding, completeness vs the original request, internal contradictions, "
        "hallucinated tool output, and tone. Reply with one of: "
        "APPROVE / APPROVE_WITH_NOTES: <notes> / REQUEST_RERUN: <reason> / BLOCK: <reason>."
    )

    async def dispatch(self, agent_id: str, prompt: str, job_id: int | None = None) -> str:
        agent = registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Unknown agent_id: {agent_id}")
        chunks: list[str] = []
        async for chunk in agent.stream(prompt, job_id=job_id):
            if chunk.get("type") == "text":
                chunks.append(chunk.get("content", ""))
        return "".join(chunks)

    async def review(self, artifact: str, original_request: str | None = None) -> ReviewResult:
        """Run a gatekeeper pass on an artifact. Returns ReviewResult."""
        prompt = (
            "Review the following artifact for quality. Reply on one line starting "
            "with APPROVE, APPROVE_WITH_NOTES:, REQUEST_RERUN:, or BLOCK:.\n\n"
            f"Original request: {original_request or '(unspecified)'}\n\n"
            f"Artifact:\n{artifact}"
        )
        text = ""
        async for chunk in self.stream(prompt):
            if chunk.get("type") == "text":
                text += chunk.get("content", "")
        return _parse_verdict(text)


def _parse_verdict(text: str) -> ReviewResult:
    line = text.strip().splitlines()[0] if text.strip() else ""
    upper = line.upper()
    if upper.startswith("APPROVE_WITH_NOTES"):
        return ReviewResult(ReviewVerdict.APPROVE_WITH_NOTES, line.split(":", 1)[-1].strip())
    if upper.startswith("APPROVE"):
        return ReviewResult(ReviewVerdict.APPROVE)
    if upper.startswith("REQUEST_RERUN"):
        return ReviewResult(ReviewVerdict.REQUEST_RERUN, line.split(":", 1)[-1].strip())
    if upper.startswith("BLOCK"):
        return ReviewResult(ReviewVerdict.BLOCK, line.split(":", 1)[-1].strip())
    # Default-safe: approve with notes containing the raw response
    return ReviewResult(ReviewVerdict.APPROVE_WITH_NOTES, f"unparsed: {line[:200]}")
```

- [ ] **Step 4: Register in `main.py`** — add to wherever other agents register:

```python
from agents.qa_director import QADirector
registry.register(QADirector)
```

- [ ] **Step 5: Run tests, expect pass.**

- [ ] **Step 6: Commit**

```bash
git add apps/api/agents/qa_director.py apps/api/tests/test_qa_director.py apps/api/main.py
git commit -m "feat(agents): QA Director with dispatch tool + verdict parser"
```

### Task 5: Verdict parser tests

**Files:**
- Modify: `apps/api/tests/test_qa_director.py`

- [ ] **Step 1: Add tests**

```python
from agents.qa_director import _parse_verdict, ReviewVerdict

def test_parse_approve():
    assert _parse_verdict("APPROVE").verdict == ReviewVerdict.APPROVE

def test_parse_approve_with_notes():
    r = _parse_verdict("APPROVE_WITH_NOTES: minor typo on line 3")
    assert r.verdict == ReviewVerdict.APPROVE_WITH_NOTES
    assert "typo" in r.notes

def test_parse_rerun():
    r = _parse_verdict("REQUEST_RERUN: missing citations")
    assert r.verdict == ReviewVerdict.REQUEST_RERUN
    assert "citations" in r.notes

def test_parse_block():
    r = _parse_verdict("BLOCK: hallucinated API response")
    assert r.verdict == ReviewVerdict.BLOCK

def test_parse_garbage_default_safe():
    r = _parse_verdict("¯\\_(ツ)_/¯")
    assert r.verdict == ReviewVerdict.APPROVE_WITH_NOTES
```

- [ ] **Step 2: Run, expect pass** (parser implemented in Task 4).

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_qa_director.py
git commit -m "test(qa): verdict parser coverage"
```

### Task 6: Wire QA Director gatekeeper into chat route

**Files:**
- Modify: `apps/api/routes/chat.py`

- [ ] **Step 1: Read current `chat.py`** to find the post-stream completion point.

- [ ] **Step 2: Add `?raw=true` bypass + QA wrapping.** After the agent stream completes and the full text is collected (introduce a `collected: list[str]` accumulator if not present), add:

```python
from agents.qa_director import QADirector, ReviewVerdict

async def _gatekeep(text: str, original: str) -> tuple[str, str | None]:
    qa = QADirector()
    result = await qa.review(text, original)
    if result.verdict == ReviewVerdict.BLOCK:
        return f"[BLOCKED BY QA DIRECTOR] {result.notes}", "blocked"
    if result.verdict == ReviewVerdict.APPROVE_WITH_NOTES:
        return f"{text}\n\n---\nQA notes: {result.notes}", "approve_with_notes"
    return text, "approve"
```

In the route handler, accept `raw: bool = False` query param. After collecting agent output but before saving the AgentRun, call `_gatekeep` unless `raw` is set. Persist the verdict on the AgentRun (`qa_verdict` column added in Task 9).

- [ ] **Step 3: Add test**

```python
# apps/api/tests/test_chat_gatekeeper.py
import pytest
from fastapi.testclient import TestClient
from main import app

def test_chat_raw_param_bypasses_qa(monkeypatch):
    called = {"qa": False}
    from agents import qa_director
    async def fake_review(self, *a, **k):
        called["qa"] = True
        return qa_director.ReviewResult(qa_director.ReviewVerdict.APPROVE)
    monkeypatch.setattr(qa_director.QADirector, "review", fake_review)
    client = TestClient(app)
    client.post("/chat/inbox?raw=true", json={"prompt": "x"})
    assert called["qa"] is False
```

- [ ] **Step 4: Run, expect pass.**

- [ ] **Step 5: Commit**

```bash
git add apps/api/routes/chat.py apps/api/tests/test_chat_gatekeeper.py
git commit -m "feat(chat): pipe responses through QA Director gatekeeper"
```

### Task 7: Wire gatekeeper into scheduler

**Files:**
- Modify: `apps/api/scheduler.py`

- [ ] **Step 1: Read scheduler.py** to find the post-run artifact save.

- [ ] **Step 2: Insert `await QADirector().review(artifact_text, prompt)`** after the artifact save but before the `ActivityEvent(kind="completed")` publish. Persist the verdict on the AgentRun. On `REQUEST_RERUN`, retry the agent run **once** with an appended note `\n[QA rerun: {notes}]`. Cap at 1 retry.

- [ ] **Step 3: Test** with a fake QADirector that flips between rerun-then-approve and assert exactly two underlying runs occur.

```python
# apps/api/tests/test_scheduler_gatekeeper.py
import pytest
from agents.qa_director import ReviewResult, ReviewVerdict

@pytest.mark.asyncio
async def test_scheduler_reruns_once_on_request_rerun(monkeypatch):
    calls = {"agent": 0, "review": 0}
    verdicts = [
        ReviewResult(ReviewVerdict.REQUEST_RERUN, "weak"),
        ReviewResult(ReviewVerdict.APPROVE),
    ]
    async def fake_review(self, *a, **k):
        calls["review"] += 1
        return verdicts.pop(0)
    monkeypatch.setattr("agents.qa_director.QADirector.review", fake_review)

    # Replace scheduler's agent runner with a counter
    from scheduler import run_agent_with_qa  # introduced in this task
    async def fake_run(agent_id, prompt):
        calls["agent"] += 1
        return "result"
    monkeypatch.setattr("scheduler._raw_run_agent", fake_run)
    await run_agent_with_qa("inbox", "test")
    assert calls["agent"] == 2
    assert calls["review"] == 2
```

- [ ] **Step 4: Implement `run_agent_with_qa` in scheduler.py** as the gatekeeper-wrapped runner. Refactor existing scheduled callbacks to call it.

- [ ] **Step 5: Run, expect pass.**

- [ ] **Step 6: Commit**

```bash
git add apps/api/scheduler.py apps/api/tests/test_scheduler_gatekeeper.py
git commit -m "feat(scheduler): QA Director gatekeeper with single-rerun policy"
```

---

## Phase 3 — Job Schema + Handoff Endpoint

### Task 8: Add Job columns

**Files:**
- Modify: `apps/api/models.py:17-26`

- [ ] **Step 1: Edit `Job`** to add fields:

```python
class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    prompt: str
    status: JobStatus = Field(default=JobStatus.PENDING, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    # NEW
    kind: str = Field(default="agent_run", index=True)
    repo_path: Optional[str] = None
    base_branch: Optional[str] = None
    worker_branch: Optional[str] = None
    worker_pid: Optional[int] = None
    log_path: Optional[str] = None
    qa_verdict: Optional[str] = None
    qa_notes: Optional[str] = None
```

Also add to `AgentRun`:
```python
    qa_verdict: Optional[str] = None
    qa_notes: Optional[str] = None
```

- [ ] **Step 2: Migration.** Project uses SQLModel `init_db` (verify in `db.py`). If sqlite + `create_all`, dropping & recreating during dev is fine but we don't want to wipe state. Add a one-shot migration block in `db.py`'s `init_db()` that runs `ALTER TABLE job ADD COLUMN ...` for each new column inside a `try/except OperationalError: pass` (sqlite-tolerant idempotent migration).

- [ ] **Step 3: Run existing tests** — `pytest apps/api/tests/ -v`. Expect pass.

- [ ] **Step 4: Commit**

```bash
git add apps/api/models.py apps/api/db.py
git commit -m "feat(db): job columns for overnight workers + QA verdict"
```

### Task 9: Handoff Pydantic models

**Files:**
- Create: `apps/api/workers/__init__.py` (empty)
- Create: `apps/api/workers/handoff.py`

- [ ] **Step 1: Implement**

```python
# apps/api/workers/handoff.py
from pydantic import BaseModel, Field
from typing import Optional

class HandoffPayload(BaseModel):
    repo_path: str = Field(..., description="Absolute path to the source repo")
    base_branch: str = Field("main", description="Branch to fork the worktree from")
    prompt: str = Field(..., description="Task description for the headless worker")
    cwd_snapshot: Optional[str] = Field(None, description="git status --porcelain output")
    diff_snapshot: Optional[str] = Field(None, description="git diff of unstaged changes")
    recent_files: list[str] = Field(default_factory=list)
    conversation_tail: Optional[str] = Field(None, description="Last ~20 messages")

class HandoffResponse(BaseModel):
    job_id: int
    dashboard_url: str
    worktree_path: str
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/workers/
git commit -m "feat(workers): handoff payload models"
```

### Task 10: `POST /jobs/handoff` endpoint

**Files:**
- Modify: `apps/api/routes/jobs.py`

- [ ] **Step 1: Write failing test**

```python
# apps/api/tests/test_handoff_route.py
from fastapi.testclient import TestClient
from main import app
from db import init_db

def setup_module(_):
    init_db()

def test_handoff_creates_overnight_job(tmp_path):
    # Init a real git repo so the endpoint validates
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=tmp_path, check=True)

    client = TestClient(app)
    r = client.post("/jobs/handoff", json={
        "repo_path": str(tmp_path),
        "base_branch": "master",
        "prompt": "add a docstring"
    })
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] > 0
    assert "dashboard_url" in body
```

- [ ] **Step 2: Run, expect 404.**

- [ ] **Step 3: Add endpoint to `routes/jobs.py`**

```python
import os
from workers.handoff import HandoffPayload, HandoffResponse

@router.post("/handoff", response_model=HandoffResponse)
async def create_handoff(body: HandoffPayload, session: Session = Depends(get_session)):
    if not os.path.isdir(os.path.join(body.repo_path, ".git")):
        raise HTTPException(400, f"Not a git repo: {body.repo_path}")
    job = Job(
        agent_id="qa_director",
        prompt=body.prompt,
        kind="overnight_code",
        repo_path=body.repo_path,
        base_branch=body.base_branch,
        status=JobStatus.PENDING,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    # Defer worker spawn to background; Task 12 wires the actual worker
    from workers.claude_code_worker import enqueue_worker
    enqueue_worker(job.id, body)
    dashboard = os.environ.get("BORINA_DASHBOARD_URL", "http://localhost:3000")
    return HandoffResponse(
        job_id=job.id,
        dashboard_url=f"{dashboard}/jobs/{job.id}",
        worktree_path=f".borina-workers/{job.id}",
    )
```

- [ ] **Step 4: Stub `enqueue_worker`** in `workers/claude_code_worker.py` so the test can pass before Task 12 implements the real worker:

```python
# apps/api/workers/claude_code_worker.py (initial stub)
def enqueue_worker(job_id: int, payload) -> None:
    return  # implemented in Task 12
```

- [ ] **Step 5: Run, expect pass.**

- [ ] **Step 6: Commit**

```bash
git add apps/api/routes/jobs.py apps/api/workers/claude_code_worker.py apps/api/tests/test_handoff_route.py
git commit -m "feat(jobs): POST /jobs/handoff endpoint"
```

---

## Phase 4 — Claude Code Worker

### Task 11: Fake `claude` binary for tests

**Files:**
- Create: `apps/api/tests/fakes/fake_claude.py`

- [ ] **Step 1: Implement fake**

```python
#!/usr/bin/env python
"""Fake claude CLI: emits canned stream-json for worker tests."""
import json, sys, time

LINES = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "doing the work"}]}},
    {"type": "result", "subtype": "success", "result": "task complete"},
]
for line in LINES:
    sys.stdout.write(json.dumps(line) + "\n")
    sys.stdout.flush()
    time.sleep(0.01)
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/tests/fakes/
git commit -m "test(workers): fake claude binary for stream-json"
```

### Task 12: Implement `claude_code_worker`

**Files:**
- Modify: `apps/api/workers/claude_code_worker.py` (replace stub)
- Test: `apps/api/tests/test_claude_code_worker.py`

- [ ] **Step 1: Write test**

```python
# apps/api/tests/test_claude_code_worker.py
import os, sys, subprocess, time, pytest
from pathlib import Path
from workers.claude_code_worker import run_worker_sync
from workers.handoff import HandoffPayload

def _init_repo(path: Path):
    subprocess.run(["git", "init"], cwd=path, check=True)
    (path / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=path, check=True)

def test_worker_creates_worktree_and_runs(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    fake_bin = Path(__file__).parent / "fakes" / "fake_claude.py"
    monkeypatch.setenv("BORINA_CLAUDE_CMD", f"{sys.executable} {fake_bin}")
    payload = HandoffPayload(
        repo_path=str(tmp_path), base_branch="master", prompt="do the thing"
    )
    result = run_worker_sync(job_id=999, payload=payload)
    assert result["exit_code"] == 0
    assert "task complete" in result["log_tail"]
    assert (tmp_path / ".." / ".borina-workers" / "999").resolve().exists() or \
           (Path(".borina-workers") / "999").exists()
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement worker**

```python
# apps/api/workers/claude_code_worker.py
"""Headless Claude Code worker. Spawns `claude -p` in a per-job git worktree."""

import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from workers.handoff import HandoffPayload

WORKTREE_ROOT = Path(os.environ.get("BORINA_WORKTREE_ROOT", ".borina-workers")).resolve()
LOG_ROOT = Path(os.environ.get("BORINA_LOG_ROOT", "logs/jobs")).resolve()
DEFAULT_CMD = os.environ.get("BORINA_CLAUDE_CMD", "claude")
DEFAULT_TIMEOUT = int(os.environ.get("BORINA_WORKER_TIMEOUT", "14400"))

@dataclass
class WorkerResult:
    exit_code: int
    worktree: str
    log_path: str
    log_tail: str
    diff: str

def _create_worktree(repo: Path, job_id: int, base_branch: str) -> Path:
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    target = WORKTREE_ROOT / str(job_id)
    if target.exists():
        return target
    branch = f"borina/job-{job_id}"
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(target), base_branch],
        cwd=repo, check=True,
    )
    return target

def _write_task_file(worktree: Path, payload: HandoffPayload) -> None:
    parts = [f"# Borina Task\n\n{payload.prompt}\n"]
    if payload.cwd_snapshot:
        parts.append(f"\n## git status\n```\n{payload.cwd_snapshot}\n```\n")
    if payload.diff_snapshot:
        parts.append(f"\n## diff\n```diff\n{payload.diff_snapshot}\n```\n")
    if payload.recent_files:
        parts.append("\n## Recent files\n" + "\n".join(f"- {f}" for f in payload.recent_files) + "\n")
    if payload.conversation_tail:
        parts.append(f"\n## Conversation context\n{payload.conversation_tail}\n")
    (worktree / "BORINA_TASK.md").write_text("".join(parts), encoding="utf-8")

def run_worker_sync(job_id: int, payload: HandoffPayload) -> dict:
    """Run synchronously. Returns dict for the calling thread."""
    repo = Path(payload.repo_path).resolve()
    worktree = _create_worktree(repo, job_id, payload.base_branch)
    _write_task_file(worktree, payload)

    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / f"{job_id}.jsonl"
    cmd = shlex.split(DEFAULT_CMD) + [
        "-p", (worktree / "BORINA_TASK.md").read_text(encoding="utf-8"),
        "--output-format", "stream-json",
    ]
    with open(log_path, "w", encoding="utf-8") as logf:
        proc = subprocess.run(
            cmd, cwd=worktree, stdout=logf, stderr=subprocess.STDOUT,
            timeout=DEFAULT_TIMEOUT,
        )
    log_tail = "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-30:])
    diff = subprocess.run(
        ["git", "diff", payload.base_branch],
        cwd=worktree, capture_output=True, text=True,
    ).stdout
    return {
        "exit_code": proc.returncode,
        "worktree": str(worktree),
        "log_path": str(log_path),
        "log_tail": log_tail,
        "diff": diff,
    }

def enqueue_worker(job_id: int, payload: HandoffPayload) -> None:
    """Spawn worker in a background thread. Job DB updates happen in callback."""
    def _runner():
        from db import session_scope  # see Task 8 helper
        from models import Job, JobStatus
        from datetime import datetime
        try:
            result = run_worker_sync(job_id, payload)
            with session_scope() as s:
                job = s.get(Job, job_id)
                job.status = JobStatus.COMPLETED if result["exit_code"] == 0 else JobStatus.FAILED
                job.completed_at = datetime.utcnow()
                job.log_path = result["log_path"]
                job.worker_branch = f"borina/job-{job_id}"
                s.add(job); s.commit()
            _post_completion_qa(job_id, result, payload.prompt)
        except Exception as e:
            with session_scope() as s:
                job = s.get(Job, job_id)
                if job:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    s.add(job); s.commit()
    threading.Thread(target=_runner, daemon=True).start()

def _post_completion_qa(job_id: int, result: dict, prompt: str) -> None:
    """Run QA Director review on the diff + summary, then notify."""
    import asyncio
    from agents.qa_director import QADirector
    from models import Job
    from db import session_scope
    artifact = f"## Diff\n{result['diff']}\n\n## Log tail\n{result['log_tail']}"
    review = asyncio.run(QADirector().review(artifact, prompt))
    with session_scope() as s:
        job = s.get(Job, job_id)
        job.qa_verdict = review.verdict.value
        job.qa_notes = review.notes
        s.add(job); s.commit()
    _notify(job_id, review)

def _notify(job_id: int, review) -> None:
    """Telegram + vault note hook. Implemented loosely; integration in Task 14."""
    pass
```

- [ ] **Step 4: Add `session_scope` helper to `db.py`** if missing:

```python
from contextlib import contextmanager
@contextmanager
def session_scope():
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()
```

- [ ] **Step 5: Run worker test, expect pass.**

- [ ] **Step 6: Commit**

```bash
git add apps/api/workers/claude_code_worker.py apps/api/db.py apps/api/tests/test_claude_code_worker.py
git commit -m "feat(workers): headless claude-code worker with worktree isolation"
```

### Task 13: Job log SSE + cancel + cleanup endpoints

**Files:**
- Modify: `apps/api/routes/jobs.py`

- [ ] **Step 1: Add endpoints**

```python
import os, signal
from fastapi.responses import StreamingResponse

@router.get("/{job_id}/log")
async def stream_log(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job or not job.log_path:
        raise HTTPException(404, "No log")
    async def gen():
        with open(job.log_path, "r", encoding="utf-8") as f:
            for line in f:
                yield f"data: {line.rstrip()}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@router.post("/{job_id}/cancel")
async def cancel_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    if job.worker_pid:
        try:
            os.kill(job.worker_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    job.status = JobStatus.CANCELLED
    session.add(job); session.commit()
    return {"ok": True}

@router.post("/{job_id}/cleanup")
async def cleanup_job(job_id: int, session: Session = Depends(get_session)):
    import shutil
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(409, "Job still active")
    worktree = f".borina-workers/{job_id}"
    if os.path.exists(worktree):
        # Use git worktree remove for cleanliness
        if job.repo_path:
            import subprocess
            subprocess.run(["git", "worktree", "remove", "--force", worktree],
                           cwd=job.repo_path, check=False)
        else:
            shutil.rmtree(worktree, ignore_errors=True)
    return {"ok": True}
```

- [ ] **Step 2: Smoke test cancel + cleanup with a fake job row.**

```python
# apps/api/tests/test_handoff_route.py (append)
def test_cleanup_requires_terminal_state(tmp_path):
    from db import session_scope
    from models import Job, JobStatus
    with session_scope() as s:
        j = Job(agent_id="qa_director", prompt="x", kind="overnight_code",
                status=JobStatus.RUNNING)
        s.add(j); s.commit(); s.refresh(j); jid = j.id
    client = TestClient(app)
    r = client.post(f"/jobs/{jid}/cleanup")
    assert r.status_code == 409
```

- [ ] **Step 3: Run, expect pass.**

- [ ] **Step 4: Commit**

```bash
git add apps/api/routes/jobs.py apps/api/tests/test_handoff_route.py
git commit -m "feat(jobs): SSE log stream + cancel/cleanup endpoints"
```

### Task 14: Telegram + vault notification on worker completion

**Files:**
- Modify: `apps/api/workers/claude_code_worker.py` (`_notify`)

- [ ] **Step 1: Implement `_notify`** using whatever existing Telegram helper the project has (search for `telegram` / `bot.send_message` in `apps/api/`). If no helper exists, use `requests.post` to the Bot API with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars.

```python
def _notify(job_id: int, review) -> None:
    import os, requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    dash = os.environ.get("BORINA_DASHBOARD_URL", "http://localhost:3000")
    if not (token and chat):
        return
    icon = {"approve": "✅", "approve_with_notes": "⚠️",
            "request_rerun": "🔁", "block": "⛔"}.get(review.verdict.value, "•")
    msg = f"{icon} Job {job_id} done — {review.verdict.value}\n{review.notes[:300]}\n{dash}/jobs/{job_id}"
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": msg}, timeout=10,
        )
    except Exception:
        pass
    # Vault note (best effort)
    vault = os.environ.get("OBSIDIAN_VAULT_PATH")
    if vault:
        from pathlib import Path
        from datetime import date
        notes_dir = Path(vault) / "borina-jobs"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / f"{date.today()}-job-{job_id}.md").write_text(msg, encoding="utf-8")
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/workers/claude_code_worker.py
git commit -m "feat(workers): Telegram + vault notification on completion"
```

---

## Phase 5 — `/handoff` Slash Command

### Task 15: Write the slash command

**Files:**
- Create: `~/.claude/commands/handoff.md` (user home, NOT repo)

- [ ] **Step 1: Write file**

```markdown
---
description: Hand the current in-flight task off to a borina-mesh overnight worker
allowed-tools: Bash(git:*), Bash(curl:*), Read
---

You are handing off the user's current task to a borina-mesh overnight worker.

## Step 1
Run these commands in parallel and capture output:
- `git rev-parse --show-toplevel` — get repo root
- `git rev-parse --abbrev-ref HEAD` — get current branch
- `git status --porcelain` — get dirty state
- `git diff` — get unstaged changes

## Step 2
Build a one-paragraph task description from the user's request and the most recent ~20 messages of this conversation. Include any plan/spec the user has been working on.

## Step 3
POST to borina:

```bash
curl -s -X POST http://localhost:8000/jobs/handoff \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "repo_path": "<repo root from step 1>",
  "base_branch": "<branch from step 1>",
  "prompt": "<task description from step 2>",
  "cwd_snapshot": "<git status output>",
  "diff_snapshot": "<git diff output>",
  "recent_files": [<files touched recently>],
  "conversation_tail": "<last 20 messages summarized>"
}
EOF
```

## Step 4
Print the returned `job_id` and `dashboard_url` to the user with a one-line confirmation: "Handed off as job #N — track at <dashboard_url>".
```

- [ ] **Step 2: Verify file is at the user home commands path** (NOT committed to the borina repo).

- [ ] **Step 3: Commit reference doc inside repo**

```bash
mkdir -p borina-mesh/docs/integrations
cp ~/.claude/commands/handoff.md borina-mesh/docs/integrations/handoff-slash-command.md
git add borina-mesh/docs/integrations/handoff-slash-command.md
git commit -m "docs(integrations): handoff slash command reference"
```

---

## Phase 6 — Front Page UI Refresh

### Task 16: Agent icon + color map

**Files:**
- Create: `apps/web/lib/agent-icons.ts`

- [ ] **Step 1: Implement**

```typescript
// apps/web/lib/agent-icons.ts
import {
  Briefcase, Search, Compass, LineChart, Megaphone,
  Inbox, TrendingUp, ShieldCheck, type LucideIcon,
} from "lucide-react";

export type AgentVisual = { icon: LucideIcon; accent: string };

export const AGENT_VISUALS: Record<string, AgentVisual> = {
  ceo:         { icon: Briefcase,    accent: "#7c3aed" }, // violet
  researcher:  { icon: Search,       accent: "#0ea5e9" }, // sky
  scout:       { icon: Compass,      accent: "#22c55e" }, // green
  trader:      { icon: LineChart,    accent: "#f59e0b" }, // amber
  adset:       { icon: Megaphone,    accent: "#ec4899" }, // pink
  inbox:       { icon: Inbox,        accent: "#64748b" }, // slate
  polymarket:  { icon: TrendingUp,   accent: "#14b8a6" }, // teal
  qa_director: { icon: ShieldCheck,  accent: "#dc2626" }, // red
};

export function getAgentVisual(id: string): AgentVisual {
  return AGENT_VISUALS[id] ?? { icon: Briefcase, accent: "#94a3b8" };
}
```

- [ ] **Step 2: Verify Lucide installed** — check `apps/web/package.json`. If missing: `cd apps/web && npm install lucide-react`.

- [ ] **Step 3: Commit**

```bash
git add apps/web/lib/agent-icons.ts apps/web/package.json apps/web/package-lock.json
git commit -m "feat(web): agent visual map (icons + accent colors)"
```

### Task 17: ModelBadge + StatusDot components

**Files:**
- Create: `apps/web/components/model-badge.tsx`
- Create: `apps/web/components/status-dot.tsx`

- [ ] **Step 1: Implement ModelBadge**

```tsx
// apps/web/components/model-badge.tsx
const COLORS: Record<string, string> = {
  "claude-opus-4-6": "bg-violet-100 text-violet-700",
  "claude-sonnet-4-6": "bg-sky-100 text-sky-700",
  "claude-haiku-4-5-20251001": "bg-emerald-100 text-emerald-700",
};
const LABELS: Record<string, string> = {
  "claude-opus-4-6": "Opus",
  "claude-sonnet-4-6": "Sonnet",
  "claude-haiku-4-5-20251001": "Haiku",
};
export function ModelBadge({ model }: { model: string }) {
  const cls = COLORS[model] ?? "bg-slate-100 text-slate-700";
  const label = LABELS[model] ?? model;
  return <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${cls}`}>{label}</span>;
}
```

- [ ] **Step 2: Implement StatusDot**

```tsx
// apps/web/components/status-dot.tsx
type Status = "idle" | "running" | "qa_flagged" | "error";
const COLORS: Record<Status, string> = {
  idle:       "bg-emerald-500",
  running:    "bg-sky-500 animate-pulse",
  qa_flagged: "bg-amber-500",
  error:      "bg-red-500",
};
export function StatusDot({ status }: { status: Status }) {
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${COLORS[status]}`} />;
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/model-badge.tsx apps/web/components/status-dot.tsx
git commit -m "feat(web): model badge + status dot primitives"
```

### Task 18: Rewrite agent-card.tsx

**Files:**
- Modify: `apps/web/components/agent-card.tsx` (full rewrite)
- Modify: `apps/web/lib/types.ts`

- [ ] **Step 1: Extend `Agent` type** in `lib/types.ts`:

```typescript
export type Agent = {
  id: string;
  name: string;
  tagline: string;
  model: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  qa_verdict?: string | null;
  status?: "idle" | "running" | "qa_flagged" | "error";
};
```

- [ ] **Step 2: Rewrite `agent-card.tsx`**

```tsx
// apps/web/components/agent-card.tsx
"use client";
import Link from "next/link";
import { getAgentVisual } from "@/lib/agent-icons";
import { ModelBadge } from "./model-badge";
import { StatusDot } from "./status-dot";
import type { Agent } from "@/lib/types";

function relativeTime(iso?: string | null) {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function AgentCard({ agent }: { agent: Agent }) {
  const { icon: Icon, accent } = getAgentVisual(agent.id);
  const status = agent.status ?? "idle";
  return (
    <Link
      href={`/jobs?agent=${agent.id}`}
      className="group block rounded-xl border border-slate-200 bg-white p-5 hover:border-slate-400 hover:shadow-md transition"
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-11 h-11 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${accent}1a`, color: accent }}
        >
          <Icon className="w-6 h-6" strokeWidth={1.75} />
        </div>
        <StatusDot status={status} />
      </div>
      <div className="font-semibold text-slate-900 mb-1">{agent.name}</div>
      <div className="text-sm text-slate-500 mb-4 line-clamp-2 min-h-[2.5rem]">{agent.tagline}</div>
      <div className="flex items-center justify-between text-xs text-slate-500">
        <ModelBadge model={agent.model} />
        <span>last: {relativeTime(agent.last_run_at)}</span>
      </div>
    </Link>
  );
}
```

- [ ] **Step 3: Update `app/page.tsx`** to drop the `emoji` prop and ensure agents come back from the API with `model` populated. Also fetch `/agents/models` and merge if backend `to_dict` doesn't include model (it does, via the property added in Task 2).

- [ ] **Step 4: Visually verify** — start dev server, open `localhost:3000`, confirm 8 cards render with icons/colors/badges and no emoji.

- [ ] **Step 5: Commit**

```bash
git add apps/web/
git commit -m "feat(web): status-rich agent tiles (icons, model badges, status dots)"
```

### Task 19: Jobs page — overnight workers section

**Files:**
- Modify: `apps/web/app/jobs/page.tsx`
- Modify: `apps/web/lib/api.ts`

- [ ] **Step 1: Add API helpers**

```typescript
// apps/web/lib/api.ts (append)
export async function createHandoff(body: {
  repo_path: string; base_branch: string; prompt: string;
}) {
  const r = await fetch(`${API_BASE}/jobs/handoff`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}
export function streamJobLog(jobId: number, onLine: (line: string) => void) {
  const es = new EventSource(`${API_BASE}/jobs/${jobId}/log`);
  es.onmessage = (e) => onLine(e.data);
  return () => es.close();
}
export async function cancelJob(jobId: number) {
  return fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: "POST" });
}
```

- [ ] **Step 2: Add a "New Overnight Job" modal + an "Overnight Workers" section** that lists jobs with `kind === "overnight_code"`, shows the live log via `streamJobLog`, and exposes Cancel and Cleanup buttons. Reuse the existing job list component if there is one — extend rather than fork.

- [ ] **Step 3: Manual test:** trigger a handoff via the modal against a sandbox repo with `BORINA_CLAUDE_CMD=python tests/fakes/fake_claude.py` set; verify log appears live, completion fires.

- [ ] **Step 4: Commit**

```bash
git add apps/web/
git commit -m "feat(web): overnight workers section with live log + handoff modal"
```

---

## Phase 7 — Verification

### Task 20: Full-suite verification

- [ ] **Step 1:** `cd borina-mesh/apps/api && pytest -v` — expect all green.
- [ ] **Step 2:** `cd borina-mesh/apps/web && npm run build` — expect clean build.
- [ ] **Step 3:** Start API + web locally, confirm:
  - Front page shows 8 status-rich cards (incl. QA Director).
  - Chat with `inbox` agent — verify QA notes appear in response (or `?raw=true` bypasses).
  - Trigger handoff via slash command on a sandbox repo — verify Telegram + dashboard update.
- [ ] **Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore: verification fixes"
```

---

## Self-Review Notes

- **Spec coverage:** All 6 spec components mapped: model tiering (Tasks 1-3), QA Director (4-7), job schema + handoff (8-10), worker (11-14), slash command (15), UI (16-19). Verification (20).
- **Open question from spec — `dispatch` parallel default:** resolved: serial in this plan; parallelism is a follow-up.
- **Open question — log retention:** local-only with manual cleanup via `/jobs/{id}/cleanup`. Vault note carries the summary.
- **Open question — Lucide icon mapping:** locked in Task 16.
- **Migration risk:** Task 8 uses idempotent `ALTER TABLE` in `init_db` to avoid wiping the dev DB. Verify `db.py` actually exposes `init_db` before running.
