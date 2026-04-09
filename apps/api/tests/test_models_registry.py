import os
import pytest
from agents.models import AGENT_MODELS, resolve_model

def test_registry_contains_all_agents():
    expected = {"ceo", "researcher", "ecommerce-scout", "polymarket-intel",
                "qa_director", "trader", "adset-optimizer", "inbox-triage"}
    assert expected.issubset(AGENT_MODELS.keys())

def test_resolve_model_returns_registry_value():
    assert resolve_model("ceo") == "claude-opus-4-6"
    assert resolve_model("inbox-triage") == "claude-haiku-4-5-20251001"

def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("BORINA_MODEL_INBOX-TRIAGE", "claude-sonnet-4-6")
    assert resolve_model("inbox-triage") == "claude-sonnet-4-6"

def test_unknown_agent_raises():
    with pytest.raises(KeyError):
        resolve_model("nope")
