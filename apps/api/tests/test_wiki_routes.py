import pytest
from fastapi.testclient import TestClient
import os

# Set vault BEFORE importing the app so lifespan sees it
os.environ["OBSIDIAN_VAULT_PATH"] = "/tmp/borina-test-vault"

import agents.ceo  # noqa
import agents.scout  # noqa
import agents.polymarket  # noqa
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
from main import app

client = TestClient(app)


def test_propose_creates_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.post(
        "/memory/propose",
        json={
            "source": "test",
            "agent_id": "ceo",
            "prompt": "test prompt",
            "content": "test content",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["queued"] is True


def test_propose_requires_content(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.post(
        "/memory/propose",
        json={"source": "test", "agent_id": "ceo", "prompt": "p"},
    )
    assert response.status_code in (400, 422)


def test_wiki_status(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.get("/wiki/status")
    assert response.status_code == 200
    data = response.json()
    assert "pending_count" in data
    assert "vault_root" in data
