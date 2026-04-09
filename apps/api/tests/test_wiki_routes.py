import os
import pytest
from fastapi.testclient import TestClient

# Set vault BEFORE importing the app
os.environ["OBSIDIAN_VAULT_PATH"] = "/tmp/borina-test-vault-v2"

import agents.ceo  # noqa
import agents.scout  # noqa
import agents.polymarket  # noqa
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
from main import app

client = TestClient(app)


def test_wiki_status_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.get("/wiki/status")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "v2"


def test_propose_requires_items(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.post("/memory/propose", json={})
    assert response.status_code in (400, 422)


def test_propose_requires_non_empty_items(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.post("/memory/propose", json={"items": []})
    assert response.status_code in (400, 422)
