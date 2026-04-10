"""QA Director — reviews agent artifacts for quality."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from agents.base import Agent, registry


class Verdict(Enum):
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


@dataclass
class ReviewResult:
    verdict: Verdict
    notes: str


class QADirector(Agent):
    id = "qa-director"
    name = "QA Director"
    emoji = "\U0001F50D"
    tagline = "Reviews agent work for quality and accuracy"
    system_prompt = """You are the QA Director of Borina Mesh. Your role:
- Review artifacts produced by other agents (reports, analyses, recommendations)
- Score each artifact: APPROVED, NEEDS_REVISION, or REJECTED
- Provide concise, actionable feedback
- Enforce quality standards: accuracy, completeness, actionability
- Be strict but fair. No rubber-stamping."""
    tools = []
    model = "claude-opus-4-6"

    async def review(
        self, artifact: str, original_request: str | None = None
    ) -> ReviewResult:
        """Review an artifact and return a verdict.

        This is a simplified sync check. A full implementation would
        call the Claude API to evaluate the artifact against criteria.
        """
        if not artifact or not artifact.strip():
            return ReviewResult(
                verdict=Verdict.REJECTED,
                notes="Empty artifact received.",
            )

        # Placeholder: real implementation will call the LLM
        return ReviewResult(
            verdict=Verdict.APPROVED,
            notes="",
        )

    async def review_and_remember(
        self, artifact: str, agent_id: str, original_request: str | None = None
    ) -> ReviewResult:
        """Review an artifact and append the verdict to the agent's memory."""
        result = await self.review(artifact, original_request)
        if result.notes:
            from datetime import datetime, timezone
            from memory import append_memory
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            append_memory(
                agent_id,
                f"## QA Feedback ({date})\n"
                f"- Verdict: {result.verdict.value}\n"
                f"- Notes: {result.notes}",
            )
        return result


registry.register(QADirector)
