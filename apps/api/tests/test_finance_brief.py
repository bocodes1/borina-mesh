"""Finance brief generation (Workstream B): omit-or-stay-silent prompt, empty
screen short-circuit (no LLM), and the regenerate route's data envelope."""
import asyncio

import pytest
from fastapi.testclient import TestClient

import agents.finance_brief as fb
from agents.finance_screen import (
    CryptoSnapshot,
    ScreenResult,
    ValuationSnapshot,
    WatchlistMove,
)
from main import app

client = TestClient(app)


def _empty_screen(**kw) -> ScreenResult:
    return ScreenResult(
        generated_at="2026-06-27T05:00:00",
        trading_date="2026-06-27",
        skipped_sections=["Macro snapshot — set FRED_API_KEY in .env to enable"],
        data_source_status={"edgar": True, "fred": False, "fmp": False,
                            "polygon": False, "coingecko": True},
        **kw,
    )


# ── _build_prompt: no apology directive, no literal {{date}} ──────────────────

def test_build_prompt_has_no_apology_directive_and_no_template_date():
    screen = _empty_screen(
        candidates_equity=[ValuationSnapshot(ticker="AAPL", name="Apple Inc")],
    )
    prompt = fb._build_prompt(screen)

    # The wrong-date bug: the literal placeholder must be gone, real date present.
    assert "{{date}}" not in prompt
    assert "2026-06-27" in prompt

    # Omit-or-stay-silent: none of the apology / hedge literals, no "say so".
    low = prompt.lower()
    assert "say so honestly" not in low
    assert "unavailable" not in low
    assert "not configured" not in low
    assert "i can't compute" not in low
    assert "apolog" not in low
    # And it must actively instruct to omit empty sections.
    assert "omit" in low


# ── empty screen short-circuits with NO LLM call ──────────────────────────────

def test_empty_screen_short_circuits_without_llm(monkeypatch):
    called = {"n": 0}

    async def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("LLM must not be called on an empty screen")

    monkeypatch.setattr(fb, "run_agent_for_answer", _boom)
    monkeypatch.setattr(fb, "run_screen", lambda **kw: _empty_screen())

    brief = asyncio.run(fb.generate_brief(use_cache=False))

    assert called["n"] == 0
    assert fb.EMPTY_BRIEF_LINE in brief.markdown
    assert brief.error is None
    assert brief.trading_date == "2026-06-27"


def test_short_circuit_appends_deterministic_crypto_line(monkeypatch):
    async def _boom(*a, **k):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(fb, "run_agent_for_answer", _boom)
    monkeypatch.setattr(
        fb, "run_screen",
        lambda **kw: _empty_screen(candidates_crypto=[
            CryptoSnapshot(symbol="BTC", name="Bitcoin", price=64000.0,
                           change_24h_pct=1.2),
        ]),
    )
    brief = asyncio.run(fb.generate_brief(use_cache=False))
    assert "BTC $64,000" in brief.markdown


# ── non-empty screen DOES call the LLM via the clean handoff file ─────────────

def test_non_empty_screen_uses_answer_file_handoff(monkeypatch):
    seen = {"job_id": None, "prompt": None}

    async def _fake(agent_id, prompt, job_id):
        seen["job_id"] = job_id
        seen["prompt"] = prompt
        return "# Morning Brief — 2026-06-27\n\n## Watchlist movement\n- NVDA +3%\n"

    monkeypatch.setattr(fb, "run_agent_for_answer", _fake)
    monkeypatch.setattr(
        fb, "run_screen",
        lambda **kw: _empty_screen(watchlist_movement=[
            WatchlistMove(ticker="NVDA", change_pct=3.0, volume_ratio=1.4,
                          close=205.0, as_of="2026-06-26"),
        ]),
    )
    brief = asyncio.run(fb.generate_brief(use_cache=False))
    assert "NVDA" in brief.markdown
    assert seen["job_id"] == 20260627  # date-derived handoff id
    assert "{{date}}" not in seen["prompt"]


# ── POST /brief/regenerate returns skipped_sections + data_source_status ──────

def test_regenerate_returns_skipped_sections_and_status(monkeypatch):
    async def _fake_generate(*a, **k):
        return fb.CachedBrief(
            trading_date="2026-06-27",
            generated_at="2026-06-27T05:00:00+00:00",
            duration_seconds=0.1,
            markdown="# Morning Brief — 2026-06-27\n\nNo candidates passed today.\n",
            screen=_empty_screen().to_dict(),
            error=None,
        )

    monkeypatch.setattr("routes.finance.generate_brief", _fake_generate)

    r = client.post("/finance/brief/regenerate")
    assert r.status_code == 200
    body = r.json()
    assert "skipped_sections" in body
    assert body["skipped_sections"] == [
        "Macro snapshot — set FRED_API_KEY in .env to enable"
    ]
    assert "data_source_status" in body
    assert body["data_source_status"]["fmp"] is False
