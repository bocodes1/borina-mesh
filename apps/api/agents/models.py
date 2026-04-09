"""Central model tiering registry. Env vars override per agent."""
import os

AGENT_MODELS: dict[str, str] = {
    "ceo":         "claude-opus-4-6",
    "researcher":  "claude-opus-4-6",
    "scout":       "claude-opus-4-6",
    "polymarket":  "claude-opus-4-6",
    "qa_director": "claude-opus-4-6",
    "trader":      "claude-sonnet-4-6",
    "adset":       "claude-sonnet-4-6",
    "inbox":       "claude-haiku-4-5-20251001",
}

def resolve_model(agent_id: str) -> str:
    if agent_id not in AGENT_MODELS:
        raise KeyError(f"Unknown agent_id: {agent_id}")
    env_key = f"BORINA_MODEL_{agent_id.upper()}"
    return os.environ.get(env_key, AGENT_MODELS[agent_id])
