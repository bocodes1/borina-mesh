"""Live LLM orchestration (Phase 4 §2): brief file-handoff + echo rejection,
planner agent proposals with deterministic fallback.

The safety rule is unchanged and re-asserted here: the live planner path stages
proposals only — `create_event` is never called by generation, agent or not.
"""
import asyncio
import json
from pathlib import Path

import pytest
from sqlmodel import select

import planner
import schedule_daily
from daily_brief import SECTION_IDS, parse_brief, load_brief
from db import session_scope
from integrations import google_calendar
from integrations.base import ok
from models import PlanItem, Task


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for it in s.exec(select(PlanItem)).all():
            s.delete(it)
        for t in s.exec(select(Task)).all():
            s.delete(t)
        s.commit()
    yield


def _spy_create_event(monkeypatch):
    calls = []

    def fake(event, *, user_initiated=False, calendar_id="primary"):
        calls.append({"user_initiated": user_initiated, "event": event})
        return ok("google_calendar", {"id": "evt_123"})

    monkeypatch.setattr(google_calendar, "create_event", fake)
    return calls


# ── brief: validation + coercion ─────────────────────────────────────────────

TAGGED_BRIEF = "# Daily Brief — test\n\n" + "\n\n".join(
    f'<section id="{sid}">\nreal {sid} content\n</section>' for sid in SECTION_IDS
)

HEADING_BRIEF = """# Daily Brief — Tuesday, June 9, 2026

_Crypto pipeline-confirmed; equity feed down._

## TL;DR
- bullet one

## Markets
| SPX | 7,405 |

## Watchlist Movers
- NVDA held $205

## Trading
- cash, 5th day

## Calendar
- unauthenticated

## Tasks & Focus
- none open

## Inbox
- 0 items

## Nudges
- review watchlist

## Weather & Logistics
- no location set
"""


def test_validate_accepts_tagged_brief():
    assert schedule_daily._validate_brief(TAGGED_BRIEF) == TAGGED_BRIEF


def test_validate_rejects_prompt_echo():
    # The task prompt itself contains valid <section> tags — an echoed prompt
    # must not be accepted as a brief (this happened in prod on 2026-06-09).
    assert schedule_daily._validate_brief(schedule_daily.DAILY_BRIEF_TASK_PROMPT) is None


def test_validate_coerces_heading_brief():
    out = schedule_daily._validate_brief(HEADING_BRIEF)
    assert out is not None
    parsed = parse_brief(out)
    assert set(SECTION_IDS) <= set(parsed)
    assert "bullet one" in parsed["tldr"]
    assert "NVDA held $205" in parsed["watchlist_movers"]


def test_generate_brief_prefers_agent_workdir_file(tmp_path, monkeypatch):
    # The agent saves a clean brief in its own workdir; pane capture is junk.
    f = tmp_path / "daily-brief.md"
    f.write_text(TAGGED_BRIEF)
    monkeypatch.setattr(schedule_daily, "_agent_brief_file", lambda day: f)

    async def fake_call(prompt):
        return "✻ Worked for 1m 26s\n❯ TUI junk only"

    monkeypatch.setattr(schedule_daily, "_call_agent", fake_call)
    asyncio.run(schedule_daily.generate_daily_brief(use_agent=True))
    brief = load_brief()
    assert "real tldr content" in brief["raw"]


def test_generate_brief_echo_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(
        schedule_daily, "_agent_brief_file", lambda day: tmp_path / "missing.md"
    )

    async def fake_call(prompt):
        return schedule_daily.DAILY_BRIEF_TASK_PROMPT  # pane echoed the prompt

    monkeypatch.setattr(schedule_daily, "_call_agent", fake_call)
    asyncio.run(schedule_daily.generate_daily_brief(use_agent=True))
    brief = load_brief()
    assert "fallback mode" in brief["raw"]


# ── runner_v2 extraction hardening ───────────────────────────────────────────

def test_delta_after_prompt_strips_full_echo():
    from agents.runner_v2 import _delta_after_prompt

    prompt = "line one\nline two\nline three"
    before = "old buffer\n"
    after = before + "line one\n  line two\n  line three\nreal answer"
    assert _delta_after_prompt(before, after, prompt).strip() == "real answer"


def test_strip_ui_chrome_drops_response_chrome():
    from agents.runner_v2 import _strip_ui_chrome

    text = "\n".join(
        [
            "keep me",
            "✻ Worked for 1m 26s",
            "✻ Sautéed for 1m 22s",
            "● How is Claude doing this session? (optional)",
            "  1: Bad    2: Fine   3: Good   0: Dismiss",
            "❯",
            "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents",
            "… +65 lines (ctrl+o to expand)",
        ]
    )
    assert _strip_ui_chrome(text).strip() == "keep me"


# ── planner: agent proposals + fallback ──────────────────────────────────────

AGENT_PROPOSALS = [
    {
        "kind": "task",
        "title": "Ship the mesh release",
        "rationale": "highest leverage",
        "payload": {"title": "Ship the mesh release", "tag": "work", "priority": "high"},
    },
    {
        "kind": "calendar",
        "title": "Prep: Investor sync",
        "rationale": "buffer before the 2pm",
        "payload": {
            "summary": "Prep: Investor sync",
            "start": "2026-06-09T13:45:00",
            "end": "2026-06-09T14:00:00",
        },
    },
]


def test_parse_agent_proposals_valid_with_fences():
    text = "Here you go:\n```json\n" + json.dumps(AGENT_PROPOSALS) + "\n```"
    parsed = planner._parse_agent_proposals(text)
    assert [p["kind"] for p in parsed] == ["task", "calendar"]
    assert parsed[0]["title"] == "Ship the mesh release"


def test_parse_agent_proposals_rejects_garbage():
    assert planner._parse_agent_proposals("no json here") is None
    assert planner._parse_agent_proposals("") is None
    # invalid kinds / missing calendar payload fields are dropped
    bad = [
        {"kind": "email", "title": "nope", "payload": {}},
        {"kind": "calendar", "title": "no payload", "payload": {"summary": "x"}},
    ]
    assert planner._parse_agent_proposals(json.dumps(bad)) is None


def test_parse_agent_proposals_repairs_pane_wrapped_json():
    # A tmux pane wraps long strings across lines (raw newline + indent inside
    # the literal) — this broke the first live run on 2026-06-09.
    wrapped = json.dumps(AGENT_PROPOSALS, indent=2).replace(
        "highest leverage", "highest\n  leverage"
    )
    parsed = planner._parse_agent_proposals(wrapped)
    assert parsed is not None and parsed[0]["rationale"] == "highest leverage"


def test_generate_plan_with_agent_prefers_workdir_file(tmp_path, monkeypatch):
    calls = _spy_create_event(monkeypatch)
    f = tmp_path / "proposals.json"
    f.write_text(json.dumps(AGENT_PROPOSALS))
    monkeypatch.setattr(planner, "_agent_proposals_file", lambda day: f)

    async def fake_call(prompt):
        return "pane junk, no json"

    monkeypatch.setattr(planner, "_call_agent", fake_call)
    summary = asyncio.run(planner.generate_plan_with_agent())
    assert summary["source"] == "agent"
    assert calls == []


def test_generate_plan_with_agent_uses_proposals(monkeypatch):
    monkeypatch.setattr(planner, "_agent_proposals_file", lambda day: Path("/nonexistent"))
    calls = _spy_create_event(monkeypatch)

    async def fake_call(prompt):
        return json.dumps(AGENT_PROPOSALS)

    monkeypatch.setattr(planner, "_call_agent", fake_call)
    summary = asyncio.run(planner.generate_plan_with_agent())
    assert summary["source"] == "agent"
    plan = planner.get_plan()
    titles = {i["title"] for i in plan["items"]}
    assert {"Ship the mesh release", "Prep: Investor sync"} <= titles
    assert all(i["status"] == "proposed" for i in plan["items"])
    # The invariant: the live path stages only — NEVER writes the calendar.
    assert calls == []


def test_generate_plan_with_agent_falls_back_on_garbage(monkeypatch):
    calls = _spy_create_event(monkeypatch)
    monkeypatch.setattr(planner, "_agent_proposals_file", lambda day: Path("/nonexistent"))

    async def fake_call(prompt):
        return "I could not produce JSON, sorry"

    monkeypatch.setattr(planner, "_call_agent", fake_call)
    summary = asyncio.run(planner.generate_plan_with_agent())
    assert summary["source"] == "fallback"
    plan = planner.get_plan()
    assert any(i["title"] == "Focus block (deep work)" for i in plan["items"])
    assert calls == []


def test_planner_context_includes_recent_obsidian_dailies(tmp_path, monkeypatch):
    daily = tmp_path / "01-daily"
    daily.mkdir(parents=True)
    (daily / "2026-06-09.md").write_text("# old\n- [ ] stale thing")
    (daily / "2026-06-10.md").write_text("# today\n- [ ] ship the poller test")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    ctx = planner._agent_context("2026-06-10")
    assert "ship the poller test" in ctx["obsidian"]
    assert "stale thing" in ctx["obsidian"]  # included, prompt tells agent to down-weight


def test_planner_context_no_vault_is_empty(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    ctx = planner._agent_context("2026-06-10")
    assert ctx["obsidian"] == "no vault notes"
