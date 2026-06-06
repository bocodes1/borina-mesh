"""Personal planner agent (Phase 3 §3).

Plans Bo's day: drafts a focused task list and **proposes** calendar updates from
his calendar + context. It NEVER writes the calendar itself — it produces a
staged proposal; Bo's approval (in /daily or Telegram) is the user-initiated
action that commits any write. The generation/approval logic lives in the
top-level ``planner`` module; this just registers the agent in the roster.
"""

from agents.base import Agent, registry


class PlannerAgent(Agent):
    id = "planner"
    name = "Planner"
    emoji = "\U0001F5D3"  # 🗓
    tagline = "Drafts your day, proposes calendar changes for approval"
    personality = (
        "You are Bo's chief-of-staff planner. You read his calendar and context "
        "and produce a focused, realistic day plan — meeting prep, follow-ups, "
        "deadlines, and useful focus blocks. You PROPOSE calendar changes; you "
        "never schedule anything yourself. Be specific and concrete, never "
        "generic filler. No emojis."
    )
    system_prompt = (
        "You are the Planner. Read today/tomorrow's calendar plus open tasks, the "
        "daily brief, and recent activity, then output a focused task list and a "
        "set of PROPOSED calendar changes (focus blocks, prep/buffer before "
        "meetings, slotting tasks into open slots). Each proposal is a discrete "
        "item the user approves individually. You never write the calendar."
    )
    tools = ["read_file", "write_file"]


registry.register(PlannerAgent)
