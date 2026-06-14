"""Obsidian write-back: every dispatch result is distilled into the vault
(04-resources/reports + a link in the daily note) so the mesh reuses what it
already learned. Disabled (returns None) when no vault is configured."""
import asyncio

import pytest

import models  # noqa: F401 — register tables before conftest's init_db runs
from dispatch.vault_writeback import save_dispatch_to_vault


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_writes_report_with_frontmatter_and_body(vault):
    p = save_dispatch_to_vault(
        agent="researcher", prompt="what moved BTC overnight",
        markdown="# BTC\n\nIt wicked below 60k.", day="2026-06-10", job_id=42,
    )
    assert p == vault / "04-resources" / "reports" / "2026-06-10-researcher-job42.md"
    text = p.read_text()
    assert text.startswith("---\n")
    assert "agent: researcher" in text
    assert "It wicked below 60k." in text
    assert "[[2026-06-10]]" in text  # links back to the daily note


def test_appends_link_to_existing_daily_note(vault):
    daily = vault / "01-daily" / "2026-06-10.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-06-10 Session Notes\n\n## Summary\n")
    save_dispatch_to_vault("trader", "bot health", "# ok", "2026-06-10", 7)
    text = daily.read_text()
    assert "## Mesh outputs" in text
    assert "[[reports/2026-06-10-trader-job7]]" in text
    assert text.startswith("# 2026-06-10 Session Notes")  # appended, not overwritten


def test_creates_daily_note_when_missing(vault):
    save_dispatch_to_vault("researcher", "x", "# y", "2026-06-11", 1)
    daily = vault / "01-daily" / "2026-06-11.md"
    assert daily.exists()
    assert "## Mesh outputs" in daily.read_text()


def test_disabled_without_vault(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    assert save_dispatch_to_vault("a", "b", "# c", "2026-06-10", 1) is None


def test_never_raises(monkeypatch, tmp_path):
    # Point the vault at a FILE so mkdir explodes internally.
    f = tmp_path / "not-a-dir"
    f.write_text("x")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(f))
    assert save_dispatch_to_vault("a", "b", "# c", "2026-06-10", 1) is None


def test_dispatcher_calls_writeback(monkeypatch, tmp_path):
    """_produce_and_reply persists to the vault after completing the job."""
    from dispatch import dispatcher, answer
    from dispatch.intent import Intent

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))

    async def fake_answer(agent_id, prompt, job_id):
        return "summary line\n\nbody"

    monkeypatch.setattr(answer, "run_agent_for_answer", fake_answer)
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: 1)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)

    intent = Intent(raw_text="what moved", agent="researcher",
                    task_type="general_question", confidence=0.5, source="fallback")
    asyncio.run(dispatcher.dispatch_intent(intent, chat_id=6452258223))
    reports = list((tmp_path / "04-resources" / "reports").glob("*.md"))
    assert len(reports) == 1
    assert "body" in reports[0].read_text()
