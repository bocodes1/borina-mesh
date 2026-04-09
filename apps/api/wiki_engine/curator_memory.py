"""Learned patterns file — the reviewer reads this before deciding and
appends new patterns after each run."""

from datetime import datetime
from pathlib import Path
from wiki_engine.paths import vault_root, CURATOR_MEMORY_FILE


INITIAL_CURATOR_MEMORY = """---
type: concept
status: active
created: 2026-04-09
updated: 2026-04-09
confidence: high
---

# Curator Memory — Learned Patterns

This page is maintained by the reviewer subagent. It records what counts as
signal vs noise for this vault, based on prior review decisions. The reviewer
reads this file BEFORE making any signal/noise call, and appends new patterns
AFTER each review run.

## Always Keep (Signal)

- **Decisions with real-money impact** — trading strategy changes, ad spend shifts,
  anything where a mistake would cost money. Include the rationale.
- **Entity metadata not recoverable from code** — Tailscale IPs, API endpoints,
  service hostnames, credential file locations, cron schedules, port numbers.
- **Lessons from mistakes** — pattern + fix. Example: "RSI lookback too short →
  always returns -1 → fix: extend window to 14+ candles."
- **Cross-machine coordination facts** — which service runs where, what depends
  on what.
- **Surprising or non-obvious facts** — things you wouldn't expect or that
  contradict intuition.
- **Explicit user preferences** — how they want things done, what tone they
  like, pet peeves.

## Always Filter (Noise)

- "Pushed commit abc123" — recoverable from git log
- "35/35 tests passing" — recoverable from CI
- Build success notifications
- Routine session summaries ("session N did X, Y, Z") — no standalone value
- Duplicates of existing wiki pages
- Temporary debugging noise
- Tool invocation logs that don't contain insight

## Update Rules

- New patterns learned from reviews go under **New Patterns** at the bottom.
- When a pattern has fired 3+ times, promote it to the main lists above.
- User corrections (via rejected overrides) always take precedence — add them
  to the Always Keep / Always Filter sections with a `(user corrected N)` tag.

## New Patterns
"""


def read_curator_memory() -> str:
    """Return current curator memory content, bootstrapping if missing."""
    path = vault_root() / CURATOR_MEMORY_FILE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(INITIAL_CURATOR_MEMORY, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def append_learned_pattern(pattern: str, kind: str) -> None:
    """Append a newly learned pattern to the New Patterns section.

    kind is "signal" or "noise".
    """
    path = vault_root() / CURATOR_MEMORY_FILE
    current = read_curator_memory()
    ts = datetime.utcnow().strftime("%Y-%m-%d")
    entry = f"- [{ts}] {kind.upper()}: {pattern.strip()}\n"
    # Append under "## New Patterns" header; add header if missing
    if "## New Patterns" in current:
        new_content = current.rstrip() + "\n" + entry
    else:
        new_content = current.rstrip() + "\n\n## New Patterns\n" + entry
    path.write_text(new_content, encoding="utf-8")
