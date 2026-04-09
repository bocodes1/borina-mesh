import pytest
import os
from pathlib import Path
from wiki_engine.queue import enqueue_proposal, list_pending, pop_pending, Proposal


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_enqueue_creates_file(vault):
    prop_id = enqueue_proposal(
        source="test",
        agent_id="ceo",
        prompt="test prompt",
        content="test content",
    )
    pending_files = list((vault / "_queue" / "pending").glob("*.json"))
    assert len(pending_files) == 1
    assert prop_id in pending_files[0].name


def test_list_pending(vault):
    enqueue_proposal(source="a", agent_id="ceo", prompt="p1", content="c1")
    enqueue_proposal(source="b", agent_id="scout", prompt="p2", content="c2")
    items = list_pending()
    assert len(items) == 2
    assert {i.agent_id for i in items} == {"ceo", "scout"}


def test_pop_pending_removes_file(vault):
    enqueue_proposal(source="x", agent_id="ceo", prompt="p", content="c")
    items = list_pending()
    assert len(items) == 1
    popped = pop_pending(items[0].id)
    assert popped is not None
    assert popped.agent_id == "ceo"
    assert len(list_pending()) == 0


def test_pop_nonexistent_returns_none(vault):
    result = pop_pending("nonexistent-id")
    assert result is None
