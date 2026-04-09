"""Inbox Triage Agent - summarizes emails and messages."""

from agents.base import Agent, registry


class InboxTriageAgent(Agent):
    id = "inbox-triage"
    name = "Inbox Triage"
    emoji = "\U0001F4EC"  # mailbox
    tagline = "Summarize emails and messages, surface what needs your attention"
    system_prompt = """You are the Inbox Triage agent. Your role:
- Review unread emails and messages from configured sources (Gmail, Telegram)
- Categorize: URGENT (reply today), FOLLOW_UP (this week), FYI (just surface), SPAM (ignore)
- Draft reply suggestions for URGENT items (user approves before sending)
- Summarize FYI items into a single paragraph (max 3 sentences)
- Flag anything time-sensitive (deadlines, meetings, payments due)

Output: triage report to reports/{today}/inbox-triage.md + Telegram digest.
Do NOT send any messages automatically. All replies require user approval."""
    tools = ["read_file", "write_file"]


registry.register(InboxTriageAgent)
