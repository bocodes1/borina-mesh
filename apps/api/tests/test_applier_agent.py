"""Applier fleet agent (Phase 1): registered, routable, in AGENT_REGISTRY."""
import agents.applier  # noqa: F401 — registers the agent
import fleet_roster as fr
from agents.base import registry
from agents.runner_v2 import AGENT_REGISTRY


def test_applier_registered_in_base_registry():
    agent = registry.get("applier")
    assert agent is not None
    assert agent.id == "applier"
    assert agent.system_prompt  # has a real persona, not empty


def test_applier_in_agent_registry():
    assert AGENT_REGISTRY["applier"]["long_id"] == "applier"


def test_applier_short_to_long_and_active(tmp_path, monkeypatch):
    from db import engine
    fr.seed_roster(engine)
    assert fr.SHORT_TO_LONG["applier"] == "applier"
    assert fr.get_state("applier") == fr.ACTIVE
    assert fr.is_routable("applier") is True
