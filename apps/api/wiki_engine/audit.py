"""Append-only audit trail for review decisions."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_engine.paths import ensure_vault_layout, REJECTED_JSONL

APPROVED_JSONL = "_queue/approved.jsonl"


def log_approved(proposal_id: str, reason: str, edits: list[dict[str, Any]]) -> None:
    """Append an approval record to approved.jsonl."""
    root = ensure_vault_layout()
    path = root / APPROVED_JSONL
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "proposal_id": proposal_id,
        "decided_at": datetime.utcnow().isoformat(),
        "reason": reason,
        "edits": edits,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def log_rejected(proposal_id: str, reason: str) -> None:
    """Append a rejection record to rejected.jsonl."""
    root = ensure_vault_layout()
    path = root / REJECTED_JSONL
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "proposal_id": proposal_id,
        "decided_at": datetime.utcnow().isoformat(),
        "reason": reason,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
