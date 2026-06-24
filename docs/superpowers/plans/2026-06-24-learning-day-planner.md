# Learning Day-Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the `planner` agent a durable, learned model of Bo (built nightly from his daily notes, Telegram, and task/calendar activity) and have it produce a layered morning plan — narrative brief → prioritized threads → time-blocked agenda — whose agenda blocks are approvable calendar items.

**Architecture:** Four additive pieces, none of which touch the existing approve/calendar safety path. (1) A `ConversationLog` table + `conversation_log.py` capture Telegram messages fail-open. (2) `operator_brain.py` runs in the existing `eod` operator phase and rewrites a bounded `operator-profile.md` in the vault from the day's signals. (3) The `planner` agent prompt is injected with that profile and returns a JSON object `{brief, threads, items}`; `items` keep the exact current shape so `PlanItem` staging + approve-tap is untouched, and calendar `items` ARE the agenda. (4) The morning operator phase sends the rendered narrative above the existing approval Card.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, pytest (+ pytest-asyncio for `@pytest.mark.asyncio`), the `claude` CLI via `agents.runner_v2.run_agent_task` (no API key).

## Global Constraints

- **Safety invariant (never weaken):** NO autonomous calendar or task writes. The only writer stays `planner.approve_item`, reached by Bo's tap. The learner and planner are text-only — they stage `PlanItem` rows and rewrite a vault file, nothing more. The existing regression tests `test_no_autonomous_write_regression` and `test_generate_plan_writes_no_calendar` MUST still pass.
- **Module name is `operator_brain.py`, NOT `operator.py`** — `operator` shadows the Python stdlib module (the trap that forced `daily_operator.py`).
- **All conversation logging is fail-open** — any logging error is swallowed and never propagates into the dispatch path.
- **New tables need no manual migration** — `db.init_db()` (called at `main.py:44` and `conftest.py:48`) runs `SQLModel.metadata.create_all`, which creates any newly-defined model table. Only ensure `models` is imported before `init_db` (conftest already does this).
- **`Task` has no completion timestamp** (only `done: bool` + `created_at`). So "tasks completed today" is not queryable by date; the learner's task signal is **tasks created today** (`created_at.date() == day`) + **currently-open task titles**. This is the agreed implementation of the spec's task/calendar signal.
- **Run tests from `apps/api`:** `cd ~/borina-mesh/apps/api && python -m pytest`. Single test: `python -m pytest tests/test_x.py::test_y -v`.
- Match existing style: lazy imports inside functions for heavy/optional deps, `# noqa: BLE001` on best-effort broad excepts, `from __future__ import annotations` at top of new modules.

## File Structure

- `apps/api/models.py` — **modify**: add `ConversationLog` table.
- `apps/api/conversation_log.py` — **create**: `log_message`, `recent_for_day`, `trim_older_than`.
- `apps/api/routes/telegram.py` — **modify**: log inbound user text (post allow-list) in `process_update`.
- `apps/api/dispatch/dispatcher.py` — **modify**: log Borina replies in `send_telegram_message`.
- `apps/api/operator_brain.py` — **create**: profile read/write/validate helpers + the nightly `update_profile` learner.
- `apps/api/daily_operator.py` — **modify**: call the learner in `eod`; add a profile line to the recap Card; send the layered narrative in `morning`.
- `apps/api/planner.py` — **modify**: `_validate_items` refactor, `_parse_agent_plan`, profile injection, layered prompt, `_run_agent_plan`, layered `generate_plan`/`_render_plan_md`/`generate_plan_with_agent`, `plan_narrative_text`.
- `apps/api/tests/test_conversation_log.py` — **create**.
- `apps/api/tests/test_operator_brain.py` — **create**.
- `apps/api/tests/test_planner_layered.py` — **create**.
- `apps/api/tests/test_daily_operator.py` — **modify**: eod-learner + morning-narrative tests.
- `apps/api/tests/test_telegram_dispatch.py` — **modify**: inbound-logging tests.
- `apps/api/tests/test_live_llm.py` — **modify** (Task 7): delete the 6 obsolete array-path planner tests + `AGENT_PROPOSALS` constant once `_parse_agent_proposals`/`_agent_proposals_file` are removed; the two `_agent_context` tests there stay (still pass — `obsidian` key is unchanged).

---

### Task 1: `ConversationLog` table + `conversation_log` module

**Files:**
- Modify: `apps/api/models.py` (add table after `TelegramThread`, ~line 135)
- Create: `apps/api/conversation_log.py`
- Test: `apps/api/tests/test_conversation_log.py`

**Interfaces:**
- Produces: `ConversationLog(id, chat_id:int, role:str, text:str, created_at:datetime)`; `log_message(chat_id:int, role:str, text:str) -> None`; `recent_for_day(day:str) -> list[dict]` (each `{"role","text","at"}`, oldest-first); `trim_older_than(days:int=30) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_conversation_log.py`:

```python
"""Conversation log — the Telegram signal for the nightly learner. Fail-open."""
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

import conversation_log as cl
from db import session_scope
from models import ConversationLog


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for r in s.exec(select(ConversationLog)).all():
            s.delete(r)
        s.commit()
    yield


def test_log_and_recent_for_today():
    cl.log_message(42, "user", "ship the planner")
    rows = cl.recent_for_day(date.today().isoformat())
    assert len(rows) == 1
    assert rows[0]["role"] == "user" and rows[0]["text"] == "ship the planner"


def test_recent_excludes_other_days():
    cl.log_message(42, "user", "today only")
    assert cl.recent_for_day("1999-01-01") == []


def test_empty_text_is_ignored():
    cl.log_message(42, "user", "   ")
    assert cl.recent_for_day(date.today().isoformat()) == []


def test_trim_removes_old_keeps_recent():
    cl.log_message(42, "user", "fresh")
    with session_scope() as s:  # backdate one row 40 days
        old = ConversationLog(chat_id=42, role="user", text="stale")
        old.created_at = datetime.utcnow() - timedelta(days=40)
        s.add(old)
        s.commit()
    deleted = cl.trim_older_than(30)
    assert deleted == 1
    texts = [r["text"] for r in cl.recent_for_day(date.today().isoformat())]
    assert "fresh" in texts and "stale" not in texts


def test_logging_failure_is_swallowed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(cl, "session_scope", boom)
    cl.log_message(42, "user", "should not raise")  # must not raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_conversation_log.py -v`
Expected: FAIL — `ImportError: cannot import name 'ConversationLog'` / `No module named 'conversation_log'`.

- [ ] **Step 3: Add the `ConversationLog` model**

In `apps/api/models.py`, immediately after the `TelegramThread` class, add:

```python
class ConversationLog(SQLModel, table=True):
    """Durable log of Telegram messages (both directions) so the nightly learner
    (operator_brain) can mine what Bo actually talked about. Written fail-open —
    a logging failure never blocks dispatch. role: "user" | "borina"."""
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    role: str
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
```

(`Optional`, `Field`, `datetime`, `SQLModel` are already imported in `models.py`.)

- [ ] **Step 4: Create `conversation_log.py`**

Create `apps/api/conversation_log.py`:

```python
"""Telegram conversation log — the Telegram signal for the nightly learner.

Every inbound user message (post allow-list) and Borina reply is appended here
fail-open: logging never raises into the dispatch path. The learner reads one
day's window; a nightly trim keeps the table bounded.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from db import session_scope
from models import ConversationLog


def log_message(chat_id: int, role: str, text: str) -> None:
    """Append one message. Swallows every error — must never break dispatch."""
    text = (text or "").strip()
    if not text:
        return
    try:
        with session_scope() as s:
            s.add(ConversationLog(chat_id=chat_id, role=role, text=text[:4000]))
            s.commit()
    except Exception:  # noqa: BLE001 — logging is best-effort
        pass


def recent_for_day(day: str) -> list[dict]:
    """Messages whose created_at falls on `day` (YYYY-MM-DD), oldest-first.
    Returns [] on any error."""
    try:
        with session_scope() as s:
            rows = s.exec(
                select(ConversationLog).order_by(ConversationLog.created_at)
            ).all()
        return [
            {"role": r.role, "text": r.text, "at": r.created_at.isoformat()}
            for r in rows
            if r.created_at.date().isoformat() == day
        ]
    except Exception:  # noqa: BLE001
        return []


def trim_older_than(days: int = 30) -> int:
    """Delete rows older than `days`. Returns count deleted (0 on error)."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = 0
        with session_scope() as s:
            for r in s.exec(
                select(ConversationLog).where(ConversationLog.created_at < cutoff)
            ).all():
                s.delete(r)
                deleted += 1
            s.commit()
        return deleted
    except Exception:  # noqa: BLE001
        return 0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_conversation_log.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
cd ~/borina-mesh && git add apps/api/models.py apps/api/conversation_log.py apps/api/tests/test_conversation_log.py
git commit -m "feat(planner): ConversationLog table + fail-open conversation_log module"
```

---

### Task 2: Wire conversation logging into Telegram (inbound + outbound)

**Files:**
- Modify: `apps/api/routes/telegram.py` (`process_update`, after the voice block, before the `# 2b1. Builder` comment — around line 487)
- Modify: `apps/api/dispatch/dispatcher.py` (`send_telegram_message`, after the token guard ~line 55)
- Test: `apps/api/tests/test_telegram_dispatch.py` (append)

**Interfaces:**
- Consumes: `conversation_log.log_message` (Task 1).
- Produces: inbound user messages logged with `role="user"` only for allow-listed chats; Borina replies logged with `role="borina"` when a bot token is configured.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_telegram_dispatch.py`:

```python
def test_inbound_logged_for_allowed_sender(monkeypatch):
    from datetime import date
    from sqlmodel import select
    import conversation_log as cl
    from db import session_scope
    from models import ConversationLog
    import routes.telegram as tg
    from dispatch import dispatcher

    with session_scope() as s:  # clean slate
        for r in s.exec(select(ConversationLog)).all():
            s.delete(r)
        s.commit()
    BO = 6452258223
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)

    tg.process_update({"update_id": 1, "message": {"chat": {"id": BO},
                                                   "text": "/help", "message_id": 9}})
    rows = cl.recent_for_day(date.today().isoformat())
    assert any(r["role"] == "user" and r["text"] == "/help" for r in rows)


def test_inbound_not_logged_for_disallowed_sender(monkeypatch):
    from datetime import date
    from sqlmodel import select
    import conversation_log as cl
    from db import session_scope
    from models import ConversationLog
    import routes.telegram as tg

    with session_scope() as s:
        for r in s.exec(select(ConversationLog)).all():
            s.delete(r)
        s.commit()
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "6452258223")
    tg.process_update({"update_id": 2, "message": {"chat": {"id": 999},
                                                   "text": "intruder", "message_id": 10}})
    assert cl.recent_for_day(date.today().isoformat()) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_telegram_dispatch.py::test_inbound_logged_for_allowed_sender tests/test_telegram_dispatch.py::test_inbound_not_logged_for_disallowed_sender -v`
Expected: FAIL — the allowed-sender test finds no `user` row.

- [ ] **Step 3: Log inbound user text in `process_update`**

In `apps/api/routes/telegram.py`, find the end of the voice block (the lines setting `text = transcript` / `heard = ...` then `return ... "transcribe_failed"`). Immediately AFTER that whole `media`/voice block and BEFORE the `# 2b1. Builder:` comment (~line 484), insert:

```python
    # Log the inbound message (post allow-list) for the nightly learner. Fail-open:
    # done here so voice transcripts are captured too, and only for allowed senders.
    if text:
        try:
            from conversation_log import log_message
            log_message(chat_id, "user", text)
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 4: Log Borina replies in `send_telegram_message`**

In `apps/api/dispatch/dispatcher.py`, inside `send_telegram_message`, right after the token guard:

```python
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
```

insert:

```python
    try:  # mirror Borina's side into the learner's signal (fail-open)
        from conversation_log import log_message
        log_message(chat_id, "borina", text)
    except Exception:  # noqa: BLE001
        pass
```

(Placed after the token guard so token-less test runs don't log, keeping existing tests unaffected.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_telegram_dispatch.py -v`
Expected: PASS (including the two new tests; existing dispatch tests still green).

- [ ] **Step 6: Commit**

```bash
cd ~/borina-mesh && git add apps/api/routes/telegram.py apps/api/dispatch/dispatcher.py apps/api/tests/test_telegram_dispatch.py
git commit -m "feat(planner): log Telegram messages (inbound post allow-list + Borina replies)"
```

---

### Task 3: `operator_brain` profile read/write/validate helpers

**Files:**
- Create: `apps/api/operator_brain.py`
- Test: `apps/api/tests/test_operator_brain.py`

**Interfaces:**
- Produces: `EMPTY_PROFILE:str`; `read_profile() -> str`; `write_profile(text:str) -> Optional[Path]` (writes only if valid + vault present); `_is_valid_profile(text:str) -> bool`; `_count_active_threads(text:str) -> int`; `_profile_path() -> Optional[Path]`.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_operator_brain.py`:

```python
"""Operator brain — profile read/write/validate + nightly learner. Text-only."""
import pytest

import operator_brain as ob

VALID = """# Operator profile — Bo
_Updated: 2026-06-24 (eod)_

## Active threads
- borina-mesh planner: shipping the learner — last touched 2026-06-24
- store launch: PDP copy — last touched 2026-06-23

## Recurring priorities
- mesh health

## Working rhythms
- deep work mornings

## Preferences
- mornings protected

## Recently completed / closed
- (none)
"""


def test_read_profile_empty_without_vault(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    assert ob.read_profile() == ob.EMPTY_PROFILE


def test_write_rejects_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    assert ob.write_profile("garbage, no sections") is None
    assert ob.read_profile() == ob.EMPTY_PROFILE  # nothing written


def test_write_then_read_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    p = ob.write_profile(VALID)
    assert p is not None and p.exists()
    assert ob.read_profile() == VALID


def test_count_active_threads():
    assert ob._count_active_threads(VALID) == 2
    assert ob._count_active_threads(ob.EMPTY_PROFILE) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_operator_brain.py -v`
Expected: FAIL — `No module named 'operator_brain'`.

- [ ] **Step 3: Create `operator_brain.py` (helpers only)**

Create `apps/api/operator_brain.py`:

```python
"""Nightly learner (L2.5) — a durable model of Bo built from the day's signals.

Runs in the eod operator phase. READS today's daily note, the Telegram
conversation log, and tasks/calendar; has the `planner` agent rewrite a bounded
`operator-profile.md` in the vault. Text-only — stages nothing, writes only the
profile file. The mesh's approve-only calendar invariant is untouched.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

_PROFILE_FILE = ("04-resources", "brain", "operator-profile.md")
_SECTIONS = (
    "## Active threads",
    "## Recurring priorities",
    "## Working rhythms",
    "## Preferences",
    "## Recently completed / closed",
)

EMPTY_PROFILE = """# Operator profile — Bo
_Updated: never_

## Active threads

## Recurring priorities

## Working rhythms

## Preferences

## Recently completed / closed
"""


def _vault() -> Optional[Path]:
    root = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not root:
        return None
    p = Path(root)
    return p if p.is_dir() else None


def _profile_path() -> Optional[Path]:
    v = _vault()
    return v.joinpath(*_PROFILE_FILE) if v else None


def read_profile() -> str:
    """Current profile text, or EMPTY_PROFILE (no vault / not yet written)."""
    p = _profile_path()
    if p and p.exists():
        try:
            return p.read_text()
        except OSError:
            return EMPTY_PROFILE
    return EMPTY_PROFILE


def _is_valid_profile(text: str) -> bool:
    """Non-trivial and carries every fixed section — guards against overwriting
    good state with a truncated/garbage agent reply."""
    if not text or len(text.strip()) < 40:
        return False
    return all(sec in text for sec in _SECTIONS)


def write_profile(text: str) -> Optional[Path]:
    """Write the profile back. Returns the path, or None (no vault / invalid)."""
    p = _profile_path()
    if not p or not _is_valid_profile(text):
        return None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p
    except OSError:
        return None


def _count_active_threads(text: str) -> int:
    """Number of bullet lines under '## Active threads'."""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "## Active threads")
    except StopIteration:
        return 0
    n = 0
    for l in lines[start + 1:]:
        if l.startswith("## "):
            break
        if l.strip().startswith("- "):
            n += 1
    return n
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_operator_brain.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add apps/api/operator_brain.py apps/api/tests/test_operator_brain.py
git commit -m "feat(planner): operator_brain profile read/write/validate helpers"
```

---

### Task 4: The nightly learner — `update_profile`

**Files:**
- Modify: `apps/api/operator_brain.py` (append signals + prompt + `update_profile`)
- Test: `apps/api/tests/test_operator_brain.py` (append)

**Interfaces:**
- Consumes: `read_profile`, `write_profile`, `_is_valid_profile`, `_count_active_threads` (Task 3); `conversation_log.recent_for_day`, `conversation_log.trim_older_than` (Task 1); `agents.runner_v2.run_agent_task`.
- Produces: `async update_profile(day:Optional[str]=None) -> dict` (`{"day","written":bool,"active_threads":int,"trimmed":int}`); `_gather_signals(day:str) -> dict`; `async _call_agent(prompt:str) -> str` (monkeypatch target in tests).

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_operator_brain.py`:

```python
@pytest.mark.asyncio
async def test_update_profile_writes_valid_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))

    async def fake_agent(prompt):
        return VALID
    monkeypatch.setattr(ob, "_call_agent", fake_agent)

    res = await ob.update_profile("2026-06-24")
    assert res["written"] is True
    assert res["active_threads"] == 2
    assert ob.read_profile() == VALID


@pytest.mark.asyncio
async def test_update_profile_keeps_old_on_garbage(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    ob.write_profile(VALID)  # seed a good profile

    async def fake_agent(prompt):
        return "sorry, I could not produce a profile"
    monkeypatch.setattr(ob, "_call_agent", fake_agent)

    res = await ob.update_profile("2026-06-24")
    assert res["written"] is False
    assert ob.read_profile() == VALID  # unchanged


@pytest.mark.asyncio
async def test_update_profile_trims_old_conversation(monkeypatch, tmp_path):
    from datetime import datetime, timedelta
    from db import session_scope
    from models import ConversationLog
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    with session_scope() as s:
        old = ConversationLog(chat_id=1, role="user", text="ancient")
        old.created_at = datetime.utcnow() - timedelta(days=40)
        s.add(old)
        s.commit()

    async def fake_agent(prompt):
        return VALID
    monkeypatch.setattr(ob, "_call_agent", fake_agent)

    res = await ob.update_profile("2026-06-24")
    assert res["trimmed"] >= 1


def test_gather_signals_includes_today_task(monkeypatch, tmp_path):
    from db import session_scope
    from models import Task
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    from datetime import date
    with session_scope() as s:
        s.add(Task(title="signal-task", tag="borina"))
        s.commit()
    sig = ob._gather_signals(date.today().isoformat())
    assert "signal-task" in sig["tasks"]
    assert set(["daily_note", "conversation", "tasks", "calendar"]).issubset(sig)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_operator_brain.py -k "update_profile or gather_signals" -v`
Expected: FAIL — `AttributeError: module 'operator_brain' has no attribute 'update_profile'`.

- [ ] **Step 3: Append the learner to `operator_brain.py`**

Append to `apps/api/operator_brain.py`:

```python
# ── signals + nightly learner ────────────────────────────────────────────────

def _today_daily_note(day: str) -> str:
    v = _vault()
    if not v:
        return ""
    note = v / "01-daily" / f"{day}.md"
    try:
        return note.read_text()[:4000] if note.exists() else ""
    except OSError:
        return ""


def _task_signal(day: str) -> dict:
    from sqlmodel import select
    from db import session_scope
    from models import Task
    with session_scope() as s:
        tasks = s.exec(select(Task)).all()
        created_today = [t.title for t in tasks if t.created_at.date().isoformat() == day]
        open_titles = [t.title for t in tasks if not t.done][:20]
    return {"created_today": created_today, "open": open_titles}


def _calendar_signal(day: str) -> list[dict]:
    from integrations import google_calendar
    cal = google_calendar.list_events(f"{day}T00:00:00Z", f"{day}T23:59:59Z")
    events = cal.data if cal.connected else []
    return [{"title": e.get("title"), "start": e.get("start")} for e in events]


def _gather_signals(day: str) -> dict:
    from conversation_log import recent_for_day
    convo = recent_for_day(day)
    cal = _calendar_signal(day)  # one calendar call, not two
    return {
        "daily_note": _today_daily_note(day) or "(none)",
        "conversation": json.dumps(convo)[:4000] if convo else "(none)",
        "tasks": json.dumps(_task_signal(day)),
        "calendar": json.dumps(cal) if cal else "(none)",
    }


LEARNER_PROMPT = """<task name="update_operator_profile">
You maintain a durable PROFILE of Bo — a compressed model of what he is working
on and how he likes his days. Today is {day}. Update the profile from today's
signals. Output ONLY the full updated profile markdown (no prose, no code fences).

Rules:
- Keep the EXACT section headers, in this order: "# Operator profile — Bo",
  "## Active threads", "## Recurring priorities", "## Working rhythms",
  "## Preferences", "## Recently completed / closed".
- Set the line under the title to "_Updated: {day} (eod)_".
- Each section is a bounded bullet list (max 10 bullets). Prune the oldest/stale.
- "## Active threads" bullets END with " — last touched <YYYY-MM-DD>". Refresh that
  date for any thread today's signals touched. Move a thread untouched for more
  than 7 days into "## Recently completed / closed" as a one-line note.
- NO invention. Only assert what the signals or the prior profile support. Prefer
  FRESH items from today; do not re-add finished work.

Prior profile:
---
{profile}
---

Today's signals:
- Daily note: {daily_note}
- Telegram conversation (role/text JSON): {conversation}
- Tasks (created_today / open JSON): {tasks}
- Calendar events JSON: {calendar}
</task>"""


async def _call_agent(prompt: str) -> str:
    """Run the learner prompt through the planner agent (chief-of-staff persona).
    Returns the agent's text output ("" on failure)."""
    from agents.runner_v2 import run_agent_task
    result = await run_agent_task("planner", prompt)
    return getattr(result, "output", None) or ""


async def update_profile(day: Optional[str] = None) -> dict:
    """The nightly learner. Reads the day's signals + current profile, has the
    agent emit an updated profile, validates it, and writes it back — keeping the
    old profile on ANY failure. Then trims the conversation log. Text-only."""
    day = day or date.today().isoformat()
    current = read_profile()
    try:
        prompt = LEARNER_PROMPT.format(profile=current, **_gather_signals(day))
        candidate = await _call_agent(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[operator_brain] learner failed: {exc}")
        candidate = ""

    written = bool(_is_valid_profile(candidate) and write_profile(candidate))

    from conversation_log import trim_older_than
    trimmed = trim_older_than(30)

    return {
        "day": day,
        "written": written,
        "active_threads": _count_active_threads(read_profile()),
        "trimmed": trimmed,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_operator_brain.py -v`
Expected: PASS (8 passed total in the file).

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add apps/api/operator_brain.py apps/api/tests/test_operator_brain.py
git commit -m "feat(planner): nightly learner update_profile (signals + validate-or-keep + trim)"
```

---

### Task 5: Hook the learner into the `eod` phase

**Files:**
- Modify: `apps/api/daily_operator.py` (`run_phase`, the `elif phase == "eod":` branch, lines 93-105)
- Test: `apps/api/tests/test_daily_operator.py` (append)

**Interfaces:**
- Consumes: `operator_brain.update_profile` (Task 4).
- Produces: the eod recap Card gains a profile line; a learner error degrades to a "skipped" line without breaking the recap.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_daily_operator.py`:

```python
@pytest.mark.asyncio
async def test_eod_phase_updates_profile(monkeypatch):
    import daily_operator as op
    import planner
    import operator_brain
    monkeypatch.setattr(op, "_chat_id", lambda: None)
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {"items": [
        {"status": "approved"}, {"status": "proposed"}]})

    async def fake_update(day=None):
        return {"written": True, "active_threads": 3, "trimmed": 0}
    monkeypatch.setattr(operator_brain, "update_profile", fake_update)

    card = await op.run_phase("eod", day="2026-06-24", send=False)
    assert "EOD recap" in card.headline
    assert any("Profile updated — 3 active thread" in l for l in card.lines)


@pytest.mark.asyncio
async def test_eod_phase_survives_learner_error(monkeypatch):
    import daily_operator as op
    import planner
    import operator_brain
    monkeypatch.setattr(op, "_chat_id", lambda: None)
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {"items": []})

    async def boom(day=None):
        raise RuntimeError("agent down")
    monkeypatch.setattr(operator_brain, "update_profile", boom)

    card = await op.run_phase("eod", day="2026-06-24", send=False)
    assert "EOD recap" in card.headline  # recap still produced
    assert any("skipped" in l.lower() for l in card.lines)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_daily_operator.py -k eod -v`
Expected: FAIL — no "Profile updated" line in the recap card.

- [ ] **Step 3: Update the `eod` branch**

In `apps/api/daily_operator.py`, replace the entire `elif phase == "eod":` block (lines 93-105) with:

```python
    elif phase == "eod":
        plan = get_plan(day)
        items = plan.get("items", [])
        approved = sum(1 for i in items if i.get("status") == "approved")
        rejected = sum(1 for i in items if i.get("status") == "rejected")
        pending = sum(1 for i in items if i.get("status") == "proposed")
        # Nightly learner: refresh Bo's durable profile from today's signals.
        # Best-effort — a learner failure must never break the recap.
        learn_line = "Profile unchanged."
        try:
            from operator_brain import update_profile
            res = await update_profile(day)
            if res.get("written"):
                learn_line = f"Profile updated — {res.get('active_threads', 0)} active thread(s)."
        except Exception as e:  # noqa: BLE001
            learn_line = "Profile update skipped (learner error)."
            print(f"[operator] eod learner error: {e}")
        card = Card(
            headline=f"EOD recap — {day}",
            lines=[
                f"approved {approved} · skipped {rejected} · still pending {pending}",
                learn_line,
                "Tomorrow's plan stages in the morning.",
            ],
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_daily_operator.py -k eod -v`
Expected: PASS (both new eod tests + the existing `test_eod_phase_recaps`).

- [ ] **Step 5: Commit**

```bash
cd ~/borina-mesh && git add apps/api/daily_operator.py apps/api/tests/test_daily_operator.py
git commit -m "feat(planner): run nightly learner in eod phase + profile recap line"
```

---

### Task 6: Planner — layered parsing + profile context (additive only)

> **Why additive:** the old array path (`PLANNER_TASK_PROMPT`, `_run_agent_proposals`, `_parse_agent_proposals`, `_agent_proposals_file`) is still called by `generate_plan_with_agent` AND still tested by `test_live_llm.py`. Removing it here would leave the suite red until Task 7. So Task 6 only ADDS the new layered functions alongside the old ones (suite stays green); Task 7 performs the atomic swap + removes the old symbols + migrates `test_live_llm.py`.

**Files:**
- Modify: `apps/api/planner.py` (INSERT new functions after `_parse_agent_proposals`; add a `"profile"` key to `_agent_context`. Remove nothing.)
- Test: `apps/api/tests/test_planner_layered.py` (create)

**Interfaces:**
- Consumes: `operator_brain.read_profile` (Task 3); existing `_agent_context`, and the existing `_call_agent` at planner.py:151 (reused, NOT redefined).
- Produces: `_validate_items(raw:list) -> list[dict]`; `_parse_agent_plan(text:str) -> Optional[dict]` (`{"brief":str,"threads":list[dict],"items":list[dict]}` or None); `_agent_plan_file(day:str) -> Path`; `async _run_agent_plan(day:str) -> Optional[dict]`; `_safe_profile() -> str`; `PLANNER_PLAN_PROMPT`. `_agent_context(day)` gains a `"profile"` key.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_planner_layered.py`:

```python
"""Layered planner output — brief + threads + agenda; parse + fallback + safety."""
import json

import pytest
from sqlmodel import select

from db import session_scope
from models import PlanItem, Task
import planner


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for it in s.exec(select(PlanItem)).all():
            s.delete(it)
        for t in s.exec(select(Task)).all():
            s.delete(t)
        s.commit()
    yield


PLAN_OBJ = {
    "brief": "Today is about shipping the planner learner.",
    "threads": [{"name": "planner", "today": "wire the eod learner", "why": "unblocks the feature"}],
    "items": [
        {"kind": "calendar", "title": "Deep work: planner",
         "rationale": "protected block",
         "payload": {"summary": "Deep work", "start": "2026-06-24T09:00:00",
                     "end": "2026-06-24T11:00:00"}},
        {"kind": "task", "title": "Review the spec",
         "rationale": "fresh", "payload": {"title": "Review the spec", "tag": "borina",
                                           "priority": "high"}},
    ],
}


def test_parse_agent_plan_extracts_layers():
    parsed = planner._parse_agent_plan(json.dumps(PLAN_OBJ))
    assert parsed is not None
    assert parsed["brief"].startswith("Today is about")
    assert parsed["threads"][0]["name"] == "planner"
    assert len(parsed["items"]) == 2


def test_parse_agent_plan_none_without_valid_items():
    bad = {"brief": "x", "threads": [], "items": [{"kind": "nope", "title": ""}]}
    assert planner._parse_agent_plan(json.dumps(bad)) is None


def test_parse_agent_plan_none_on_nonjson():
    assert planner._parse_agent_plan("I cannot help with that") is None


def test_agent_context_includes_profile(monkeypatch):
    monkeypatch.setattr(planner, "_safe_profile", lambda: "PROFILE-MARKER")
    ctx = planner._agent_context("2026-06-24")
    assert ctx["profile"] == "PROFILE-MARKER"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_planner_layered.py -v`
Expected: FAIL — `AttributeError: module 'planner' has no attribute '_parse_agent_plan'`.

- [ ] **Step 3: ADD the layered agent-path functions to `planner.py` (additive — removes nothing)**

In `apps/api/planner.py`, INSERT the following block immediately AFTER the existing `_parse_agent_proposals` function (after line ~205, before `_recent_daily_notes`). The old array-path functions stay in place and keep working until Task 7 swaps them out, so the suite stays green at this commit. **Reuse the existing `_call_agent` at line ~151 — do NOT redefine it** (the block below intentionally omits `_call_agent`).

```python
# ── live agent path: layered plan ────────────────────────────────────────────
# The planner agent produces TEXT only (a JSON object) staged as PlanItem rows —
# the no-autonomous-write rule is untouched: the only write path remains
# approve_item, invoked by Bo. The agent returns {brief, threads, items}; the
# calendar `items` ARE Bo's time-blocked agenda.

PLANNER_PLAN_PROMPT = """<task name="daily_plan">
You are Bo's chief-of-staff planner. Draft today's ({day}) plan as STAGED PROPOSALS.
You never write to the calendar or task list — you only propose; Bo approves each item.

Bo's durable profile (what he's working on + how he likes his days):
{profile}

Today's context:
- Calendar events: {events}
- Open tasks: {tasks}
- Brief TL;DR: {tldr}
- Brief focus suggestions: {tasks_focus}
- Recent Obsidian daily notes (prefer FRESH items; SKIP long-running recurring ones): {obsidian}

Produce a LAYERED plan. Output ONLY a JSON object (no prose, no code fences):
{{
  "brief": "<2-4 sentence narrative: where Bo is, what today is for>",
  "threads": [{{"name": "...", "today": "<concrete next action today>", "why": "..."}}],
  "items": [ ... ]
}}
Each element of "items":
  {{"kind": "task" | "calendar", "title": "...", "rationale": "...", "payload": {{...}}}}
- kind=calendar payload: {{"summary": "...", "start": "ISO-8601", "end": "ISO-8601"}}
- kind=task payload: {{"title": "...", "tag": "work|personal|borina", "priority": "high|medium|low"}}

The kind=calendar items ARE Bo's time-blocked agenda: lay out the working day as
calendar blocks — a 15-min prep buffer before each real meeting, protected
deep-work block(s), and a timed slot for each top task — with real start/end times
that don't overlap existing events. At most 10 items total. Ground everything in
the profile + context above; no generic filler.

ALSO save this exact JSON object to plan/{day}.json under your working directory
(create the folder if needed) — that file is the canonical handoff.
</task>"""


def _safe_profile() -> str:
    """Bo's durable profile for the prompt; never raises (empty/no-vault → note)."""
    try:
        from operator_brain import read_profile
        return read_profile()[:3000]
    except Exception:  # noqa: BLE001
        return "(no profile yet)"


def _agent_plan_file(day: str) -> Path:
    """Where the planner agent saves its JSON plan object inside its workdir."""
    from agents.runner_v2 import AGENT_REGISTRY, _workdir_root

    entry = AGENT_REGISTRY.get("planner", {})
    workdir = Path(entry.get("workdir") or (_workdir_root() / "planner"))
    return workdir / "plan" / f"{day}.json"


def _validate_items(raw_items) -> list[dict]:
    """Validate/normalize the proposal items. Drops invalid; caps at 8."""
    valid: list[dict] = []
    for it in (raw_items or [])[:12]:
        if not isinstance(it, dict):
            continue
        kind = it.get("kind")
        title = str(it.get("title") or "").strip()[:80]
        if kind not in ("task", "calendar") or not title:
            continue
        payload = it.get("payload") if isinstance(it.get("payload"), dict) else {}
        if kind == "calendar":
            if not all(
                isinstance(payload.get(k), str) and payload.get(k)
                for k in ("summary", "start", "end")
            ):
                continue
        else:
            payload = {
                "title": str(payload.get("title") or title)[:80],
                "tag": payload.get("tag", "borina"),
                "priority": payload.get("priority", "medium"),
            }
        valid.append({
            "kind": kind,
            "title": title,
            "rationale": str(it.get("rationale") or "")[:200],
            "payload": payload,
        })
    return valid[:8]


def _parse_agent_plan(text: str) -> Optional[dict]:
    """Parse the agent's {brief, threads, items} object. Returns None unless at
    least one valid item survives (so callers fall back to heuristics)."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    blob = m.group(0)
    try:
        raw = json.loads(blob)
    except Exception:
        # tmux pane wrap leaves raw newlines inside JSON string literals;
        # collapsing inter-token whitespace repairs the wrapped strings.
        try:
            raw = json.loads(re.sub(r"\n\s*", " ", blob))
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    items = _validate_items(raw.get("items") if isinstance(raw.get("items"), list) else [])
    if not items:
        return None
    threads: list[dict] = []
    for t in (raw.get("threads") or [])[:8]:
        if isinstance(t, dict) and (t.get("name") or t.get("today")):
            threads.append({
                "name": str(t.get("name") or "")[:80],
                "today": str(t.get("today") or "")[:160],
                "why": str(t.get("why") or "")[:160],
            })
    return {"brief": str(raw.get("brief") or "")[:600], "threads": threads, "items": items}


async def _run_agent_plan(day: str) -> Optional[dict]:
    try:
        prompt = PLANNER_PLAN_PROMPT.format(**_agent_context(day))
        output = await _call_agent(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[planner] agent path failed, using heuristics: {exc}")
        return None
    # Preferred handoff: the file the agent wrote; pane capture as fallback.
    try:
        f = _agent_plan_file(day)
        if f.exists():
            parsed = _parse_agent_plan(f.read_text())
            if parsed:
                return parsed
    except Exception as exc:  # noqa: BLE001
        print(f"[planner] workdir plan unreadable: {exc}")
    return _parse_agent_plan(output)
```

- [ ] **Step 4: Inject the profile into `_agent_context`**

In `apps/api/planner.py`, in `_agent_context` (the returned dict, ~line 236-247), add one key. Change the closing of the returned dict so it includes:

```python
        "obsidian": _recent_daily_notes() or "no vault notes",
        "profile": _safe_profile(),
    }
```

- [ ] **Step 5: Run the new tests AND confirm the old suites are still green (additive change)**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_planner_layered.py tests/test_live_llm.py tests/test_planner.py -v`
Expected: the 4 new layered-parse tests PASS, and **every existing `test_live_llm.py` / `test_planner.py` test still PASSES** — Task 6 removed nothing, so the old array path is untouched. If any old test fails, you accidentally removed/renamed an old symbol; revert that and keep Task 6 additive.

- [ ] **Step 6: Commit**

```bash
cd ~/borina-mesh && git add apps/api/planner.py apps/api/tests/test_planner_layered.py
git commit -m "feat(planner): add layered plan parsing (brief/threads/items) + profile context"
```

---

### Task 7: Planner — layered generate/render + atomic swap to the new path

> **This is the atomic swap.** Steps 3-7 must land in ONE commit: rewiring `generate_plan_with_agent` to `_run_agent_plan` and deleting the old array-path symbols leaves the suite red in between, so do not run/commit partway. After this task the old path is gone and the new layered path is live.

**Files:**
- Modify: `apps/api/planner.py` (`_render_plan_md`, `generate_plan`, `generate_plan_with_agent`; then DELETE `PLANNER_TASK_PROMPT`, `_agent_proposals_file`, `_parse_agent_proposals`, `_run_agent_proposals`)
- Modify: `apps/api/tests/test_live_llm.py` (delete the obsolete array-path planner tests)
- Test: `apps/api/tests/test_planner_layered.py` (append)

**Interfaces:**
- Consumes: `_run_agent_plan`, `_validate_items`, `_agent_plan_file` (Task 6); `_build_proposals`, `generate_plan` internals.
- Produces: `_render_plan_md(day, proposals, source="fallback", brief="", threads=None) -> str`; `generate_plan(day=None, proposals=None, source="fallback", brief="", threads=None) -> dict` (return dict gains `"brief"`, `"threads"`); `async generate_plan_with_agent(day=None) -> dict` (uses `_run_agent_plan`; return carries `brief`/`threads`).
- Removes: `PLANNER_TASK_PROMPT`, `_agent_proposals_file`, `_parse_agent_proposals`, `_run_agent_proposals` (now unreferenced after the rewire).

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_planner_layered.py`:

```python
@pytest.mark.asyncio
async def test_generate_with_agent_stages_layered_plan(monkeypatch):
    async def fake_call(prompt):
        return json.dumps(PLAN_OBJ)
    monkeypatch.setattr(planner, "_call_agent", fake_call)
    # No workdir file in tests → parser falls through to stdout.
    summary = await planner.generate_plan_with_agent("2026-06-24")
    assert summary["source"] == "agent"
    assert summary["brief"].startswith("Today is about")
    assert summary["threads"][0]["name"] == "planner"

    plan = planner.get_plan("2026-06-24")
    kinds = sorted(i["kind"] for i in plan["items"])
    assert kinds == ["calendar", "task"]
    md = plan["raw"]
    assert "## Brief" in md and "## Threads" in md and "## Agenda" in md


@pytest.mark.asyncio
async def test_generate_with_agent_falls_back_on_garbage(monkeypatch):
    async def fake_call(prompt):
        return "no json here"
    monkeypatch.setattr(planner, "_call_agent", fake_call)
    summary = await planner.generate_plan_with_agent("2026-06-24")
    assert summary["source"] == "fallback"
    assert summary["calendar_count"] >= 1  # deterministic proposals still produced


@pytest.mark.asyncio
async def test_layered_agent_path_writes_no_calendar(monkeypatch):
    """Safety: even a calendar-laden agent plan only STAGES; never writes."""
    from integrations import google_calendar
    from integrations.base import ok
    calls = []
    monkeypatch.setattr(google_calendar, "create_event",
                        lambda event, **k: calls.append(event) or ok("google_calendar", {"id": "x"}))

    async def fake_call(prompt):
        return json.dumps(PLAN_OBJ)
    monkeypatch.setattr(planner, "_call_agent", fake_call)
    await planner.generate_plan_with_agent("2026-06-24")
    assert calls == []  # no autonomous write


def test_render_lays_out_all_layers():
    md = planner._render_plan_md(
        "2026-06-24", PLAN_OBJ["items"], source="agent",
        brief=PLAN_OBJ["brief"], threads=PLAN_OBJ["threads"])
    assert "## Brief" in md and "## Threads" in md
    assert "## Agenda" in md and "## Tasks" in md
    assert "Deep work: planner" in md  # agenda block rendered


@pytest.mark.asyncio
async def test_generate_with_agent_prefers_workdir_file(tmp_path, monkeypatch):
    """Migrated from test_live_llm: the agent's workdir file wins over pane junk."""
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(PLAN_OBJ))
    monkeypatch.setattr(planner, "_agent_plan_file", lambda day: f)

    async def fake_call(prompt):
        return "pane junk, no json"
    monkeypatch.setattr(planner, "_call_agent", fake_call)
    summary = await planner.generate_plan_with_agent("2026-06-24")
    assert summary["source"] == "agent"
    assert summary["brief"].startswith("Today is about")


def test_parse_agent_plan_repairs_pane_wrapped_json():
    """Migrated from test_live_llm: tmux pane wraps long strings across lines."""
    wrapped = json.dumps(PLAN_OBJ, indent=2).replace(
        "shipping the planner learner", "shipping the\n  planner learner")
    parsed = planner._parse_agent_plan(wrapped)
    assert parsed is not None
    assert parsed["brief"] == "Today is about shipping the planner learner."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_planner_layered.py -k "layered or render or fall or workdir or wrapped" -v`
Expected: FAIL — `_render_plan_md()` got an unexpected keyword `brief` / `generate_plan_with_agent` has no `brief` in its summary.

- [ ] **Step 3: Replace `_render_plan_md`**

In `apps/api/planner.py`, replace the whole `_render_plan_md` function (lines ~269-278) with:

```python
def _render_plan_md(day: str, proposals: list[dict], source: str = "fallback",
                    brief: str = "", threads: Optional[list[dict]] = None) -> str:
    threads = threads or []
    tasks = [p for p in proposals if p["kind"] == "task"]
    cals = [p for p in proposals if p["kind"] == "calendar"]
    origin = "Proposed live by the planner agent." if source == "agent" else "Proposed by fallback heuristics (no LLM)."
    lines = [f"# Daily plan — {day}", "", f"_{origin}_", ""]
    if brief:
        lines += ["## Brief", "", brief, ""]
    if threads:
        lines += ["## Threads", ""]
        for t in threads:
            why = f" — _{t['why']}_" if t.get("why") else ""
            lines.append(f"- **{t.get('name', '')}**: {t.get('today', '')}{why}")
        lines += [""]
    lines += ["## Agenda (proposed calendar blocks — require approval)", ""]
    lines += [f"- {c['title']} — {c['rationale']}" for c in cals] or ["- (none)"]
    lines += ["", "## Tasks", ""]
    lines += [f"- {t['title']}" for t in tasks] or ["- (none)"]
    lines += ["", "_Nothing is written to the calendar until you approve each item._"]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Extend `generate_plan` to carry brief/threads**

In `apps/api/planner.py`, change the `generate_plan` signature and the two spots that use it. Replace the `def generate_plan(...)` signature line (lines ~281-285) with:

```python
def generate_plan(
    day: Optional[str] = None,
    proposals: Optional[list[dict]] = None,
    source: str = "fallback",
    brief: str = "",
    threads: Optional[list[dict]] = None,
) -> dict:
```

Then, inside `generate_plan`, replace the `path.write_text(...)` call with:

```python
    path.write_text(_render_plan_md(day, proposals, source, brief=brief, threads=threads or []))
```

and replace the `return { ... }` block at the end of `generate_plan` with:

```python
    return {
        "day": day,
        "source": source,
        "item_ids": created_ids,
        "task_count": sum(1 for p in proposals if p["kind"] == "task"),
        "calendar_count": sum(1 for p in proposals if p["kind"] == "calendar"),
        "path": str(path),
        "brief": brief,
        "threads": threads or [],
    }
```

- [ ] **Step 5: Rewrite `generate_plan_with_agent`**

In `apps/api/planner.py`, replace the whole `generate_plan_with_agent` function (lines ~325-333) with:

```python
async def generate_plan_with_agent(day: Optional[str] = None) -> dict:
    """Live path: have the planner agent draft the layered plan; fall back to the
    deterministic heuristics. Staging-only either way — no calendar writes."""
    day = day or today_str()
    plan = await _run_agent_plan(day)
    if plan and plan.get("items"):
        return generate_plan(
            day, proposals=plan["items"], source="agent",
            brief=plan.get("brief", ""), threads=plan.get("threads") or [],
        )
    return generate_plan(day)
```

- [ ] **Step 6: Delete the now-orphaned old array-path symbols from `planner.py`**

`generate_plan_with_agent` no longer calls the old path, so remove these four definitions entirely (use Edit to delete each function/constant block). **Keep `_call_agent` (planner.py:151), `_agent_context`, and `_recent_daily_notes`** — they're still used.

- `PLANNER_TASK_PROMPT = """<task name="daily_plan">...` (the whole old prompt constant)
- `def _agent_proposals_file(day: str) -> Path:` (whole function)
- `def _parse_agent_proposals(text: str) -> Optional[list[dict]]:` (whole function)
- `async def _run_agent_proposals(day: str) -> Optional[list[dict]]:` (whole function)

- [ ] **Step 7: Migrate `test_live_llm.py` (delete the obsolete array-path planner tests)**

In `apps/api/tests/test_live_llm.py`:
1. Delete the entire section from the comment `# ── planner: agent proposals + fallback ──...` (≈line 161) through the end of `test_generate_plan_with_agent_falls_back_on_garbage` (≈line 256) — this removes the `AGENT_PROPOSALS` constant and the 6 tests (`test_parse_agent_proposals_valid_with_fences`, `..._rejects_garbage`, `..._repairs_pane_wrapped_json`, `test_generate_plan_with_agent_prefers_workdir_file`, `..._uses_proposals`, `..._falls_back_on_garbage`). Their coverage is now in `test_planner_layered.py` (object form, added in Step 1).
2. Delete the now-unused `_spy_create_event` helper (≈lines 34-42).
3. Delete the now-unused imports: `import json`, `from pathlib import Path`, `from integrations import google_calendar`, `from integrations.base import ok`.
4. KEEP everything else — the brief tests, the runner_v2 tests, and `test_planner_context_includes_recent_obsidian_dailies` / `test_planner_context_no_vault_is_empty` (these still pass: Task 6 only ADDED a `"profile"` key to `_agent_context`; the `obsidian` key they assert on is unchanged).

- [ ] **Step 8: Run the planner suites — all green**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_planner_layered.py tests/test_live_llm.py tests/test_planner.py -v`
Expected: PASS — `test_planner_layered.py` (10 passed), `test_live_llm.py` (remaining tests green, no AttributeError), `test_planner.py` (especially `test_no_autonomous_write_regression` and `test_generate_plan_writes_no_calendar` — the `generate_plan` return gained `brief`/`threads` keys but `task_count`/`calendar_count` are unchanged).

- [ ] **Step 9: Verify the old symbols are fully gone**

Run: `cd ~/borina-mesh && grep -rn "PLANNER_TASK_PROMPT\|_run_agent_proposals\|_agent_proposals_file\|_parse_agent_proposals" apps/api --include=*.py | grep -v ".venv"`
Expected: NO output. If anything appears, finish removing/migrating it before committing.

- [ ] **Step 10: Commit**

```bash
cd ~/borina-mesh && git add apps/api/planner.py apps/api/tests/test_planner_layered.py apps/api/tests/test_live_llm.py
git commit -m "feat(planner): swap to layered generate/render path; remove old array path + migrate tests"
```

---

### Task 8: Morning narrative delivery

**Files:**
- Modify: `apps/api/planner.py` (add `plan_narrative_text`)
- Modify: `apps/api/daily_operator.py` (`run_phase`, `morning` branch, lines 71-80)
- Test: `apps/api/tests/test_planner_layered.py` (append) + `apps/api/tests/test_daily_operator.py` (append)

**Interfaces:**
- Consumes: `generate_plan_with_agent` summary (Task 7); `get_plan`.
- Produces: `plan_narrative_text(day:str, summary:dict) -> str` (the trimmed brief + threads + agenda for the Telegram morning message). The `morning` phase sends this narrative above the approval Card.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_planner_layered.py`:

```python
def test_plan_narrative_text_includes_layers(monkeypatch):
    summary = {"brief": "Ship the learner today.",
               "threads": [{"name": "planner", "today": "wire eod"}]}
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {
        "calendar": [{"title": "Deep work: planner"}], "tasks": [], "items": []})
    text = planner.plan_narrative_text("2026-06-24", summary)
    assert "Ship the learner today." in text
    assert "planner" in text and "wire eod" in text
    assert "Deep work: planner" in text
```

Append to `apps/api/tests/test_daily_operator.py`:

```python
@pytest.mark.asyncio
async def test_morning_phase_sends_narrative(monkeypatch):
    import daily_operator as op
    import planner
    from dispatch import dispatcher
    sent = []
    monkeypatch.setattr(op, "_chat_id", lambda: 123)
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda chat, text, **k: sent.append(text) or 1)
    monkeypatch.setattr(op, "send_card", lambda chat, card: None)

    async def fake_gen(day=None):
        return {"source": "agent", "task_count": 0, "calendar_count": 1,
                "brief": "Focus day.", "threads": [{"name": "planner", "today": "ship"}]}
    monkeypatch.setattr(planner, "generate_plan_with_agent", fake_gen)
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {
        "calendar": [{"title": "Deep work"}], "tasks": [], "items": []})
    monkeypatch.setattr(op, "_proposed_calendar_items",
                        lambda day: [{"id": 1, "title": "Deep work", "kind": "calendar",
                                      "status": "proposed"}])

    await op.run_phase("morning", day="2026-06-24", send=True)
    assert any("Focus day." in t for t in sent)  # narrative was sent
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_planner_layered.py::test_plan_narrative_text_includes_layers tests/test_daily_operator.py::test_morning_phase_sends_narrative -v`
Expected: FAIL — `module 'planner' has no attribute 'plan_narrative_text'`.

- [ ] **Step 3: Add `plan_narrative_text` to `planner.py`**

In `apps/api/planner.py`, add after `plan_digest_text` (end of file):

```python
def plan_narrative_text(day: str, summary: dict) -> str:
    """The morning Telegram narrative: brief → threads → agenda. Trimmed for chat;
    the full layered document lives in daily-plan.md."""
    brief = (summary or {}).get("brief") or ""
    threads = (summary or {}).get("threads") or []
    plan = get_plan(day)
    cals = plan.get("calendar", [])
    lines = [f"Plan for {day}"]
    if brief:
        lines += ["", brief]
    if threads:
        lines += ["", "Threads:"]
        for t in threads[:5]:
            lines.append(f"• {t.get('name', '')}: {t.get('today', '')}")
    if cals:
        lines += ["", "Agenda:"]
        for c in cals[:10]:
            lines.append(f"• {c['title']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Send the narrative in the `morning` phase**

In `apps/api/daily_operator.py`, replace the `morning` branch (lines 71-80) with:

```python
    if phase == "morning":
        # Stage the layered plan (proposals only — never writes).
        try:
            summary = await generate_plan_with_agent(day)
        except Exception as e:  # noqa: BLE001
            card = Card(headline=f"Morning plan — {day}", lines=[f"(plan generation failed: {e})"])
            if send and chat:
                send_card(chat, card)
            return card
        # Send the layered narrative (brief + threads + agenda) above the card.
        if send and chat:
            try:
                from planner import plan_narrative_text
                from dispatch.dispatcher import send_telegram_message
                from dispatch.telegram_format import format_telegram
                narrative = plan_narrative_text(day, summary)
                if narrative:
                    send_telegram_message(chat, format_telegram(narrative, max_lines=30))
            except Exception as e:  # noqa: BLE001
                print(f"[operator] morning narrative error: {e}")
        card = build_morning_card(day)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ~/borina-mesh/apps/api && python -m pytest tests/test_planner_layered.py::test_plan_narrative_text_includes_layers tests/test_daily_operator.py -k "morning or eod" -v`
Expected: PASS (narrative test + existing `test_morning_phase_builds_approval_card` + the new morning test + eod tests).

- [ ] **Step 6: Commit**

```bash
cd ~/borina-mesh && git add apps/api/planner.py apps/api/daily_operator.py apps/api/tests/test_planner_layered.py apps/api/tests/test_daily_operator.py
git commit -m "feat(planner): send layered morning narrative above the approval card"
```

---

## Final verification

- [ ] **Run the full backend suite:**

Run: `cd ~/borina-mesh/apps/api && python -m pytest -q`
Expected: all green (existing ~351 + the new conversation-log / operator-brain / planner-layered / daily-operator tests). Investigate and fix any regression before declaring done — per the safety invariant, `test_no_autonomous_write_regression` failing is a hard stop.

- [ ] **Confirm no stray references to removed symbols:**

Run: `cd ~/borina-mesh && grep -rn "PLANNER_TASK_PROMPT\|_run_agent_proposals\|_parse_agent_proposals\|_agent_proposals_file" apps/api --include=*.py | grep -v ".venv"`
Expected: no output.

- [ ] **Deploy** (only when asked, per global instructions): commit → push `origin/main` → `cd apps/web && npm run build` → `launchctl kickstart -k gui/$(id -u)/com.borina.mesh-{api,web}`. Don't restart services mid-build.

## Spec coverage check

- Operator profile (durable, fixed sections, bounded, aging) → Tasks 3, 4 (aging is prompt-driven in `LEARNER_PROMPT`).
- ConversationLog capture (post allow-list, fail-open, replies, retention) → Tasks 1, 2, 4 (`trim_older_than(30)` in `update_profile`).
- Nightly learner in eod, validate-or-keep → Tasks 4, 5.
- Layered plan (brief + threads + agenda), agenda = approvable calendar items, fallback intact → Tasks 6, 7.
- Morning narrative delivery → Task 8.
- Safety: no new write path; approve-only regression green → enforced in Tasks 6-7 tests + Final verification.
- Implementation deviation from spec: "tasks completed today" → "tasks created today + open titles" (no completion timestamp on `Task`); documented in Global Constraints + Task 4.
