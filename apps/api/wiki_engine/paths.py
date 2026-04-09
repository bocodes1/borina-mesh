"""Vault path resolution + directory layout for the wiki engine."""

import os
from pathlib import Path

# Subdirectory layout under the vault root
ENTITIES_DIR = "entities"
CONCEPTS_DIR = "concepts"
DECISIONS_DIR = "decisions"
SOURCES_DIR = "sources"
QUEUE_DIR = "_queue"
PENDING_DIR = "_queue/pending"
ARCHIVE_DIR = "_archive"

# Top-level files
SCHEMA_FILE = "00-schema.md"
INDEX_FILE = "index.md"
LOG_FILE = "log.md"
CURATOR_MEMORY_FILE = "curator-memory.md"
APPROVED_JSONL = "_queue/approved.jsonl"
REJECTED_JSONL = "_queue/rejected.jsonl"


def vault_root() -> Path:
    """Return the vault root from OBSIDIAN_VAULT_PATH env var.

    Raises RuntimeError if not set. Expands ~ but does NOT require the path
    to already exist — callers that create directories should ensure it.
    """
    raw = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not raw:
        raise RuntimeError("OBSIDIAN_VAULT_PATH is not set")
    return Path(raw).expanduser().resolve()


def ensure_vault_layout(root: Path | None = None) -> Path:
    """Create the wiki directory layout under the vault root. Idempotent."""
    root = root or vault_root()
    for sub in (ENTITIES_DIR, CONCEPTS_DIR, DECISIONS_DIR, SOURCES_DIR, PENDING_DIR, ARCHIVE_DIR):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
