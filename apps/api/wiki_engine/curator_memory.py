"""Curator memory — learned rejection examples that the reviewer reads
before every decision."""

from datetime import datetime
from pathlib import Path
from wiki_engine.paths import vault_root, CURATOR_MEMORY_FILE


INITIAL_CURATOR_MEMORY = """---
category: infrastructure
title: Curator Memory — Rejection Examples
created: 2026-04-09
updated: 2026-04-09
confidence: high
---

# Curator Memory — Learned Rejection Examples

The Reviewer subagent reads this file before every decision. When a
previously-approved page is later overridden by the user as "should not
have been kept," a new rejection example is appended here so the
reviewer learns from the mistake.

## Always REJECT — Concrete Anti-Examples

These are real examples of content that was wrongly kept in v1. The
reviewer must reject anything matching these patterns:

### ❌ Code fix narratives
> polybot-redeemer-fix: Deleted 90-line broken _auto_redeem() function and
> wired proper AutoRedeemer class with imports and call to check_and_redeem()
> on each bot cycle.

**Why reject:** Routine code change, recoverable from `git log run_bot.py`.
Line counts, function names, and file paths in a fix narrative are ALWAYS
noise. If there's a lesson, extract only the pattern (e.g. "Safe positions
need Builder Relayer redemption path, not direct EOA") and file it under
`lessons/` or `infrastructure/`.

### ❌ Test / build status
> Tests passing: 35/35 after Phase A patch

**Why reject:** Operational status. Recoverable from CI.

### ❌ Commit / push announcements
> Pushed commit 7954480 to main; Mac Mini auto-updater picked it up

**Why reject:** Git log recoverable.

### ❌ Session progress summaries
> In this session we completed Task 5 and moved on to Task 6

**Why reject:** Meta-commentary with no lasting signal.

### ❌ Tool invocation traces
> Ran curl against /wiki/status and got pending=605

**Why reject:** It's a debug trace, not knowledge.

### ❌ Install / environment setup
> brew install pango cairo libffi && pip install weasyprint

**Why reject:** Recoverable from the repo's README. Only keep setup notes
when they describe a non-obvious gotcha with a permanent workaround.

## Always KEEP — Positive Examples

### ✓ Trading strategy decision with data
> Switched Polymarket bot from fixed +12¢ scalp target to trailing ride-winners
> exit. Rationale: over 39 live trades, real scalps cap at 40-50¢ and early
> exits left an average of 30¢ on the table. New logic holds if contract
> >=65¢ OR momentum still confirms; exits only when contract drops 6¢ from
> peak AND Binance momentum reverses.

### ✓ Infrastructure fact
> Mac Mini Tailscale IP: 100.116.121.128. Services:
> - Borina dashboard: port 3000 (com.borina.mesh-web LaunchAgent)
> - Borina API: port 8000 (com.borina.mesh-api LaunchAgent)
> - Polymarket bot: port 8080 (separate service)
> LaunchAgents auto-restart on crash via KeepAlive=true.

### ✓ Abstracted lesson
> RSI calculations must use a lookback window >=14 candles. Shorter windows
> cause RSI to always return -1 because the calculation needs enough data
> points for both gain and loss averages. This cost the bot 39 trades
> effectively flying blind on momentum confirmation.

## Learned Patterns (Appended by Reviewer Over Time)

(Empty on bootstrap. The reviewer will add new patterns here when it makes
mistakes that the user corrects.)
"""


def read_curator_memory() -> str:
    """Return current curator memory content, bootstrapping if missing."""
    path = vault_root() / CURATOR_MEMORY_FILE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(INITIAL_CURATOR_MEMORY, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def append_learned_pattern(pattern: str, kind: str) -> None:
    """Append a newly learned pattern under 'Learned Patterns'."""
    path = vault_root() / CURATOR_MEMORY_FILE
    current = read_curator_memory()
    ts = datetime.utcnow().strftime("%Y-%m-%d")
    entry = f"- [{ts}] {kind.upper()}: {pattern.strip()}\n"
    if "## Learned Patterns" in current:
        new_content = current.rstrip() + "\n" + entry
    else:
        new_content = current.rstrip() + "\n\n## Learned Patterns\n" + entry
    path.write_text(new_content, encoding="utf-8")
