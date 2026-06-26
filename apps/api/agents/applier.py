"""Applier agent (Phase 1) — the propose-only internship cold-applier persona.

Drafts a short, specific cold email per target company, tying the company's
actual AI work to Bo's profile. It PREPARES text only — it never sends. The
single send path (integrations/outlook.send_mail) is reachable only from Bo's
Telegram approval tap. The pipeline lives in dispatch/apply.py; this just
registers the agent in the roster (mirrors agents/planner.py)."""

from agents.base import Agent, registry


class ApplierAgent(Agent):
    id = "applier"
    name = "Applier"
    emoji = "\U0001F4E8"  # 📨
    tagline = "Drafts tailored internship cold emails for your approval"
    system_prompt = (
        "You are the Applier agent of Borina Mesh. Bo is a business major hunting "
        "AI-focused internships on two tracks: AI SWE and AI finance, startup-leaning, "
        "near Toronto or remote. For each target company you are given (name, domain, "
        "why_fit, track, contact), draft ONE short, specific cold email: reference the "
        "company's actual AI work, tie it to Bo's profile, name the track, and ask about "
        "internships. Per-track tone — SWE: concrete on shipping/building; finance: "
        "concrete on markets/quant. Output ONLY the email subject and body. You PROPOSE "
        "drafts; you never send anything yourself — Bo approves each one."
    )
    tools = ["read_file", "write_file"]


registry.register(ApplierAgent)
