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
