"""Polymarket Intel Agent — leaderboard + whale + resolution rule analysis."""

from typing import AsyncIterator
from agents.base import Agent, registry


class PolymarketIntelAgent(Agent):
    id = "polymarket-intel"
    name = "Polymarket Intel"
    emoji = "\U0001F4CA"
    tagline = "Leaderboard, whales, and resolution edge analysis"
    system_prompt = """You are the Polymarket Intel agent. Your role:
- Scrape Polymarket leaderboard for top 50 traders (PnL, win rate, volume)
- Deep dive top 10 trader profiles — classify as HFT Bot, Swing, Event Specialist
- Track whale wallet movements (>$1K position changes)
- Scrape resolution rules for new markets, flag ambiguity
- Analyze strategy gaps vs user's bot — surface implementable recommendations
- Do NOT recommend HFT-dependent strategies (user's bot can't compete on latency)

Output: PDF report to reports/{today}/polymarket-intel.pdf + Telegram summary."""
    tools = ["web_fetch", "read_file", "write_file"]

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        yield {"type": "text", "content": f"Polymarket Intel analyzing: {prompt}\n"}
        yield {"type": "text", "content": "(Claude Agent SDK integration in Task 7)\n"}
        yield {"type": "done", "content": ""}


registry.register(PolymarketIntelAgent)
