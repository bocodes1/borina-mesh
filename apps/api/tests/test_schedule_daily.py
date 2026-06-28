"""schedule_daily — the 6am researcher brief is grounded in a context pack."""
import asyncio

import agents.context_pack as CP
import schedule_daily
from agents import runner_v2


def test_researcher_prompt_includes_context_block(monkeypatch, tmp_path):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setattr(CP, "build_context_pack",
                        lambda aid, **k: CP.ContextPack(text="VAULT+DATA", signal_hash="x"))
    captured = {}

    async def _fake_run(agent_id, prompt, **k):
        captured["prompt"] = prompt

        class R:  # minimal result
            output = "# Morning Brief\nreal content"

        return R()

    monkeypatch.setattr(runner_v2, "run_agent_task", _fake_run)
    asyncio.run(schedule_daily.generate_daily_brief(day="2026-06-18"))
    assert "VAULT+DATA" in captured["prompt"]
    assert "CONTEXT:" in captured["prompt"]
