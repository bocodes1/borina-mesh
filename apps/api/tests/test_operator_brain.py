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
