"""Missions: 'mission: <goal>' fans out to multiple read-only agents via the
CEO (decompose → parallel run → synthesize). Forbidden gate still wins."""
import asyncio
import json

import pytest

import models  # noqa: F401 — register tables before conftest's init_db runs
from dispatch.intent import resolve_intent


def test_mission_prefix_routes_to_ceo():
    intent = resolve_intent("mission: full read on BTC into CPI")
    assert intent.agent == "ceo"
    assert intent.task_type == "mission"
    assert intent.dispatchable


def test_mission_with_forbidden_action_refused():
    intent = resolve_intent("mission: buy the dip on NVDA")
    assert intent.forbidden is True and intent.dispatchable is False


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
