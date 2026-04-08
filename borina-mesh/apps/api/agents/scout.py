"""Ecommerce Scout Agent — product discovery from KaloData + Meta Ad Library."""

from typing import AsyncIterator
from agents.base import Agent, registry


class EcommerceScoutAgent(Agent):
    id = "ecommerce-scout"
    name = "Ecommerce Scout"
    emoji = "\U0001F6CD\uFE0F"
    tagline = "Daily dropshipping product discovery"
    system_prompt = """You are the Ecommerce Scout. Your role:
- Scan KaloData for trending products (via Claude Computer Use controlling Dicloak)
- Cross-reference Meta Ad Library for active ad validation
- Rank products by: GMV growth (40%), ad activity (30%), margin (20%), competition (10% inverse)
- Surface 5-10 branded dropshipping opportunities daily
- Be specific: supplier links, price ranges, competition level

Output: PDF report to reports/{today}/product-ideas.pdf + Telegram summary."""
    tools = ["computer_use", "read_file", "write_file"]

    async def stream(self, prompt: str) -> AsyncIterator[dict]:
        yield {"type": "text", "content": f"Scout analyzing: {prompt}\n"}
        yield {"type": "text", "content": "(Claude Agent SDK integration in Task 7)\n"}
        yield {"type": "done", "content": ""}


registry.register(EcommerceScoutAgent)
