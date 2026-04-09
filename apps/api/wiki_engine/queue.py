"""Filesystem-backed queue for memory proposals.

Each proposal is one JSON file in $VAULT/_queue/pending/. Writers use atomic
file creation (write to .tmp then rename) to avoid partial reads.
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path

from wiki_engine.paths import vault_root, ensure_vault_layout, PENDING_DIR


@dataclass
class Proposal:
    id: str
    source: str           # "borina:ceo", "claude-code:pc", "manual", etc.
    agent_id: str         # Which agent produced it (may be the submitter not producer)
    prompt: str           # What triggered the content
    content: str          # The text to be reviewed
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


def _pending_dir() -> Path:
    root = ensure_vault_layout()
    return root / PENDING_DIR


def enqueue_proposal(source: str, agent_id: str, prompt: str, content: str) -> str:
    """Create a new proposal file. Returns the proposal id."""
    prop_id = f"{int(time.time()*1000):d}-{uuid.uuid4().hex[:8]}"
    prop = Proposal(
        id=prop_id,
        source=source,
        agent_id=agent_id,
        prompt=prompt,
        content=content,
    )
    dir_ = _pending_dir()
    tmp_path = dir_ / f"{prop_id}.json.tmp"
    final_path = dir_ / f"{prop_id}.json"
    tmp_path.write_text(json.dumps(prop.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp_path, final_path)
    return prop_id


def list_pending() -> list[Proposal]:
    """List all pending proposals, oldest first."""
    dir_ = _pending_dir()
    results: list[Proposal] = []
    for p in sorted(dir_.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append(Proposal(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    return results


def pop_pending(proposal_id: str) -> Proposal | None:
    """Read and delete a pending proposal. Returns None if not found."""
    path = _pending_dir() / f"{proposal_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        prop = Proposal(**data)
    except Exception:
        return None
    path.unlink()
    return prop
