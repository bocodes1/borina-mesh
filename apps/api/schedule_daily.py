"""schedule_daily — the longer, more useful morning brief (spec §8).

Writes a single dated artifact `reports/{today}/daily-brief.md` containing the
sectioned brief the Finance / Daily / Calendar tabs read via `daily_brief`.

Two generation paths:
- **agent (live):** route the canonical task prompt to a researcher-class agent
  which orchestrates sub-calls (researcher/trader/polymarket/inbox). Needs the
  `claude` CLI + real data keys → exercised on the Mac Mini, handed off in §12.
- **deterministic fallback:** assemble every section from local data + the
  integration statuses (saying "unavailable" where a source isn't connected,
  never fabricating). This guarantees the manual trigger always writes a valid,
  parseable brief even with no keys — which is what makes the step
  autonomous-completable.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from daily_brief import SECTION_IDS, save_brief, parse_brief, coerce_headings_to_sections
from models import Task

# The canonical scheduled task body (stored verbatim from the spec). Routed to a
# researcher-class agent; it must output ONLY the sectioned markdown brief.
DAILY_BRIEF_TASK_PROMPT = """<task name="daily_brief">
You are Bo's morning chief-of-staff. Produce a single markdown brief for today that is
genuinely useful for running the day. Be concrete, skimmable, and specific — no filler,
no generic advice. Use real data via the available tools/agents. If a data source is
unavailable, say so in one line and move on; never fabricate numbers.

Write the brief with these sections, in order:

<section id="tldr">
3–5 bullets: the single most important things for Bo today across markets, schedule,
trading, and inbox. Lead with anything time-sensitive.
</section>

<section id="markets">
Overnight + pre-market moves for the watchlist and major indices (SPX, NDX, BTC, ETH).
For each: level, overnight %, and a one-line "why" if there's a clear catalyst.
Pull from the market-data integration and the researcher agent for news.
</section>

<section id="watchlist_movers">
Top 3 movers (up and down) on Bo's watchlist with a one-line reason and whether it
changes the thesis. Read-only — no recommendations to buy/sell.
</section>

<section id="trading">
Summary from the trader + polymarket agents: any signals, the CEX-lag bot's recent
state (win rate, confidence band, last session PnL if available), and Polymarket markets
worth watching today. Surface confidence/edge as read-only intel. Flag if the bot looks
unhealthy. Never instruct a trade.
</section>

<section id="calendar">
Today's Google Calendar events in time order: time, title, location/join link.
Call out conflicts, back-to-backs, and anything needing prep.
</section>

<section id="tasks_focus">
Read open tasks from the tasks API. Pick the top 3 to focus on today given deadlines
and the calendar. One line each on why it matters now.
</section>

<section id="inbox">
From the inbox agent: count of items needing a reply, and the 3 most important with a
one-line suggested next action each. Do not send anything.
</section>

<section id="nudges">
2–4 specific, actionable nudges for the /daily tab. Each: a short title, one sentence,
and which agent or action it maps to (open chat / run agent X / review Y). These render
as one-tap suggestion cards.
</section>

<section id="weather_logistics">
One line: weather for Bo's location and any logistics impact (commute, what to wear,
outdoor plans).
</section>

Output ONLY the markdown brief. Save it to reports/{today}/daily-brief.md.
Keep total length tight enough to read in under two minutes but rich enough to act on.
</task>"""


def _section(sid: str, body: str) -> str:
    return f'<section id="{sid}">\n{body.strip()}\n</section>'


def build_fallback_brief(day: Optional[str] = None) -> str:
    """Assemble a real, sectioned brief from local data + integration statuses.

    Never fabricates: unconnected sources are reported as such. Used when the
    live agent path is unavailable (no claude CLI / no keys).
    """
    from sqlmodel import select
    from db import session_scope
    from integrations import market_data, weather, polymarket, google_calendar

    day = day or date.today().isoformat()

    # Tasks (real, from DB).
    with session_scope() as s:
        open_tasks = s.exec(
            select(Task).where(Task.done == False).order_by(Task.due)  # noqa: E712
        ).all()
    top_tasks = open_tasks[:3]

    md_status = market_data.status()
    pm = polymarket.get_overview()
    cal = google_calendar.status()
    wx = weather.get_current()

    tldr_lines = [
        f"- {len(open_tasks)} open task(s); "
        + (f"top focus: {top_tasks[0].title}" if top_tasks else "none queued"),
        "- Market data: "
        + ("connected" if md_status.connected else "not connected — add MARKET_DATA_API_KEY"),
        "- Calendar: " + ("connected" if cal.connected else "not connected — complete Google OAuth"),
    ]

    movers = (
        "Watchlist movers unavailable — market data not connected."
        if not md_status.connected
        else "No notable movers computed in fallback mode (live agent provides ranked movers)."
    )

    trading = (
        f"Polymarket bot: {'healthy' if (pm.data or {}).get('signal', {}).get('healthy') else 'state unknown'}; "
        f"read-only. {'' if pm.connected else 'Bot API not reachable.'}"
    )

    if top_tasks:
        tasks_focus = "\n".join(
            f"- **{t.title}** ({t.tag}{', due ' + t.due.isoformat()[:10] if t.due else ''}) — prioritized by due date."
            for t in top_tasks
        )
    else:
        tasks_focus = "- No open tasks. Add some in the Daily tab."

    nudges = "\n".join(
        [
            "- **Review watchlist** — quick scan of overnight moves · run agent researcher",
            "- **Check Polymarket** — surface today's edge · open chat polymarket",
        ]
    )

    weather_line = (
        f"{wx.data.get('conditions')}, {wx.data.get('temp')}° — plan accordingly."
        if wx.connected and wx.data
        else "Weather unavailable — set WEATHER_API_KEY + HOME_LAT/HOME_LON."
    )

    bodies = {
        "tldr": "\n".join(tldr_lines),
        "markets": "Major indices + watchlist quotes require the market-data integration. "
        + ("Connected." if md_status.connected else "Not connected."),
        "watchlist_movers": movers,
        "trading": trading,
        "calendar": "Today's events require Google Calendar authorization. "
        + ("Authorized." if cal.connected else "Not authorized."),
        "tasks_focus": tasks_focus,
        "inbox": "Inbox triage summary is produced by the inbox agent on its schedule; not run in fallback mode.",
        "nudges": nudges,
        "weather_logistics": weather_line,
    }

    header = f"# Daily Brief — {day}\n\n_Generated in fallback mode (no LLM). Connect data sources for the full brief._\n"
    return header + "\n\n" + "\n\n".join(_section(sid, bodies[sid]) for sid in SECTION_IDS)


# The task prompt itself contains <section> tags (as format instructions), so a
# TUI prompt-echo parses as a "valid" brief. Compare section bodies against the
# prompt's instruction bodies to reject echoes (bit us in prod on 2026-06-09).
_PROMPT_SECTIONS = parse_brief(DAILY_BRIEF_TASK_PROMPT)


def _is_prompt_echo(parsed: dict[str, str]) -> bool:
    return any(
        parsed.get(sid, "").strip() == body.strip()
        for sid, body in _PROMPT_SECTIONS.items()
        if parsed.get(sid)
    )


def _validate_brief(markdown: Optional[str]) -> Optional[str]:
    """Accept only a real sectioned brief: tldr + ≥5 sections, not a prompt
    echo. A `## Heading`-styled brief is coerced to the canonical format."""
    if not markdown or not markdown.strip():
        return None
    parsed = parse_brief(markdown)
    if "tldr" in parsed and len(parsed) >= 5 and not _is_prompt_echo(parsed):
        return markdown
    coerced = coerce_headings_to_sections(markdown)
    if coerced:
        parsed = parse_brief(coerced)
        if "tldr" in parsed and len(parsed) >= 5 and not _is_prompt_echo(parsed):
            return coerced
    return None


def _agent_brief_file(day: str) -> Path:
    """Where the researcher agent saves the brief inside its own workdir (the
    prompt instructs it to). Reading this file beats scraping the tmux pane."""
    from agents.runner_v2 import AGENT_REGISTRY, _workdir_root

    entry = AGENT_REGISTRY.get("researcher", {})
    workdir = Path(entry.get("workdir") or (_workdir_root() / "researcher"))
    return workdir / "reports" / day / "daily-brief.md"


async def _call_agent(prompt: str) -> str:
    from agents.runner_v2 import run_agent_task

    result = await run_agent_task("researcher", prompt)
    return getattr(result, "output", None) or ""


async def _run_agent_brief(day: str) -> Optional[str]:
    """Live path: dispatch a researcher-class agent with the task prompt.
    Returns validated markdown, else None (caller falls back)."""
    try:
        output = await _call_agent(DAILY_BRIEF_TASK_PROMPT.replace("{today}", day))
    except Exception as exc:  # noqa: BLE001
        print(f"[schedule_daily] agent path failed, using fallback: {exc}")
        return None
    # Preferred handoff: the file the agent wrote (pane capture is lossy —
    # echoed prompt, wrapped lines, TUI chrome).
    try:
        f = _agent_brief_file(day)
        if f.exists():
            valid = _validate_brief(f.read_text())
            if valid:
                return valid
    except Exception as exc:  # noqa: BLE001
        print(f"[schedule_daily] workdir brief unreadable: {exc}")
    return _validate_brief(output)


async def generate_daily_brief(use_agent: bool = True, day: Optional[str] = None) -> Path:
    """Generate + save today's daily-brief.md. Prefers the live agent, always
    falls back to the deterministic builder so a brief is always written."""
    day = day or date.today().isoformat()
    markdown: Optional[str] = None
    if use_agent:
        markdown = await _run_agent_brief(day)
    if not markdown:
        markdown = build_fallback_brief(day)
    return save_brief(markdown, day)
