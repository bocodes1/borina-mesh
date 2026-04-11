import os
import pytest
from agents.base import Agent


@pytest.fixture(autouse=True)
def tmp_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))


class PersonalityAgent(Agent):
    id = "personality-test"
    name = "Test"
    system_prompt = "You do things."
    personality = "You are aggressive about opportunities."


class NoPersonalityAgent(Agent):
    id = "no-personality-test"
    name = "Test NP"
    system_prompt = "You do things."


def test_effective_system_prompt_with_personality():
    agent = PersonalityAgent()
    prompt = agent.effective_system_prompt()
    assert "aggressive about opportunities" in prompt
    assert "You do things" in prompt


def test_effective_system_prompt_without_personality():
    agent = NoPersonalityAgent()
    prompt = agent.effective_system_prompt()
    assert prompt == "You do things."
    assert "aggressive" not in prompt


def test_personality_is_class_var():
    assert PersonalityAgent.personality == "You are aggressive about opportunities."
    assert NoPersonalityAgent.personality == ""


def test_effective_prompt_includes_memory():
    from memory import write_memory
    write_memory("personality-test", "# Memory\nI learned something.")
    agent = PersonalityAgent()
    prompt = agent.effective_system_prompt()
    assert "aggressive about opportunities" in prompt
    assert "I learned something" in prompt
    assert "You do things" in prompt
