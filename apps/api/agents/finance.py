"""Finance research agent — morning brief on undervalued candidates.

The full system prompt + brief format specs live in the agent's workdir at
``~/.borina/agents/finance/{CLAUDE.md, BRIEF_FORMAT.md, BRIEF_FORMAT_CRYPTO.md}``.
Claude auto-loads `CLAUDE.md` on session start, so the inline ``system_prompt``
here is short — it just points the agent at the workdir specs.
"""

from agents.base import Agent, registry


class FinanceAgent(Agent):
    id = "finance"
    name = "Finance"
    emoji = "\U0001F4B0"  # 💰
    tagline = "Junior analyst's morning brief"
    personality = (
        "You write like a junior equity analyst at a hedge fund. Facts and "
        "numbers, not opinions. Always include the bear case alongside the bull "
        "case. Never use the words 'buy', 'sell', or 'recommendation' — surface "
        "the evidence and let the reader make the call."
    )
    # The real system prompt is in ~/.borina/agents/finance/CLAUDE.md, which
    # claude reads automatically when the session's cwd is that directory.
    # The runtime overrides the per-pane workdir for this agent so CLAUDE.md
    # is found on session start.
    system_prompt = (
        "You are the Finance research agent. Your full operating spec is in "
        "CLAUDE.md in your workdir; the brief format is in BRIEF_FORMAT.md "
        "(equities) or BRIEF_FORMAT_CRYPTO.md (crypto). Read those before "
        "anything else."
    )
    tools = ["web_fetch", "read_file", "write_file"]


registry.register(FinanceAgent)
