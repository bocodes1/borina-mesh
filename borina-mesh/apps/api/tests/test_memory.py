import os
import pytest


@pytest.fixture(autouse=True)
def tmp_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_read_memory_empty():
    from memory import read_memory
    assert read_memory("ceo") == ""


def test_write_and_read_memory():
    from memory import write_memory, read_memory
    write_memory("ceo", "# CEO Memory\n\nLearned: user prefers terse output.")
    content = read_memory("ceo")
    assert "CEO Memory" in content
    assert "terse output" in content


def test_append_memory():
    from memory import write_memory, append_memory, read_memory
    write_memory("scout", "# Scout Memory\n")
    append_memory("scout", "## 2026-04-09\n- Found trending product X")
    content = read_memory("scout")
    assert "Scout Memory" in content
    assert "trending product X" in content


def test_append_memory_creates_file():
    from memory import append_memory, read_memory
    append_memory("trader", "## 2026-04-09\n- Bot health OK")
    content = read_memory("trader")
    assert "Bot health OK" in content


def test_get_memory_path():
    from memory import get_memory_path
    path = get_memory_path("ceo")
    assert path.name == "memory.md"
    assert "borina-agents" in str(path)
    assert "ceo" in str(path)


# --- Task 6: Agent.load_memory integration ---


def test_agent_load_memory():
    from memory import write_memory
    write_memory("fake-test", "# Fake Memory\n\nI remember things.")

    from agents.base import Agent

    class FakeMemAgent(Agent):
        id = "fake-test"
        name = "Fake"
        system_prompt = "You are fake."

    agent = FakeMemAgent()
    mem = agent.load_memory()
    assert "I remember things" in mem


def test_agent_load_memory_empty():
    from agents.base import Agent

    class NoMemAgent(Agent):
        id = "no-mem-test"
        name = "No Memory"
        system_prompt = "You are forgetful."

    agent = NoMemAgent()
    assert agent.load_memory() == ""


# --- Task 6: QA Director review_and_remember ---


@pytest.mark.asyncio
async def test_qa_review_and_remember_with_notes():
    """review_and_remember appends feedback to agent memory when notes are present."""
    from agents.qa_director import QADirector, ReviewResult, Verdict
    from memory import read_memory

    qa = QADirector()
    # Patch review to return a result with notes
    async def mock_review(artifact, original_request=None):
        return ReviewResult(verdict=Verdict.NEEDS_REVISION, notes="Missing data sources.")
    qa.review = mock_review

    result = await qa.review_and_remember("Some artifact text", "scout")
    assert result.verdict == Verdict.NEEDS_REVISION

    mem = read_memory("scout")
    assert "Missing data sources" in mem
    assert "needs_revision" in mem


@pytest.mark.asyncio
async def test_qa_review_and_remember_no_notes():
    """review_and_remember does NOT append to memory when notes are empty."""
    from agents.qa_director import QADirector
    from memory import read_memory

    qa = QADirector()
    # Default review returns APPROVED with empty notes
    result = await qa.review_and_remember("Good artifact", "ceo")
    assert result.notes == ""

    mem = read_memory("ceo")
    assert mem == ""


@pytest.mark.asyncio
async def test_qa_review_rejects_empty_artifact():
    from agents.qa_director import QADirector, Verdict

    qa = QADirector()
    result = await qa.review("")
    assert result.verdict == Verdict.REJECTED
    assert "Empty" in result.notes


# --- Task 6: Memory route tests ---


def test_memory_route_get_empty():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/memory/agent/nobody")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "nobody"
    assert data["content"] == ""


def test_memory_route_append_and_get():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    resp = client.post(
        "/memory/agent/test-agent/append",
        json={"entry": "## 2026-04-09\n- Learned something new"},
    )
    assert resp.status_code == 200
    assert resp.json()["appended"] is True

    resp = client.get("/memory/agent/test-agent")
    assert resp.status_code == 200
    assert "Learned something new" in resp.json()["content"]


def test_memory_route_append_empty_rejected():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    resp = client.post(
        "/memory/agent/test-agent/append",
        json={"entry": "   "},
    )
    assert resp.status_code == 400
