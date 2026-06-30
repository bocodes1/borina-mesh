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
from dispatch.answer import run_agent_for_answer


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


EMPTY_BRIEF_LINE = "No candidates passed today."


def _build_prompt(screen: ScreenResult) -> str:
    """Template the screen results into a prompt for the finance agent.

    The agent's CLAUDE.md (auto-loaded from its workdir) already explains who
    it is and the hard rules. This prompt carries an OMIT-OR-STAY-SILENT
    contract: only emit sections backed by real data, never print an empty
    header, never hedge or excuse a missing source. Crypto is excluded — it is
    rendered deterministically in Python, not by the LLM.
    """
    rendered = render_screen_for_prompt(screen)
    return f"""Write today's equity morning brief for {screen.trading_date} in the
voice and structure of ~/.borina/agents/finance/BRIEF_FORMAT.md. Use ONLY the
screen results below — do not invent numbers, do not fabricate candidates.

OUTPUT CONTRACT (strict):
- Emit only sections that are backed by real data in the screen below.
- Never print an empty section header. If a section has no data, omit the whole
  section silently.
- Do not hedge, fill, or excuse missing data. Source availability is surfaced
  separately in the dashboard — say nothing about it here.
- Do not write up crypto; it is rendered separately as a price line.
- If 0 candidates passed and there were 0 watchlist moves, output exactly this
  one line and nothing else: {EMPTY_BRIEF_LINE}

Output pure markdown. Do not wrap it in code fences. Start with the H1:
  # Morning Brief — {screen.trading_date}

────────────────── SCREEN RESULTS ──────────────────

{rendered}

────────────────── END OF SCREEN ──────────────────

Now write the brief.
"""


def _crypto_price_line(screen: ScreenResult) -> str:
    """Deterministic BTC/ETH/SOL price line — no LLM.

    The screen never gathers the on-chain inputs (NVT/MVRV/flows) the crypto
    rubric demands, so we don't ask the model to write up crypto. We just print
    the latest prices as a one-line factual footer when available.
    """
    parts: list[str] = []
    for c in screen.candidates_crypto:
        if c.price is None:
            continue
        chg = f" ({c.change_24h_pct:+.1f}% 24h)" if c.change_24h_pct is not None else ""
        parts.append(f"{c.symbol} ${c.price:,.0f}{chg}")
    if not parts:
        return ""
    return "**Crypto:** " + " · ".join(parts)


async def generate_brief(
    *,
    clients: Optional[FinanceClients] = None,
    universe: Optional[list[str]] = None,
    use_cache: bool = True,
) -> CachedBrief:
    """Run the screen, ask the finance agent to write up the brief, cache, return.

    If ``use_cache`` is True and today's brief already exists, returns the
    cached copy without spending any model quota. An empty screen short-circuits
    to a deterministic one-line brief with no LLM call at all.
    """
    if use_cache:
        cached = load_cached_brief()
        if cached is not None:
            return cached

    started = time.time()
    screen = run_screen(clients=clients, universe=universe)
    crypto_line = _crypto_price_line(screen)

    # Short-circuit: nothing passed the screen → emit a deterministic one-line
    # brief in Python and skip the LLM entirely. Burning Opus/Sonnet quota to
    # have a model type "No candidates passed today." is pure waste.
    if not screen.candidates_equity and not screen.watchlist_movement:
        body = f"# Morning Brief — {screen.trading_date}\n\n{EMPTY_BRIEF_LINE}"
        if crypto_line:
            body += f"\n\n{crypto_line}"
        brief = CachedBrief(
            trading_date=screen.trading_date,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration_seconds=round(time.time() - started, 2),
            markdown=body + "\n",
            screen=screen.to_dict(),
            error=None,
        )
        save_cached_brief(brief)
        return brief

    prompt = _build_prompt(screen)

    # Run the agent and read its clean handoff file (no tmux pane de-chroming).
    job_id = int(date.fromisoformat(screen.trading_date).strftime("%Y%m%d"))
    try:
        markdown = await run_agent_for_answer("finance", prompt, job_id)
        error = None if markdown.strip() else "agent returned an empty brief"
    except Exception as e:
        markdown = ""
        error = f"{type(e).__name__}: {e!r}"

    if markdown.strip() and crypto_line:
        markdown = markdown.rstrip() + f"\n\n{crypto_line}\n"

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

    # Anchor on the first H1 the model emitted. Claude's TUI swallows the
    # literal `#` for H1s, so we match either:
    #   "# Morning Brief — DATE"  (morning brief mode)
    #   "TICKER — Company Name"   (deep-dive equity, after `#` stripped)
    #   "SYMBOL — Asset Name"     (deep-dive crypto)
    # The deep-dive H1 always has the em-dash separator and is the FIRST line
    # of the model's actual output, so anchor on the first non-prompt-echo
    # line that contains "—" and looks like a title.
    lines = raw.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        stripped = ln.lstrip(" ⏺#").strip()
        # Morning brief
        if stripped.startswith("Morning Brief"):
            start = i
            lines[i] = "# " + stripped
            break
        # Deep-dive H1: looks like "TICKER — Company Name" — short ticker (1-5
        # chars, all alpha), em-dash, then content. Skip lines that contain
        # paths or URLs.
        if "—" in stripped and "/" not in stripped and len(stripped) < 120:
            head = stripped.split("—", 1)[0].strip()
            if 1 <= len(head) <= 6 and head.replace("-", "").replace(".", "").isalnum() and head.upper() == head:
                start = i
                lines[i] = "# " + stripped
                break

    # Anchor the end on the brief/deep-dive footer.
    #   "End of brief. Generated at..."  (morning brief)
    #   "Generated in Xs. Cached until..."  (deep-dive)
    end = len(lines)
    for i in range(start, len(lines)):
        if "End of brief" in lines[i] or (
            "Generated in" in lines[i] and "Cached until" in lines[i]
        ):
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
