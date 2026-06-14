"""Obsidian as the machine's brain (Phase 7).

OpenClaw's idea: the machine accumulates its own knowledge and consults it
before acting. Here the vault IS that knowledge — daily notes, past mesh
reports, a remembered-facts file, and MEMORY.md. `recall(query)` returns the
most relevant snippets (dependency-free keyword overlap over recent files);
`remember(fact)` appends a durable fact. Dispatch injects `recall` into every
agent prompt and `vault_writeback` keeps adding reports, so the loop closes:
the mesh reads what it knew and writes what it learned.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_BRAIN_FILE = ("04-resources", "brain", "memory.md")
# Where recall reads from, newest-first, capped per area.
_SCAN = [
    ("04-resources/reports", "*.md", 40),
    ("01-daily", "*.md", 5),
    ("04-resources/brain", "*.md", 5),
]
_STOP = set("the a an and or of to in on for is are was be it this that with from "
            "what how why when who which do does my your me i you we they at as by".split())


def _vault() -> Optional[Path]:
    root = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not root:
        return None
    p = Path(root)
    return p if p.is_dir() else None


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower()) if w not in _STOP}


def recall(query: str, *, max_chars: int = 2500, per_note: int = 600) -> str:
    """Return relevant vault snippets for `query`, or "" if none/no vault.

    Scores each recent note by keyword overlap with the query; returns the top
    matches as a compact context block the agent prompt can include verbatim."""
    vault = _vault()
    if not vault:
        return ""
    q = _tokens(query)
    if not q:
        return ""

    scored: list[tuple[float, str, str]] = []
    for rel, pattern, limit in _SCAN:
        d = vault / rel
        if not d.is_dir():
            continue
        files = sorted(d.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
        for f in files:
            try:
                text = f.read_text()
            except OSError:
                continue
            overlap = q & _tokens(text)
            if not overlap:
                continue
            # Score by distinct query-term hits, lightly weighting frequency.
            score = sum(text.lower().count(t) for t in overlap) + 2 * len(overlap)
            scored.append((score, f.stem, text.strip()[:per_note]))

    if not scored:
        return ""
    scored.sort(key=lambda x: x[0], reverse=True)
    out, used = ["What the machine already knows (from its Obsidian brain):"], 0
    for _score, name, snippet in scored:
        block = f"\n- [{name}] {snippet}"
        if used + len(block) > max_chars:
            break
        out.append(block)
        used += len(block)
    return "".join(out) if len(out) > 1 else ""


def remember(fact: str, *, source: str = "mesh") -> Optional[Path]:
    """Append a durable fact to the vault brain file. Returns the path or None
    (no vault). Never raises."""
    vault = _vault()
    if not vault or not (fact or "").strip():
        return None
    try:
        p = vault.joinpath(*_BRAIN_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("---\ntitle: Brain — remembered facts\ntype: brain\n---\n\n"
                         "# Remembered facts\n\n")
        with p.open("a") as fh:
            fh.write(f"- {fact.strip()}  _(via {source})_\n")
        return p
    except OSError:
        return None
