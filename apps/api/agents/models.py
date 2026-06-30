"""Central model tiering registry. Env vars override per agent."""
import os

AGENT_MODELS: dict[str, str] = {
    "ceo":              "claude-opus-4-8",
    "researcher":       "claude-opus-4-8",
    "ecommerce-scout":  "claude-opus-4-8",
    "qa_director":      "claude-opus-4-8",
    "finance":          "claude-opus-4-8",   # deep-dive only (on-demand)
    "finance-brief":    "claude-sonnet-4-6", # morning brief write-up — cheaper tier
    "trader":           "claude-sonnet-4-6",
    "adset-optimizer":  "claude-sonnet-4-6",
    "inbox-triage":     "claude-haiku-4-5-20251001",
    "planner":          "claude-sonnet-4-6",
    "builder":          "claude-opus-4-8",
}

def resolve_model(agent_id: str) -> str:
    if agent_id not in AGENT_MODELS:
        raise KeyError(f"Unknown agent_id: {agent_id}")
    env_key = f"BORINA_MODEL_{agent_id.upper()}"
    return os.environ.get(env_key, AGENT_MODELS[agent_id])
