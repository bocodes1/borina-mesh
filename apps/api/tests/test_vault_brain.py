"""Obsidian-as-brain (Phase 7): before answering, agents recall relevant
context from the vault (daily notes, past mesh reports, MEMORY); durable facts
can be remembered back. This closes the read+write loop so the machine
accumulates its own knowledge (OpenClaw-style)."""
import pytest

import models  # noqa: F401
from dispatch import vault_brain


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    (tmp_path / "01-daily").mkdir()
    (tmp_path / "04-resources" / "reports").mkdir(parents=True)
    (tmp_path / "04-resources" / "brain").mkdir(parents=True)
    return tmp_path


def test_recall_finds_relevant_notes(vault):
    (vault / "04-resources" / "reports" / "2026-06-13-researcher-job1.md").write_text(
        "---\nagent: researcher\n---\ncoordlayer is a coordination layer for AI agents. "
        "Phases 1-10 are a solid MVP; phases 11-12 are the stale frontier."
    )
    (vault / "04-resources" / "reports" / "2026-06-10-trader-job2.md").write_text(
        "The cex-lag bot is flat, $0 at risk, 5th day correct."
    )
    ctx = vault_brain.recall("what is the status of coordlayer")
    assert "coordlayer" in ctx
    assert "cex-lag bot" not in ctx  # irrelevant note not surfaced


def test_recall_disabled_without_vault(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    assert vault_brain.recall("anything") == ""


def test_recall_empty_when_no_match(vault):
    (vault / "04-resources" / "reports" / "x.md").write_text("totally unrelated content about gardening")
    assert vault_brain.recall("quantum chromodynamics") == ""


def test_recall_caps_size(vault):
    for i in range(20):
        (vault / "04-resources" / "reports" / f"r{i}.md").write_text(
            "bitcoin " * 500 + f"note {i}"
        )
    ctx = vault_brain.recall("bitcoin", max_chars=2000)
    assert len(ctx) <= 2200  # cap + small header slack


def test_remember_appends_to_brain(vault):
    p = vault_brain.remember("Bo's main repo is coordlayer", source="researcher")
    assert p is not None
    text = (vault / "04-resources" / "brain" / "memory.md").read_text()
    assert "Bo's main repo is coordlayer" in text
    assert "researcher" in text


def test_remember_disabled_without_vault(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    assert vault_brain.remember("x") is None


def test_recall_includes_remembered_facts(vault):
    vault_brain.remember("The polymarket bot uses a CEX-lag strategy on Binance")
    ctx = vault_brain.recall("how does the polymarket bot work")
    assert "CEX-lag" in ctx
