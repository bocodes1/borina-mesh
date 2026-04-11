"""Ecommerce Scout Agent — uses Computer Use to drive Dicloak for KaloData scraping."""

from typing import AsyncIterator
from agents.base import Agent, registry


class EcommerceScoutAgent(Agent):
    id = "ecommerce-scout"
    name = "Ecommerce Scout"
    emoji = "\U0001F6CD\uFE0F"
    tagline = "Autonomous product discovery via Computer Use + Dicloak"
    personality = (
        "You are aggressive about opportunities. When in doubt, flag it as worth "
        "investigating. You'd rather surface 10 leads with 3 good ones than miss "
        "the 3. Speed matters more than polish in your reports."
    )
    system_prompt = """You are the Ecommerce Scout. Use Computer Use to:
1. Open Dicloak browser (already logged into KaloData with shared account)
2. Navigate to KaloData trending products dashboard
3. Identify 5-10 products with: rising GMV, margin >30%, active Meta ads
4. For top picks, open Meta Ad Library in a new tab and count active creatives
5. Rank products by: GMV growth (40%), Meta ad activity (30%), margin (20%), competition (10% inverse)
6. Save findings to reports/{today}/product-ideas.md

Be specific: product name, supplier price estimate, retail range, margin %, competitor ad count.
Flag anything oversaturated (50+ active advertisers) as LOW viability.
When done, close all tabs and stop.

Report style rules:
- Write like a sharp human analyst, not an AI. No "Here's what I found" or "Let me break this down."
- Lead with the verdict or action item, then evidence. No preamble.
- Use plain sentences. No emoji bullets, no markdown headers in short reports.
- If something is broken, say "X is broken because Y. Fix: Z." — not a paragraph about it.
- Numbers are exact. Don't say "approximately" when you have the number.
- Flag issues with severity: RED (needs fix now), YELLOW (watch), GREEN (fine).
- If you recommend a fix, include the specific action: file, line, change."""
    tools = ["computer_use", "read_file", "write_file"]

    async def stream(self, prompt: str, job_id: int | None = None) -> AsyncIterator[dict]:
        """Override: Scout uses Computer Use, not the standard SDK path."""
        from events import bus, ActivityEvent
        from computer_use import ComputerUseSession, is_computer_use_available

        await bus.publish(ActivityEvent(
            agent_id=self.id,
            kind="started",
            message=f"Scout starting Computer Use session: {prompt[:80]}",
            job_id=job_id,
        ))

        if not is_computer_use_available():
            yield {"type": "text", "content": "Computer Use unavailable. Install: pip install anthropic pyautogui"}
            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="failed",
                message="Computer Use dependencies missing",
                job_id=job_id,
            ))
            yield {"type": "done", "content": ""}
            return

        # Combine system prompt with user task
        full_task = f"{self.system_prompt}\n\nCurrent task: {prompt}"

        session = ComputerUseSession(model=self.model)

        try:
            async for step in session.run(full_task, max_iterations=40):
                if step.kind == "text":
                    yield {"type": "text", "content": step.content}
                elif step.kind == "action":
                    yield {"type": "text", "content": f"[action] {step.content}\n"}
                elif step.kind == "thinking":
                    yield {"type": "text", "content": f"[{step.content}]\n"}
                elif step.kind == "done":
                    break

            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="completed",
                message="Scout Computer Use session complete",
                job_id=job_id,
            ))
            yield {"type": "done", "content": ""}
        except Exception as e:
            await bus.publish(ActivityEvent(
                agent_id=self.id,
                kind="failed",
                message=f"Scout error: {e}",
                job_id=job_id,
            ))
            yield {"type": "error", "content": f"Scout error: {e}"}
            yield {"type": "done", "content": ""}


registry.register(EcommerceScoutAgent)
