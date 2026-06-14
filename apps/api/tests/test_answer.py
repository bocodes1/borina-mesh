"""Clean-answer extraction (Phase 7): the dispatch reply/PDF must contain the
agent's ANSWER, never the tmux pane scrollback (echoed prompt, ⏺ tool calls,
Bash(...) blocks, box-drawing). Primary path = file handoff; fallback = an
aggressive pane cleaner. Also: PDF is opt-in (only when the user asks)."""
import asyncio

import pytest

import models  # noqa: F401 — register tables before conftest's init_db runs
from dispatch import answer


# ── the cleaner (fallback when the agent didn't write the file) ──────────────

GARBAGE = """Produce a complete markdown report — this becomes the attached PDF, so put the depth here.

⏺ This request is ambiguous and I need to check what I can access.

⏺ Bash(echo "=== gh auth status ==="; gh auth status 2>&1 | head -10)
  ⎿  === gh auth status ===
     github.com
       ✓ Logged in to github.com account bocodes1 (keyring)

⏺ gh is authenticated. Let me find the repo.

⏺ Write(reports/2026-06-13/research-coordlayer-assessment.md)
  ⎿  Wrote 75 lines to reports/2026-06-13/research-coordlayer-assessment.md

⏺ Report saved. The answer is: coordlayer is your repo and phases 1-10 are solid.

✻ Galloping… (43s · ↓ 2.0k tokens)
● How is Claude doing this session? (optional)
  1: Bad    2: Fine   3: Good   0: Dismiss
❯
  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt
… +65 lines (ctrl+o to expand)"""


def test_clean_strips_tool_calls_and_chrome():
    out = answer.clean_agent_output(GARBAGE)
    assert "Bash(" not in out
    assert "⎿" not in out
    assert "Write(" not in out
    assert "gh auth status" not in out
    assert "Galloping" not in out
    assert "bypass permissions" not in out
    assert "1: Bad" not in out
    assert "ctrl+o to expand" not in out
    assert "Produce a complete markdown report" not in out
    # the actual prose answer survives, with the ⏺ marker stripped
    assert "coordlayer is your repo" in out
    assert not out.lstrip().startswith("⏺")


def test_clean_empty_is_empty():
    assert answer.clean_agent_output("") == ""
    assert answer.clean_agent_output("⏺ Bash(ls)\n  ⎿ a\nb") .find("Bash(") == -1


# ── file handoff (primary path) ──────────────────────────────────────────────

def test_run_agent_for_answer_prefers_file(monkeypatch, tmp_path):
    monkeypatch.setattr(answer, "_agent_workdir", lambda a: tmp_path)

    async def fake_run(agent_id, prompt, **kw):
        # The prompt must instruct the agent where to write.
        assert str(tmp_path) in prompt
        # Simulate the agent writing a CLEAN answer file + noisy pane.
        af = answer.answer_file(agent_id, 7, tmp_path)
        af.parent.mkdir(parents=True, exist_ok=True)
        af.write_text("Clean answer line.\n\nDetail here.")
        return type("R", (), {"output": "⏺ Bash(noise)\n  ⎿ junk"})()

    monkeypatch.setattr(answer, "_run_agent_task", fake_run)
    out = asyncio.run(answer.run_agent_for_answer("researcher", "what is X", 7))
    assert out.startswith("Clean answer line.")
    assert "junk" not in out and "Bash(" not in out


def test_run_agent_for_answer_falls_back_to_cleaned_pane(monkeypatch, tmp_path):
    monkeypatch.setattr(answer, "_agent_workdir", lambda a: tmp_path)

    async def fake_run(agent_id, prompt, **kw):
        return type("R", (), {"output": "⏺ Bash(x)\n  ⎿ y\n⏺ The real answer is 42."})()

    monkeypatch.setattr(answer, "_run_agent_task", fake_run)
    out = asyncio.run(answer.run_agent_for_answer("researcher", "q", 8))
    assert "The real answer is 42." in out
    assert "Bash(" not in out


# ── PDF opt-in ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "send me a pdf on NVDA", "write a full report on the bond market",
    "give me a write-up", "put it in a document", "detailed report please",
])
def test_wants_pdf_true(text):
    assert answer.wants_pdf(text) is True


@pytest.mark.parametrize("text", [
    "what moved BTC overnight", "how is the trading bot",
    "quick read on rates", "is the relief bounce holding",
])
def test_wants_pdf_false(text):
    assert answer.wants_pdf(text) is False
