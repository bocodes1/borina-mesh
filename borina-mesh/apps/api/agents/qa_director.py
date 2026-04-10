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

    async def dispatch(self, agent_id: str, prompt: str, job_id: int | None = None) -> str:
        """Dispatch a prompt to another agent and collect the full response."""
        from agents.base import registry
        agent = registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Unknown agent_id: {agent_id}")
        chunks: list[str] = []
        async for chunk in agent.stream(prompt):
            if chunk.get("type") == "text":
                chunks.append(chunk.get("content", ""))
        return "".join(chunks)

    async def pipeline_dispatch(
        self,
        steps: list[dict],
        workspace_id: str,
        engine=None,
    ) -> str:
        """Execute a multi-step pipeline using the workspace blackboard.

        Each step: {"agent_id": str, "prompt_template": str}
        The prompt_template can use {context} to inject current workspace state.
        """
        import json
        from sqlmodel import Session, select
        from models import AgentWorkspace

        if engine is None:
            from db import engine

        output = ""
        for step in steps:
            with Session(engine) as session:
                entries = session.exec(
                    select(AgentWorkspace)
                    .where(AgentWorkspace.workspace_id == workspace_id)
                ).all()
            context = {e.key: e.value for e in entries}

            prompt = step["prompt_template"].replace("{context}", json.dumps(context))
            output = await self.dispatch(step["agent_id"], prompt)

            with Session(engine) as session:
                entry = AgentWorkspace(
                    workspace_id=workspace_id,
                    agent_id=step["agent_id"],
                    key=f"{step['agent_id']}_output",
                    value=output[:5000],
                )
                session.add(entry)
                session.commit()

        return output


registry.register(QADirector)
