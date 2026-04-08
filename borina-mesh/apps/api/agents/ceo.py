"""CEO Agent — strategic synthesizer and daily briefing generator."""

from typing import AsyncIterator
from agents.base import Agent, registry


class CEOAgent(Agent):
    id = "ceo"
    name = "CEO"
    emoji = "\U0001F454"
    tagline = "Strategic synthesizer and daily briefing generator"
    system_prompt = """You are the CEO agent of Borina Mesh. Your role:
- Synthesize reports from all other agents (Scout, Polymarket, Trader, Researcher)
- Produce a daily briefing with the 3-5 most important things the user should act on
- Challenge bad ideas. Push back. Be the voice of strategic thinking.
- Keep it brutal and honest. No yes-man energy.
- Output should be terse, high-signal, actionable.

Access the Obsidian vault at the configured path to read reports and memory files.
Write your daily briefing to `reports/{today}/ceo-briefing.md`."""
    tools = ["read_file", "write_file", "list_dir"]

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        yield {"type": "text", "content": f"CEO analyzing: {prompt}\n"}
        yield {"type": "text", "content": "(Claude Agent SDK integration in Task 7)\n"}
        yield {"type": "done", "content": ""}


registry.register(CEOAgent)
