"""Finance brief: glue between the screen, the agent, and the cache.

The brief generation flow:
1. Run the screen (deterministic Python — no LLM)
2. Template the screen results into a prompt for the finance agent
3. Have the agent write up the brief in BRIEF_FORMAT.md voice
4. Cache the result on disk so the dashboard serves the same brief all day
   (regenerate on POST /api/finance/brief/regenerate)
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from agents.finance_data import FinanceClients
from agents.finance_screen import (
    ScreenResult,
    render_screen_for_prompt,
    run_screen,
)


CACHE_DIR = Path.home() / ".borina" / "data" / "finance-briefs"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CachedBrief:
    trading_date: str
    generated_at: str  # ISO timestamp
    duration_seconds: float
    markdown: str
    screen: dict  # asdict(ScreenResult)
    error: Optional[str] = None


def _cache_path(d: Optional[date] = None) -> Path:
    d = d or date.today()
    return CACHE_DIR / f"{d.isoformat()}.json"


def load_cached_brief(d: Optional[date] = None) -> Optional[CachedBrief]:
    path = _cache_path(d)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CachedBrief(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def save_cached_brief(brief: CachedBrief) -> Path:
    path = _cache_path(date.fromisoformat(brief.trading_date))
    path.write_text(json.dumps(asdict(brief), indent=2), encoding="utf-8")
    return path


def _build_prompt(screen: ScreenResult) -> str:
    """Template the screen results into a prompt for the finance agent.

    The agent's CLAUDE.md (auto-loaded from its workdir) already explains who
    it is and the hard rules. This prompt provides only:
    1. Today's screen data
    2. A reminder of which BRIEF_FORMAT to use
    3. The "honest about gaps" reminder
    """
    rendered = render_screen_for_prompt(screen)
    return f"""Write today's morning brief in the voice and structure of
~/.borina/agents/finance/BRIEF_FORMAT.md (equities) and BRIEF_FORMAT_CRYPTO.md
(crypto). Use ONLY the screen results below — do not invent numbers, do not
fabricate candidates. If a section is empty (0 candidates passed), say so
honestly per CLAUDE.md rules.

Output the brief as pure markdown. Do not wrap it in code fences. Start with
the `# Morning Brief — {{date}}` H1 from BRIEF_FORMAT.md.

────────────────── SCREEN RESULTS ──────────────────

{rendered}

────────────────── END OF SCREEN ──────────────────

Now write the brief.
"""


async def generate_brief(
    *,
    clients: Optional[FinanceClients] = None,
    universe: Optional[list[str]] = None,
    use_cache: bool = True,
) -> CachedBrief:
    """Run the screen, ask the finance agent to write up the brief, cache, return.

    If ``use_cache`` is True and today's brief already exists, returns the
    cached copy without burning Opus quota.
    """
    if use_cache:
        cached = load_cached_brief()
        if cached is not None:
            return cached

    started = time.time()
    screen = run_screen(clients=clients, universe=universe)
    prompt = _build_prompt(screen)

    # Run the agent.
    try:
        from agents.runner_v2 import run_agent_task
        result = await run_agent_task(
            "finance",
            prompt,
            timeout_seconds=900,  # 15 min — multi-source synthesis can run long
            idle_seconds=6,
        )
        markdown = _clean_brief_output(result.output) if result.ok else ""
        error = None if result.ok else (result.error or "unknown error")
    except Exception as e:
        markdown = ""
        error = f"{type(e).__name__}: {e!r}"

    brief = CachedBrief(
        trading_date=screen.trading_date,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration_seconds=round(time.time() - started, 2),
        markdown=markdown,
        screen=screen.to_dict(),
        error=error,
    )
    save_cached_brief(brief)
    return brief


def regenerate_brief_sync() -> CachedBrief:
    """Synchronous wrapper used by the scheduler thread."""
    return asyncio.run(generate_brief(use_cache=False))


def _clean_brief_output(raw: str) -> str:
    """Strip claude TUI artifacts the supervisor's pane-diff capture leaves in.

    The runner returns a best-effort delta of pane content after the prompt.
    For the finance brief we want only the model's markdown, no:
      - prompt echo (lines starting with "> " from the input quote, plus the
        "──── SCREEN RESULTS ────" framing)
      - claude's `⏺` response-leader glyphs
      - `✻ Brewed for Xs` / `Read N files` status footers
      - bypass-permissions banner
      - the empty `❯` input prompt the TUI shows after the response
    """
    if not raw:
        return ""

    # Anchor on the brief's H1. The model writes "# Morning Brief — DATE", but
    # claude's TUI re-renders that as "⏺ Morning Brief — DATE" (no literal #).
    # So match the unique "Morning Brief —" signature regardless of prefix.
    lines = raw.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        stripped = ln.lstrip(" ⏺#").strip()
        if stripped.startswith("Morning Brief"):
            start = i
            # Restore the markdown H1 so react-markdown renders it as a heading.
            lines[i] = "# " + stripped
            break

    # Anchor the end on the brief's footer — BRIEF_FORMAT requires
    # "End of brief. Generated at {timestamp}." Cut anything past that.
    end = len(lines)
    for i in range(start, len(lines)):
        if "End of brief" in lines[i]:
            end = i + 1
            break

    cleaned = []
    for ln in lines[start:end]:
        # Drop the bypass-permissions banner if it lands inside the brief.
        if "bypass permissions on" in ln:
            continue
        # Drop claude's "✻ Brewed/Cogitated/Baked for Xs" footer line if mid-brief.
        if ln.lstrip().startswith("✻ "):
            continue
        # Strip the leading ⏺ + 2-space indent claude uses on its response body.
        if ln.startswith("  "):
            ln = ln[2:]
        cleaned.append(ln.rstrip())

    return "\n".join(cleaned).strip() + "\n"
