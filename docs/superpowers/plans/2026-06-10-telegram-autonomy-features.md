# Telegram Autonomy Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three Bo-picked features: (A) every dispatch result is written back into the Obsidian vault so the mesh "saves what it works on", (B) replying to a bot message in Telegram continues that topic with the same agent, (C) a `mission: …` Telegram prompt fans out to multiple agents via the CEO and returns one synthesized report.

**Architecture:** All three build on the existing dispatch pipeline (`routes/telegram.py process_update` → `dispatch/worker.py` queue → `dispatch/dispatcher.py _produce_and_reply` → tmux agent pool). Write-back is a post-completion hook in the dispatcher; threads are a new `TelegramThread` table consulted before intent resolution; missions are a new `task_type` that swaps the single `run_agent` call for a decompose→fan-out→synthesize pipeline. **Safety invariants unchanged:** forbidden-action gate always runs first, all dispatched agents are read-only, planner/calendar write paths untouched.

**Tech Stack:** FastAPI + SQLModel/SQLite, tmux agent pool (`agents/runner_v2.run_agent_task`), pytest (hermetic via `conftest.py`). No new dependencies.

**Working dir:** `~/borina-mesh/apps/api`. Test command: `.venv/bin/python -m pytest <file> -q`. Suite must stay green (216 at plan time). Commit per task from `~/borina-mesh`.

**Known sharp edges (learned live, do not rediscover):**
- tmux pane capture is lossy — JSON crossing pane lines breaks string literals. Any JSON contract with an agent needs the newline-collapse repair (see `planner._parse_agent_proposals`) and ideally file handoff. For missions, decompose JSON is short (≤4 items, short prompts) so pane + repair is acceptable.
- `conftest.py` sets `OBSIDIAN_VAULT_PATH=""` — vault code must treat empty env as "disabled, return None" so tests stay hermetic.
- `dispatch/worker.run_job` re-resolves intent from the stored prompt; anything the webhook decided (thread agent, mission type) must survive that re-resolution (Task 3 fixes this).

---

## File Structure

```
apps/api/
  dispatch/
    vault_writeback.py      # NEW (A): dispatch result → vault report + daily-note link
    mission.py              # NEW (C): decompose → fan-out → synthesize
    dispatcher.py           # MODIFY (A: hook; B: send returns message_id, record thread; C: mission branch)
    worker.py               # MODIFY (B: honor job.agent_id over re-resolved intent)
    intent.py               # MODIFY (C: "mission:" alias → ceo/mission)
  models.py                 # MODIFY (B: TelegramThread table)
  routes/telegram.py        # MODIFY (B: reply_to_message → thread lookup)
  tests/
    test_vault_writeback.py # NEW (A)
    test_telegram_threads.py# NEW (B)
    test_mission.py         # NEW (C)
```

---

# Feature A — Obsidian write-back

### Task 1: `dispatch/vault_writeback.py` + tests

**Files:**
- Create: `apps/api/dispatch/vault_writeback.py`
- Test: `apps/api/tests/test_vault_writeback.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_vault_writeback.py
"""Obsidian write-back: every dispatch result is distilled into the vault
(04-resources/reports + a link in the daily note) so the mesh reuses what it
already learned. Disabled (returns None) when no vault is configured."""
from pathlib import Path

import pytest

from dispatch.vault_writeback import save_dispatch_to_vault


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_writes_report_with_frontmatter_and_body(vault):
    p = save_dispatch_to_vault(
        agent="researcher", prompt="what moved BTC overnight",
        markdown="# BTC\n\nIt wicked below 60k.", day="2026-06-10", job_id=42,
    )
    assert p == vault / "04-resources" / "reports" / "2026-06-10-researcher-job42.md"
    text = p.read_text()
    assert text.startswith("---\n")
    assert "agent: researcher" in text
    assert "It wicked below 60k." in text
    assert "[[2026-06-10]]" in text  # links back to the daily note


def test_appends_link_to_existing_daily_note(vault):
    daily = vault / "01-daily" / "2026-06-10.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-06-10 Session Notes\n\n## Summary\n")
    save_dispatch_to_vault("trader", "bot health", "# ok", "2026-06-10", 7)
    text = daily.read_text()
    assert "## Mesh outputs" in text
    assert "[[reports/2026-06-10-trader-job7]]" in text
    assert text.startswith("# 2026-06-10 Session Notes")  # appended, not overwritten


def test_creates_daily_note_when_missing(vault):
    save_dispatch_to_vault("researcher", "x", "# y", "2026-06-11", 1)
    daily = vault / "01-daily" / "2026-06-11.md"
    assert daily.exists()
    assert "## Mesh outputs" in daily.read_text()


def test_disabled_without_vault(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    assert save_dispatch_to_vault("a", "b", "# c", "2026-06-10", 1) is None


def test_never_raises(monkeypatch, tmp_path):
    # Point the vault at a FILE so mkdir explodes internally.
    f = tmp_path / "not-a-dir"
    f.write_text("x")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(f))
    assert save_dispatch_to_vault("a", "b", "# c", "2026-06-10", 1) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_vault_writeback.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dispatch.vault_writeback'`

- [ ] **Step 3: Implement the module**

```python
# apps/api/dispatch/vault_writeback.py
"""Write a completed dispatch into the Obsidian vault (spec: Bo 2026-06-10,
"it should save the things it works on").

Report file: 04-resources/reports/{day}-{agent}-job{job_id}.md with
frontmatter; a link line is appended to 01-daily/{day}.md under
"## Mesh outputs" (note + section created if missing). Returns the report
path, or None when no vault is configured or on ANY error — write-back must
never break a dispatch reply.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_DAILY_TEMPLATE = """---
title: '{day}'
type: daily
tags: [daily]
---

# {day} Session Notes

## Mesh outputs
"""


def _slug(agent: str, job_id: int, day: str) -> str:
    safe_agent = re.sub(r"[^a-z0-9-]", "", agent.lower()) or "agent"
    return f"{day}-{safe_agent}-job{job_id}"


def save_dispatch_to_vault(
    agent: str, prompt: str, markdown: str, day: str, job_id: int
) -> Optional[Path]:
    root = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not root:
        return None
    try:
        vault = Path(root)
        stem = _slug(agent, job_id, day)

        report = vault / "04-resources" / "reports" / f"{stem}.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        prompt_line = prompt.replace("\n", " ")[:200]
        report.write_text(
            "---\n"
            f"title: '{stem}'\n"
            "type: mesh-report\n"
            f"agent: {agent}\n"
            f"date: {day}\n"
            f"prompt: '{prompt_line.replace(chr(39), chr(34))}'\n"
            "tags: [mesh-report]\n"
            "---\n\n"
            f"{markdown.strip()}\n\n"
            f"Back to [[{day}]]\n"
        )

        daily = vault / "01-daily" / f"{day}.md"
        daily.parent.mkdir(parents=True, exist_ok=True)
        text = daily.read_text() if daily.exists() else _DAILY_TEMPLATE.format(day=day)
        if "## Mesh outputs" not in text:
            text += "\n## Mesh outputs\n"
        text += f"- [[reports/{stem}]] — {agent}: {prompt_line[:80]}\n"
        daily.write_text(text)
        return report
    except Exception as exc:  # noqa: BLE001 — never break the reply path
        print(f"[vault-writeback] failed: {exc}")
        return None
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_vault_writeback.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add apps/api/dispatch/vault_writeback.py apps/api/tests/test_vault_writeback.py
git commit -m "phase6(vault): dispatch write-back module — report file + daily-note link (§A)"
```

### Task 2: Hook write-back into the dispatcher

**Files:**
- Modify: `apps/api/dispatch/dispatcher.py` (in `_produce_and_reply`, right after `_complete_job(job_id, markdown)`)
- Test: append to `apps/api/tests/test_vault_writeback.py`

- [ ] **Step 1: Write the failing test**

```python
# append to apps/api/tests/test_vault_writeback.py
import asyncio


def test_dispatcher_calls_writeback(monkeypatch, tmp_path):
    """_produce_and_reply persists to the vault after completing the job."""
    from dispatch import dispatcher
    from dispatch.intent import Intent

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    async def fake_run_agent(agent_id, prompt):
        return "# report\n\nbody"
    monkeypatch.setattr(dispatcher, "run_agent", fake_run_agent)
    monkeypatch.setattr(dispatcher, "render_markdown_pdf", lambda md, p: p)
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)

    intent = Intent(raw_text="what moved", agent="researcher",
                    task_type="general_question", confidence=0.5, source="fallback")
    res = asyncio.run(dispatcher.dispatch_intent(intent, chat_id=6452258223))
    reports = list((tmp_path / "04-resources" / "reports").glob("*.md"))
    assert len(reports) == 1
    assert "body" in reports[0].read_text()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_vault_writeback.py::test_dispatcher_calls_writeback -q`
Expected: FAIL — no reports written (glob empty)

- [ ] **Step 3: Add the hook in `_produce_and_reply`**

In `apps/api/dispatch/dispatcher.py`, immediately after the existing `_complete_job(job_id, markdown)` line:

```python
    _complete_job(job_id, markdown)

    # Persist what we learned into the Obsidian vault (no-op without a vault;
    # never raises) so briefs/planner/agents can reuse it.
    from dispatch.vault_writeback import save_dispatch_to_vault
    save_dispatch_to_vault(intent.agent, intent.raw_text, markdown, day, job_id)
```

- [ ] **Step 4: Run the file, then the full suite**

Run: `.venv/bin/python -m pytest tests/test_vault_writeback.py -q` → 6 passed
Run: `.venv/bin/python -m pytest -q` → 222 passed (216 + 6)

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add -A && git commit -m "phase6(vault): dispatcher persists every dispatch result to the vault (§A)"
```

---

# Feature B — Telegram threads (reply = follow-up)

### Task 3: Worker honors the job row's agent (prerequisite)

`worker.run_job` currently re-resolves intent from the prompt text and uses
`intent.agent` — that would send every thread follow-up to the fallback
researcher instead of the thread's agent. The Job row's `agent_id` (decided by
the webhook at enqueue time) is authoritative.

**Files:**
- Modify: `apps/api/dispatch/worker.py:136-143` (`run_job`)
- Test: append to `apps/api/tests/test_background_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# append to apps/api/tests/test_background_jobs.py
def test_run_job_honors_job_agent_over_reresolution(monkeypatch):
    """A queued job's agent_id (set by the webhook/thread lookup) wins over
    what re-resolving the prompt text would pick."""
    import asyncio
    from dispatch import worker, dispatcher
    from dispatch.worker import enqueue_job

    seen = {}
    async def fake_produce(intent, chat_id, job_id, requested_at):
        seen["agent"] = intent.agent
    monkeypatch.setattr(dispatcher, "_produce_and_reply", fake_produce)
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)

    # "what changed overnight" re-resolves to researcher (fallback) — the job
    # row says trader (thread follow-up), and trader must win.
    job = enqueue_job("what changed overnight", "trader", 9001, 6452258223)
    asyncio.run(worker.run_job(job.id))
    assert seen["agent"] == "trader"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_background_jobs.py::test_run_job_honors_job_agent_over_reresolution -q`
Expected: FAIL — `seen["agent"] == "researcher"`

- [ ] **Step 3: Fix `run_job`**

In `apps/api/dispatch/worker.py`, the current block:

```python
    with session_scope() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        chat_id = job.telegram_chat_id
        prompt = job.prompt

    intent = resolve_intent(prompt)
    if not intent.dispatchable:
        _fail_job(job_id, "intent no longer dispatchable")
        return
```

becomes:

```python
    with session_scope() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        chat_id = job.telegram_chat_id
        prompt = job.prompt
        job_agent = job.agent_id

    intent = resolve_intent(prompt)
    if not intent.dispatchable:
        _fail_job(job_id, "intent no longer dispatchable")
        return
    # The webhook already routed this job (thread follow-ups, mission type
    # survive via task_type re-detection); the row's agent is authoritative.
    if job_agent:
        intent.agent = job_agent
```

- [ ] **Step 4: Run the test file + full suite**

Run: `.venv/bin/python -m pytest tests/test_background_jobs.py -q` → all pass
Run: `.venv/bin/python -m pytest -q` → 223 passed

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add -A && git commit -m "phase6(threads): worker honors job.agent_id over prompt re-resolution (§B prereq)"
```

### Task 4: `TelegramThread` table + reply message-id capture

**Files:**
- Modify: `apps/api/models.py` (add table at the end)
- Modify: `apps/api/dispatch/dispatcher.py` (`send_telegram_message` returns the id; `_produce_and_reply` records the thread)
- Test: create `apps/api/tests/test_telegram_threads.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_telegram_threads.py
"""Telegram threads: replying to a bot report message continues that topic
with the SAME agent. The bot's outbound report message_id is recorded per job;
process_update consults it before intent resolution. Forbidden gate still
runs on follow-up text."""
import asyncio
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

import routes.telegram as tg
from db import engine, session_scope
from dispatch import dispatcher
from dispatch.intent import Intent
from models import TelegramThread

BO = 6452258223


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    with session_scope() as s:
        for t in s.exec(select(TelegramThread)).all():
            s.delete(t)
        s.commit()
    yield


def test_record_and_find_thread():
    dispatcher._record_thread(chat_id=BO, message_id=555, agent_id="trader",
                              job_id=12, prompt="bot health")
    t = dispatcher.find_thread(chat_id=BO, message_id=555)
    assert t is not None and t.agent_id == "trader" and t.job_id == 12
    assert dispatcher.find_thread(chat_id=BO, message_id=999) is None


def test_produce_and_reply_records_thread(monkeypatch, tmp_path):
    async def fake_run_agent(agent_id, prompt):
        return "# r\n\nbody"
    monkeypatch.setattr(dispatcher, "run_agent", fake_run_agent)
    monkeypatch.setattr(dispatcher, "render_markdown_pdf", lambda md, p: p)
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: 777)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)
    intent = Intent(raw_text="bot health check", agent="trader",
                    task_type="bot_health", confidence=0.8, source="alias")
    asyncio.run(dispatcher.dispatch_intent(intent, chat_id=BO))
    threads = []
    with Session(engine) as s:
        threads = s.exec(select(TelegramThread).where(TelegramThread.message_id == 777)).all()
    assert len(threads) == 1 and threads[0].agent_id == "trader"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_telegram_threads.py -q`
Expected: FAIL — `ImportError: cannot import name 'TelegramThread'`

- [ ] **Step 3: Add the model**

Append to `apps/api/models.py` (match the file's existing SQLModel table style):

```python
class TelegramThread(SQLModel, table=True):
    """Maps a bot-sent Telegram message to the job/agent that produced it, so
    a user reply to that message continues the topic with the same agent."""
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    message_id: int = Field(index=True)
    agent_id: str
    job_id: Optional[int] = None
    prompt: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

(SQLite: `init_db()`'s `create_all` creates new tables automatically — no migration needed.)

- [ ] **Step 4: Make `send_telegram_message` return the message id, record threads**

In `apps/api/dispatch/dispatcher.py` replace `send_telegram_message` with:

```python
def send_telegram_message(chat_id: int, text: str) -> Optional[int]:
    """Send; returns Telegram's message_id (None offline/on failure) so the
    reply can be recorded as a thread anchor."""
    from integrations.base import http_post_json

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    resp = http_post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        },
    )
    try:
        return int((resp.get("result") or {}).get("message_id"))
    except Exception:  # noqa: BLE001
        return None
```

Add next to `_create_job`:

```python
def _record_thread(chat_id: int, message_id: Optional[int], agent_id: str,
                   job_id: int, prompt: str) -> None:
    if not message_id:
        return
    from db import session_scope
    from models import TelegramThread

    with session_scope() as s:
        s.add(TelegramThread(chat_id=chat_id, message_id=message_id,
                             agent_id=agent_id, job_id=job_id, prompt=prompt[:300]))
        s.commit()


def find_thread(chat_id: int, message_id: int):
    from db import session_scope
    from models import TelegramThread
    from sqlmodel import select

    with session_scope() as s:
        return s.exec(
            select(TelegramThread).where(
                TelegramThread.chat_id == chat_id,
                TelegramThread.message_id == message_id,
            )
        ).first()
```

And in `_produce_and_reply`, replace the reply-send block:

```python
    text = format_dispatch_reply(
        agent=intent.agent, markdown=markdown, deep_link=deep_link
    )
    sent_id = send_telegram_message(chat_id, text)
    _record_thread(chat_id, sent_id, intent.agent, job_id, intent.raw_text)
    send_telegram_document(chat_id, pdf_path, caption=f"{intent.agent} report")
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_threads.py -q` → 2 passed
Run: `.venv/bin/python -m pytest -q` → full suite green (225)

- [ ] **Step 6: Commit**

```bash
cd ~/borina-mesh && git add -A && git commit -m "phase6(threads): TelegramThread table; reply message_id recorded per dispatch (§B)"
```

### Task 5: Route replies through the thread

**Files:**
- Modify: `apps/api/routes/telegram.py` (`process_update`, between the voice block and "# 3. Intent.")
- Test: append to `apps/api/tests/test_telegram_threads.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to apps/api/tests/test_telegram_threads.py
def _spy_enqueue(monkeypatch):
    calls = []
    def fake(text, agent, update_id, chat_id):
        calls.append({"text": text, "agent": agent})
        return SimpleNamespace(id=len(calls))
    monkeypatch.setattr(tg, "enqueue_job", fake)
    return calls


def _reply_update(update_id, chat_id, text, reply_to_id):
    return {"update_id": update_id,
            "message": {"chat": {"id": chat_id}, "text": text,
                        "reply_to_message": {"message_id": reply_to_id}}}


def test_reply_routes_to_thread_agent(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    dispatcher._record_thread(BO, 600, "trader", 31, "bot health")
    res = tg.process_update(_reply_update(700, BO, "and the win rate?", 600))
    assert res["status"] == "dispatched" and res["agent"] == "trader"
    assert calls[0]["agent"] == "trader"
    assert "win rate" in calls[0]["text"]


def test_reply_to_unknown_message_uses_normal_routing(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    res = tg.process_update(_reply_update(701, BO, "research the bond market", 999999))
    assert res["status"] == "dispatched"
    assert calls[0]["agent"] == "researcher"  # normal alias routing


def test_forbidden_follow_up_still_refused(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    dispatcher._record_thread(BO, 601, "trader", 32, "bot health")
    res = tg.process_update(_reply_update(702, BO, "ok now buy 10 NVDA", 601))
    assert res["status"] == "refused"
    assert calls == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_telegram_threads.py -q`
Expected: the 3 new tests FAIL (reply routes to researcher fallback, not trader)

- [ ] **Step 3: Implement the lookup in `process_update`**

In `apps/api/routes/telegram.py`, insert between the voice block (`heard = …`)
and the `# 3. Intent.` comment:

```python
    # 2c. Thread follow-up: replying to a bot report continues that topic with
    # the same agent. Forbidden gate still applies to the follow-up text.
    reply_to = (msg.get("reply_to_message") or {}).get("message_id")
    if reply_to:
        thread = dispatcher.find_thread(chat_id, reply_to)
        if thread:
            from dispatch.intent import detect_forbidden, Intent

            reason = detect_forbidden(text)
            if reason:
                dispatcher.send_telegram_message(
                    chat_id,
                    format_telegram(
                        f"{heard}That maps to a {reason} action - not auto-dispatchable. "
                        f"I only run read-only research and intel from Telegram."
                    ),
                )
                return {"ok": True, "status": "refused", "reason": reason}
            follow_up = f"Follow-up to your earlier report on '{thread.prompt}': {text}"
            job = enqueue_job(follow_up, thread.agent_id, update_id, chat_id)
            if job is None:
                return {"ok": True, "status": "duplicate"}
            dispatcher.send_telegram_message(
                chat_id,
                format_telegram(f"{heard}Following up with {thread.agent_id}."),
            )
            return {"ok": True, "status": "dispatched", "agent": thread.agent_id, "job_id": job.id}
```

(`enqueue_job` stores `agent_id=thread.agent_id`; Task 3 makes the worker
honor it. The agent's tmux session still holds the original conversation, so
the follow-up lands with context.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_threads.py tests/test_telegram_dispatch.py tests/test_telegram_polling.py tests/test_telegram_voice.py -q`
Expected: all pass (threads + no regressions in the security suites)
Run: `.venv/bin/python -m pytest -q` → full suite green (228)

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add -A && git commit -m "phase6(threads): replying to a bot report continues the topic with the same agent (§B)"
```

---

# Feature C — Missions (multi-agent from one prompt)

### Task 6: `mission:` intent alias

**Files:**
- Modify: `apps/api/dispatch/intent.py` (top of `_alias_match`, BEFORE the finance match — "mission: research X" must not be claimed by the researcher alias)
- Test: append to `apps/api/tests/test_mission.py` (new file)

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_mission.py
"""Missions: 'mission: <goal>' fans out to multiple read-only agents via the
CEO (decompose → parallel run → synthesize). Forbidden gate still wins."""
import asyncio
import json

import pytest

from dispatch.intent import resolve_intent


def test_mission_prefix_routes_to_ceo():
    intent = resolve_intent("mission: full read on BTC into CPI")
    assert intent.agent == "ceo"
    assert intent.task_type == "mission"
    assert intent.dispatchable


def test_mission_with_forbidden_action_refused():
    intent = resolve_intent("mission: buy the dip on NVDA")
    assert intent.forbidden is True and intent.dispatchable is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_mission.py -q`
Expected: first test FAILS (routes to researcher fallback, task_type general_question)

- [ ] **Step 3: Add the alias**

In `apps/api/dispatch/intent.py`, at the very top of `_alias_match` (before the
finance worked-example block):

```python
    # Mission: explicit multi-agent orchestration. Checked first so "mission:
    # research X" isn't claimed by a single-agent alias below.
    if re.match(r"^\s*mission\b[:,]?\s+", low):
        return Intent(
            raw_text=text, agent="ceo", task_type="mission",
            confidence=0.95, source="alias",
        )
```

(The forbidden gate runs before `_alias_match` in `resolve_intent`, so test 2
passes with no extra code.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_mission.py tests/test_intent_router.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add -A && git commit -m "phase6(mission): 'mission:' alias routes to ceo/mission (§C)"
```

### Task 7: `dispatch/mission.py` — decompose → fan out → synthesize

**Files:**
- Create: `apps/api/dispatch/mission.py`
- Test: append to `apps/api/tests/test_mission.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to apps/api/tests/test_mission.py
from dispatch import mission


def test_parse_subtasks_valid_caps_and_validates():
    raw = json.dumps([
        {"agent": "researcher", "prompt": "macro read"},
        {"agent": "trader", "prompt": "bot + price structure"},
        {"agent": "nonexistent", "prompt": "dropped"},
        {"agent": "planner", "prompt": "dropped — not a mission agent"},
    ])
    subs = mission._parse_subtasks(raw)
    assert [s["agent"] for s in subs] == ["researcher", "trader"]


def test_parse_subtasks_garbage_is_none():
    assert mission._parse_subtasks("no json") is None
    assert mission._parse_subtasks(json.dumps([{"agent": "x", "prompt": ""}])) is None


def test_parse_subtasks_repairs_pane_wrapped_json():
    raw = json.dumps([{"agent": "researcher", "prompt": "macro read"}], indent=2)
    assert mission._parse_subtasks(raw.replace("macro read", "macro\n  read")) is not None


def test_run_mission_decomposes_fans_out_synthesizes(monkeypatch):
    calls = []
    async def fake_run_agent(agent_id, prompt):
        calls.append(agent_id)
        if agent_id == "ceo" and "Decompose" in prompt:
            return json.dumps([
                {"agent": "researcher", "prompt": "macro"},
                {"agent": "trader", "prompt": "bot state"},
            ])
        if agent_id == "ceo":
            return "# Mission report\n\nSynthesis."
        return f"findings from {agent_id}"
    monkeypatch.setattr(mission, "run_agent", fake_run_agent)
    progress = []
    md = asyncio.run(mission.run_mission("full read into CPI", progress=progress.append))
    assert "Synthesis." in md
    assert calls[0] == "ceo" and calls[-1] == "ceo"
    assert {"researcher", "trader"} <= set(calls)
    assert any("researcher" in p for p in progress)  # progress ping mentions the fan-out


def test_run_mission_decompose_failure_falls_back_to_researcher(monkeypatch):
    calls = []
    async def fake_run_agent(agent_id, prompt):
        calls.append(agent_id)
        if agent_id == "ceo" and "Decompose" in prompt:
            return "sorry, no json today"
        if agent_id == "ceo":
            return "# Mission report\n\nSynthesis."
        return "findings"
    monkeypatch.setattr(mission, "run_agent", fake_run_agent)
    md = asyncio.run(mission.run_mission("whatever"))
    assert "researcher" in calls  # single-subtask fallback
    assert md.strip()


def test_run_mission_synthesis_failure_joins_sections(monkeypatch):
    async def fake_run_agent(agent_id, prompt):
        if agent_id == "ceo" and "Decompose" in prompt:
            return json.dumps([{"agent": "researcher", "prompt": "macro"}])
        if agent_id == "ceo":
            return ""  # synthesis produced nothing
        return "raw findings"
    monkeypatch.setattr(mission, "run_agent", fake_run_agent)
    md = asyncio.run(mission.run_mission("x"))
    assert "raw findings" in md  # deterministic join fallback
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_mission.py -q`
Expected: FAIL — `ImportError: cannot import name 'mission'`

- [ ] **Step 3: Implement the module**

```python
# apps/api/dispatch/mission.py
"""Mission pipeline (§C): one Telegram prompt → CEO decomposes into ≤4
read-only subtasks → agents run in parallel (separate tmux sessions) → CEO
synthesizes one report.

Safety: subtask agents are restricted to MISSION_AGENTS (read-only intel
roster — no planner, no write paths); the forbidden gate already refused
action-shaped missions upstream. Every stage degrades: decompose failure →
single researcher subtask; synthesis failure → deterministic section join.
JSON from a tmux pane needs the newline-collapse repair (pane wrap breaks
string literals — hit live 2026-06-09).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Callable, Optional

MISSION_AGENTS = {"researcher", "trader", "polymarket", "finance", "scout", "inbox", "adset"}
MAX_SUBTASKS = 4
_RESULT_CAP = 4000  # chars of each subtask result fed to synthesis

DECOMPOSE_PROMPT = """Decompose this mission into 2-{max_subtasks} independent READ-ONLY subtasks.
Mission: {mission}

Available agents: {agents}.
Output ONLY a JSON array (no prose, no code fences):
  [{{"agent": "<agent>", "prompt": "<specific subtask>"}}]
Pick only agents that genuinely add signal for THIS mission."""

SYNTH_PROMPT = """Synthesize ONE markdown mission report from your agents' findings.
Mission: {mission}

{sections}

The FIRST line must be a one-sentence plain summary (it becomes the chat reply).
Lead with the answer, reconcile disagreements explicitly, no filler. No emojis."""


async def run_agent(agent_id: str, prompt: str) -> str:
    from agents.runner_v2 import run_agent_task

    result = await run_agent_task(agent_id, prompt)
    return getattr(result, "output", None) or ""


def _parse_subtasks(text: str) -> Optional[list[dict]]:
    if not text:
        return None
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except Exception:
        try:
            raw = json.loads(re.sub(r"\n\s*", " ", m.group(0)))
        except Exception:
            return None
    if not isinstance(raw, list):
        return None
    subs = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        agent = it.get("agent")
        prompt = str(it.get("prompt") or "").strip()
        if agent in MISSION_AGENTS and prompt:
            subs.append({"agent": agent, "prompt": prompt})
    return subs[:MAX_SUBTASKS] or None


async def run_mission(
    mission_text: str, progress: Optional[Callable[[str], None]] = None
) -> str:
    """Returns the final mission report markdown. Never raises on stage
    failures — degrades instead (this feeds a Telegram reply)."""
    agents_list = ", ".join(sorted(MISSION_AGENTS))
    decompose = await run_agent(
        "ceo",
        DECOMPOSE_PROMPT.format(
            max_subtasks=MAX_SUBTASKS, mission=mission_text, agents=agents_list
        ),
    )
    subtasks = _parse_subtasks(decompose) or [
        {"agent": "researcher", "prompt": mission_text}
    ]
    if progress:
        try:
            progress(
                f"Mission: {len(subtasks)} agent(s) dispatched - "
                + ", ".join(s["agent"] for s in subtasks)
            )
        except Exception:  # noqa: BLE001
            pass

    subtask_preamble = (
        "Mission subtask (read-only intel only - never place orders, transfer "
        "funds, send messages, or modify anything): "
    )
    results = await asyncio.gather(
        *(run_agent(s["agent"], subtask_preamble + s["prompt"]) for s in subtasks),
        return_exceptions=True,
    )

    sections = []
    for sub, res in zip(subtasks, results):
        body = res if isinstance(res, str) else f"(failed: {res})"
        body = (body or "(no output)").strip()[:_RESULT_CAP]
        sections.append(f"## {sub['agent']} — {sub['prompt'][:80]}\n\n{body}")

    synthesis = await run_agent(
        "ceo", SYNTH_PROMPT.format(mission=mission_text, sections="\n\n".join(sections))
    )
    if synthesis.strip():
        return synthesis
    # Deterministic fallback: the raw sections are still a useful report.
    return f"# Mission report: {mission_text[:80]}\n\n" + "\n\n".join(sections)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_mission.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add -A && git commit -m "phase6(mission): decompose → parallel fan-out → synthesize pipeline (§C)"
```

### Task 8: Dispatcher branch + progress ping for missions

**Files:**
- Modify: `apps/api/dispatch/dispatcher.py` (`_produce_and_reply`, the `markdown = await run_agent(...)` line)
- Test: append to `apps/api/tests/test_mission.py`

- [ ] **Step 1: Write the failing test**

```python
# append to apps/api/tests/test_mission.py
def test_dispatcher_routes_mission_task_type(monkeypatch, tmp_path):
    from dispatch import dispatcher
    from dispatch.intent import Intent

    async def fake_mission(text, progress=None):
        if progress:
            progress("Mission: 2 agents dispatched")
        return "# Mission report\n\nDone."
    monkeypatch.setattr("dispatch.mission.run_mission", fake_mission)
    monkeypatch.setattr(dispatcher, "render_markdown_pdf", lambda md, p: p)
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda cid, txt: sent.append(txt) or 1)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)

    intent = Intent(raw_text="mission: read the room", agent="ceo",
                    task_type="mission", confidence=0.95, source="alias")
    res = asyncio.run(dispatcher.dispatch_intent(intent, chat_id=6452258223))
    assert any("Mission" in s for s in sent)          # progress ping forwarded
    assert "Done." in res["summary"] or res["summary"]  # report produced
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_mission.py::test_dispatcher_routes_mission_task_type -q`
Expected: FAIL (mission never called; run_agent path used)

- [ ] **Step 3: Branch in `_produce_and_reply`**

Replace the single line `markdown = await run_agent(intent.agent, prompt)` with:

```python
    if intent.task_type == "mission":
        from dispatch.mission import run_mission
        from dispatch.telegram_format import format_telegram

        markdown = await run_mission(
            intent.raw_text,
            progress=lambda m: send_telegram_message(chat_id, format_telegram(m)),
        )
    else:
        markdown = await run_agent(intent.agent, prompt)
```

- [ ] **Step 4: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_mission.py -q` → 9 passed
Run: `.venv/bin/python -m pytest -q` → full suite green (~237)

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add -A && git commit -m "phase6(mission): dispatcher runs mission pipeline for task_type=mission, with progress ping (§C)"
```

### Task 9: BUILD_LOG, deploy, live verify

- [ ] **Step 1: Append the Phase 6 section to `BUILD_LOG.md`** (summarize Tasks 1–8 in the established style: what + why + test counts)

- [ ] **Step 2: Deploy (API-only change)**

```bash
cd ~/borina-mesh && git push origin main
launchctl kickstart -k gui/$(id -u)/com.borina.mesh-api
sleep 8 && curl -s http://localhost:8000/health   # expect {"status":"ok"}
```

- [ ] **Step 3: Live verify, in order**

1. Vault write-back: send any text question to @borinabot (or run one dispatch via
   `curl -s -X POST "http://localhost:8000/daily/generate?use_agent=false"` is NOT a dispatch —
   use Telegram), then check `ls /Users/clawd/obsidian-vault/04-resources/reports/` for the new
   report and the link in today's daily note.
2. Threads: in Telegram, reply to the report message with a follow-up question → expect
   "Following up with <agent>." and a follow-up report from the SAME agent.
3. Mission: send `mission: give me a full read on BTC and rates into tomorrow` → expect
   "Mission: N agents dispatched - …" progress ping, then one synthesized report + PDF
   (takes several minutes; the worker's progress ping covers the wait).

- [ ] **Step 4: Confirm steady-state logs are clean**

```bash
tail -20 ~/borina-mesh/logs/api.log   # no tracebacks, no 409 floods after the restart window
```

---

## Self-Review (done at write time)

- **Coverage:** "saves what it works on" → Tasks 1–2; "reply = follow-up with context" → Tasks 3–5; "send out agents from one prompt" → Tasks 6–8; deploy/verify → Task 9. Standing watches were explicitly deferred by Bo.
- **Types:** `save_dispatch_to_vault(agent, prompt, markdown, day, job_id)` consistent across Tasks 1–2; `_record_thread/find_thread` signatures consistent across Tasks 4–5; `run_mission(text, progress)` consistent across Tasks 7–8. `send_telegram_message` return-type change (None → Optional[int]) is backward-compatible (existing callers ignore the return).
- **Test-count arithmetic** is approximate (suite at 216 at plan time); the binding requirement is "full suite green" at each step.
- **Risk noted:** missions hold a worker slot for several minutes (cap 3 concurrent telegram jobs) — acceptable for a single user; revisit if missions become frequent.
