"""Curator Agent — runs the reviewer on pending proposals.

Registered as a Borina agent so it appears in the dashboard and can be
triggered manually or on schedule. Overrides stream() to call the
wiki_engine reviewer instead of running a generic Claude prompt.
"""

from typing import AsyncIterator
from agents.base import Agent, registry


class CuratorAgent(Agent):
    id = "curator"
    name = "Curator"
    emoji = "\U0001F4DA"  # books
    tagline = "Reviews pending memory proposals and curates the wiki"
    system_prompt = """You are the Curator agent. You review pending memory
proposals from other agents and sessions, decide signal vs noise, and apply
approved edits to the wiki. You do this by running the wiki_engine's
process_pending batch runner."""
    tools = ["wiki_engine"]
    model = "claude-opus-4-6"

    async def stream(self, prompt: str, job_id: int | None = None) -> AsyncIterator[dict]:
        """Run the wiki_engine reviewer on all pending proposals."""
        from events import bus, ActivityEvent
        from wiki_engine.reviewer import process_pending

        await bus.publish(ActivityEvent(
            agent_id=self.id,
            kind="started",
            message="Curator reviewing pending proposals",
            job_id=job_id,
        ))

        yield {"type": "text", "content": "Curator: processing pending proposals...\n"}

        try:
            summary = await process_pending(max_items=50)
        except Exception as e:
            yield {"type": "error", "content": f"Curator error: {e}"}
            await bus.publish(ActivityEvent(
                agent_id=self.id, kind="failed",
                message=f"Curator failed: {e}", job_id=job_id,
            ))
            yield {"type": "done", "content": ""}
            return

        report = (
            f"Processed: {summary['processed']}\n"
            f"Approved:  {summary['approved']}\n"
            f"Rejected:  {summary['rejected']}\n"
            f"Errors:    {summary['errors']}\n"
        )
        yield {"type": "text", "content": report}

        await bus.publish(ActivityEvent(
            agent_id=self.id,
            kind="completed",
            message=f"Curator: {summary['approved']} approved, {summary['rejected']} rejected",
            job_id=job_id,
        ))
        yield {"type": "done", "content": ""}


registry.register(CuratorAgent)
