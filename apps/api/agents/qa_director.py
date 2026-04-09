"""QA Director — director-of-work + gatekeeper for every user-bound artifact."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from agents.base import Agent, registry


class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_NOTES = "approve_with_notes"
    REQUEST_RERUN = "request_rerun"
    BLOCK = "block"


@dataclass
class ReviewResult:
    verdict: ReviewVerdict
    notes: str = ""


class QADirector(Agent):
    id = "qa_director"
    name = "QA Director"
    tagline = "Plans, dispatches, reviews. Nothing reaches you unchecked."
    system_prompt = (
        "You are the QA Director for Borina Mesh. Your job has two halves:\n"
        "1) DIRECT: Given a user request, decide which sub-agents to dispatch "
        "(any subset of registered agents). Use the `dispatch` tool. Run them "
        "in parallel when independent. Synthesize one coherent answer.\n"
        "2) REVIEW: When asked to review an artifact, check it for factual "
        "grounding, completeness vs the original request, internal contradictions, "
        "hallucinated tool output, and tone. Reply with one of: "
        "APPROVE / APPROVE_WITH_NOTES: <notes> / REQUEST_RERUN: <reason> / BLOCK: <reason>."
    )

    async def dispatch(self, agent_id: str, prompt: str, job_id: int | None = None) -> str:
        agent = registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Unknown agent_id: {agent_id}")
        chunks: list[str] = []
        async for chunk in agent.stream(prompt, job_id=job_id):
            if chunk.get("type") == "text":
                chunks.append(chunk.get("content", ""))
        return "".join(chunks)

    async def review(self, artifact: str, original_request: str | None = None) -> ReviewResult:
        """Run a gatekeeper pass on an artifact. Returns ReviewResult."""
        prompt = (
            "Review the following artifact for quality. Reply on one line starting "
            "with APPROVE, APPROVE_WITH_NOTES:, REQUEST_RERUN:, or BLOCK:.\n\n"
            f"Original request: {original_request or '(unspecified)'}\n\n"
            f"Artifact:\n{artifact}"
        )
        text = ""
        async for chunk in self.stream(prompt):
            if chunk.get("type") == "text":
                text += chunk.get("content", "")
        return _parse_verdict(text)


def _parse_verdict(text: str) -> ReviewResult:
    line = text.strip().splitlines()[0] if text.strip() else ""
    upper = line.upper()
    if upper.startswith("APPROVE_WITH_NOTES"):
        return ReviewResult(ReviewVerdict.APPROVE_WITH_NOTES, line.split(":", 1)[-1].strip())
    if upper.startswith("APPROVE"):
        return ReviewResult(ReviewVerdict.APPROVE)
    if upper.startswith("REQUEST_RERUN"):
        return ReviewResult(ReviewVerdict.REQUEST_RERUN, line.split(":", 1)[-1].strip())
    if upper.startswith("BLOCK"):
        return ReviewResult(ReviewVerdict.BLOCK, line.split(":", 1)[-1].strip())
    return ReviewResult(ReviewVerdict.APPROVE_WITH_NOTES, f"unparsed: {line[:200]}")


registry.register(QADirector)
