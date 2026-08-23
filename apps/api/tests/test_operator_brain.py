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


@pytest.mark.asyncio
async def test_call_agent_uses_operator_runner_id(monkeypatch):
    """Regression: the nightly learner must run under the "operator" agent id,
    not "planner" — they map to distinct tmux sessions/workdirs. Using the
    wrong id silently shares the ever-growing 6:30am planner session instead."""
    import agents.runner_v2 as runner_v2

    calls = []

    async def fake_run_agent_task(agent_id, prompt):
        calls.append(agent_id)
        class Result:
            output = "ok"
        return Result()

    monkeypatch.setattr(runner_v2, "run_agent_task", fake_run_agent_task)

    await ob._call_agent("some prompt")
    assert calls == ["operator"]


@pytest.mark.asyncio
async def test_update_profile_feeds_signals_through_context_pack(monkeypatch, tmp_path):
    """Phase C1: the learner's signals (tasks/calendar/conversation/daily note)
    reach the agent via build_context_pack's `data` param, and the vault-recall
    query is built from today's actual task/event titles (C1/D3), not a fixed
    phrase."""
    import agents.context_pack as CP
    from db import session_scope
    from models import Task

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    with session_scope() as s:
        s.add(Task(title="Fix the operator agent id bug", tag="borina"))
        s.commit()

    captured = {}

    def fake_pack(agent_id, *, query, data="", last_artifact=""):
        captured["query"] = query
        captured["data"] = data
        return CP.ContextPack(text="PACKTEXT", signal_hash="x")
    monkeypatch.setattr(CP, "build_context_pack", fake_pack)

    async def fake_agent(prompt):
        captured["prompt"] = prompt
        return VALID
    monkeypatch.setattr(ob, "_call_agent", fake_agent)

    from datetime import date
    await ob.update_profile(date.today().isoformat())
    assert "Fix the operator agent id bug" in captured["data"]  # live task data went through the pack
    assert "Fix the operator agent id bug" in captured["query"]  # adaptive query uses the same titles
    assert "PACKTEXT" in captured["prompt"] and "CONTEXT:" in captured["prompt"]


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


def test_task_signal_reports_same_day_completion(monkeypatch, tmp_path):
    """Phase D1: completed_today is real (from Task.completed_at), not
    inferred from a task simply vanishing off "open" — the gap the nightly
    learner had before this: a task finished 5 minutes after creation and one
    finished 3 weeks ago both used to look identical (absent, no timestamp)."""
    from datetime import date, datetime, timedelta
    from db import session_scope
    from models import Task
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    today = date.today().isoformat()
    with session_scope() as s:
        s.add(Task(title="finished today", done=True, completed_at=datetime.utcnow()))
        s.add(Task(title="finished long ago", done=True,
                    completed_at=datetime.utcnow() - timedelta(days=20)))
        s.add(Task(title="still open", done=False))
        s.commit()
    sig = ob._task_signal(today)
    assert sig["completed_today"] == ["finished today"]
    assert "still open" in sig["open"]
    assert "finished today" not in sig["open"] and "finished long ago" not in sig["open"]
