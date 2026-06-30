"""Deterministic context pack injected into a contracted agent's prompt.

Combines Obsidian vault recall (read-only), the agent's real data, and its own
last artifact, and computes a stable signal hash over the *meaningful* inputs
(data + last artifact + vault) so the scheduler can skip a run when nothing
changed. Timestamps and other volatile text are NOT part of the signal.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class ContextPack:
    text: str
    signal_hash: str
    EMPTY_SIGNAL = "empty"


def _hash(*parts: str) -> str:
    joined = " ".join(p.strip() for p in parts)
    if not joined.strip():
        return ContextPack.EMPTY_SIGNAL
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def build_context_pack(agent_id: str, *, query: str, data: str = "",
                       last_artifact: str = "") -> ContextPack:
    try:
        from dispatch.vault_brain import recall
        vault = recall(query) if query else ""
    except Exception:
        vault = ""

    sections = []
    if vault:
        sections.append(vault)
    if data:
        sections.append(f"Today's data:\n{data}")
    if last_artifact:
        sections.append(f"Your previous output (update from this — note what changed):\n{last_artifact}")
    text = "\n\n".join(sections)
    return ContextPack(text=text, signal_hash=_hash(vault, data, last_artifact))
