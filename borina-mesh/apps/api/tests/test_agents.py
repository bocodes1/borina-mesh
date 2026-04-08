import pytest
from agents.base import Agent, AgentRegistry


class FakeAgent(Agent):
    id = "fake"
    name = "Fake Agent"
    emoji = "\U0001F916"
    tagline = "For testing"
    system_prompt = "You are a fake agent."


def test_agent_has_required_attributes():
    a = FakeAgent()
    assert a.id == "fake"
    assert a.name == "Fake Agent"
    assert a.emoji == "\U0001F916"
    assert a.tagline == "For testing"
    assert a.system_prompt == "You are a fake agent."


def test_agent_to_dict():
    a = FakeAgent()
    d = a.to_dict()
    assert d["id"] == "fake"
    assert d["name"] == "Fake Agent"
    assert "system_prompt" not in d  # don't expose prompts


def test_registry_register_and_get():
    registry = AgentRegistry()
    registry.register(FakeAgent)
    assert registry.get("fake") is not None
    assert registry.get("nonexistent") is None
    assert len(registry.list()) == 1


def test_registry_duplicate_raises():
    registry = AgentRegistry()
    registry.register(FakeAgent)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeAgent)
