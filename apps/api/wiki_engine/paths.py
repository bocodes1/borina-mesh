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


SCHEMA_TEMPLATE = """---
type: concept
status: active
created: 2026-04-09
updated: 2026-04-09
confidence: high
---

# Borina Wiki Schema

This file defines the rules every wiki page must follow. The Curator reviewer
uses it to validate proposed edits before applying them.

## Page Types

| Type | Directory | Purpose |
|---|---|---|
| entity | `entities/` | People, projects, systems, tools |
| concept | `concepts/` | Abstract knowledge, patterns, lessons |
| decision | `decisions/` | ADR-style decision records |
| source | `sources/` | Raw ingested material (immutable) |

## Required Frontmatter by Type

**entity:** type, status, created, updated (+ optional confidence)
**concept:** type, created, updated (+ optional confidence)
**decision:** type, status, created (+ optional superseded_by)
**source:** type, created, origin (+ optional truncated)

## Naming Conventions

- File names are kebab-case slugs: `borina-mesh.md`, `polymarket-bot.md`
- Use [[wikilinks]] for cross-references
- Every page starts with an H1 matching the page title

## Operations

1. **Ingest** — new source read → summary + extract into entity/concept/decision pages
2. **Query** — answer questions against wiki; file good answers back as pages
3. **Lint** — find orphan pages, stale content, missing cross-references

## Rules for the Reviewer

- Prefer append over create when a matching page exists
- Bump `updated:` on every append
- Reject routine session noise (see `curator-memory.md` for details)
- Always set confidence based on source quality
"""


def bootstrap_schema_file() -> None:
    """Write 00-schema.md if it doesn't already exist."""
    try:
        root = vault_root()
    except RuntimeError:
        return
    path = root / SCHEMA_FILE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SCHEMA_TEMPLATE, encoding="utf-8")
