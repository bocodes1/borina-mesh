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


def test_plan_narrative_text_includes_layers(monkeypatch):
    summary = {"brief": "Ship the learner today.",
               "threads": [{"name": "planner", "today": "wire eod"}]}
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {
        "calendar": [{"title": "Deep work: planner"}], "tasks": [], "items": []})
    text = planner.plan_narrative_text("2026-06-24", summary)
    assert "Ship the learner today." in text
    assert "planner" in text and "wire eod" in text
    assert "Deep work: planner" in text
