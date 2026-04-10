"""Morning brief generation — gathers last 24h of agent runs, synthesizes via CEO."""

from datetime import datetime, timedelta
from sqlmodel import Session, select

from models import AgentRun, MorningBrief


def gather_last_24h_runs(engine) -> list[AgentRun]:
    """Fetch all AgentRun records from the last 24 hours."""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    with Session(engine) as session:
        return list(session.exec(
            select(AgentRun).where(AgentRun.created_at >= cutoff)
        ).all())


def build_brief_prompt(runs: list[AgentRun]) -> str:
    """Build the CEO synthesis prompt from recent runs."""
    if not runs:
        return (
            "No agent runs in the last 24 hours. Produce a brief noting "
            "the silence and suggesting what to prioritize today."
        )

    lines = []
    for r in runs:
        qa_verdict = getattr(r, "qa_verdict", None)
        verdict = f" [QA: {qa_verdict}]" if qa_verdict else ""
        lines.append(f"- **{r.agent_id}** (job {r.job_id}): {r.output[:500]}{verdict}")

    return (
        "Synthesize these agent runs from the last 24 hours into a morning brief.\n\n"
        "## Agent Outputs\n"
        + "\n".join(lines)
        + "\n\nProduce a structured brief with these sections:\n"
        "1. **Key Findings** — the 3-5 most important things to act on today\n"
        "2. **Blockers** — anything stuck or failing\n"
        "3. **Recommendations** — what to prioritize today\n"
        "4. **Cost Summary** — total runs and estimated cost\n\n"
        "Be terse, high-signal, actionable. No filler."
    )


def compute_cost_summary(runs: list[AgentRun]) -> tuple[str, float]:
    """Return (JSON cost-by-agent string, total_cost)."""
    import json
    cost_by_agent: dict[str, float] = {}
    for r in runs:
        cost_by_agent[r.agent_id] = round(
            cost_by_agent.get(r.agent_id, 0.0) + r.cost_usd, 6
        )
    return json.dumps(cost_by_agent), round(sum(r.cost_usd for r in runs), 4)


async def generate_morning_brief(engine) -> MorningBrief:
    """Generate today's morning brief via CEO agent. Upserts by date."""
    from agents.ceo import CEOAgent

    runs = gather_last_24h_runs(engine)
    prompt = build_brief_prompt(runs)

    ceo = CEOAgent()
    output_parts: list[str] = []
    async for chunk in ceo.stream(prompt):
        if chunk.get("type") == "text":
            output_parts.append(chunk.get("content", ""))

    summary = "".join(output_parts)
    today = datetime.utcnow().date().isoformat()
    cost_json, total_cost = compute_cost_summary(runs)

    with Session(engine) as session:
        existing = session.exec(
            select(MorningBrief).where(MorningBrief.date == today)
        ).first()
        if existing:
            existing.summary = summary
            existing.cost_summary = cost_json
            existing.total_runs = len(runs)
            existing.total_cost_usd = total_cost
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

        brief = MorningBrief(
            date=today,
            summary=summary,
            cost_summary=cost_json,
            total_runs=len(runs),
            total_cost_usd=total_cost,
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)
        return brief
