"""Vault path resolution + directory layout for wiki v2 (5 categories)."""

import os
from pathlib import Path

# Category directories
TRADING_DIR = "trading"
ECOMMERCE_DIR = "ecommerce"
BUSINESS_DIR = "business"
INFRASTRUCTURE_DIR = "infrastructure"
LESSONS_DIR = "lessons"

ALL_CATEGORY_DIRS = [
    TRADING_DIR, ECOMMERCE_DIR, BUSINESS_DIR, INFRASTRUCTURE_DIR, LESSONS_DIR,
]

# Supporting dirs
QUEUE_DIR = "_queue"
PENDING_DIR = "_queue/pending"
ARCHIVE_DIR = "_archive"

# Top-level files
SCHEMA_FILE = "00-schema.md"
INDEX_FILE = "index.md"
LOG_FILE = "log.md"
CURATOR_MEMORY_FILE = "curator-memory.md"
REJECTED_JSONL = "_queue/rejected.jsonl"


def vault_root() -> Path:
    """Return the vault root from OBSIDIAN_VAULT_PATH env var."""
    raw = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not raw:
        raise RuntimeError("OBSIDIAN_VAULT_PATH is not set")
    return Path(raw).expanduser().resolve()


def ensure_vault_layout(root: Path | None = None) -> Path:
    """Create the wiki v2 directory layout. Idempotent."""
    root = root or vault_root()
    for sub in ALL_CATEGORY_DIRS + [PENDING_DIR, ARCHIVE_DIR]:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


SCHEMA_TEMPLATE = """---
category: infrastructure
title: Borina Wiki Schema
created: 2026-04-09
updated: 2026-04-09
confidence: high
---

# Borina Wiki Schema (v2)

This file defines the 5 categories and the rules the Reviewer subagent
follows. The Reviewer reads this before every decision and defaults to
REJECT unless the content clearly matches a category.

## The Five Categories

### 1. Trading (`trading/`)
Polymarket bot strategies, paper-trade results with numbers, whale wallet
moves, leaderboard trader profiles, resolution-rule edges, strategy decisions
with money impact, lessons from real losses/wins.

**Keep:** "Scalp exits cap at 40-50¢ in live trading, ride-winners strategy
  is the correct exit policy based on 39 trades"
**Reject:** "bot restarted", "tests passing", "pushed commit to run_bot.py"

### 2. Ecommerce (`ecommerce/`)
Refined Concept decisions, product scouting finds (KaloData GMV data), Meta
Ad Library observations, Google Ads performance tuning, Shopify theme
insights, competitor teardowns, creative/fal.ai wins.

**Keep:** "KaloData trending: Italian marble tables at $45K GMV 120% WoW,
  12 Meta advertisers, margin ~35%"
**Reject:** "pushed theme update", "deployed to Shopify"

### 3. Business Decisions (`business/`)
Money-impact decisions (pricing, budget allocation, ad spend shifts,
strategic pivots) with rationale. Partnership notes. Financial facts.

**Keep:** "Shifted $20/day from Meta to Google Shopping because ROAS was
  3.2x vs 1.4x over 14 days"
**Reject:** "created spreadsheet", "opened bank app"

### 4. Infrastructure (`infrastructure/`)
Non-obvious configs not recoverable from code: Tailscale IPs, API endpoints,
credential locations, cron schedules, service dependencies.

**Keep:** "Mac Mini Tailscale IP is 100.116.121.128; Borina dashboard on
  port 3000, API on 8000, Polymarket bot dashboard on 8080"
**Reject:** "brew install pango", "pip installed weasyprint"

### 5. Lessons Learned (`lessons/`)
Abstracted gotchas with the pattern + fix. Things that cost real time/money.

**Keep:** "RSI calculations need >=14 candle lookback or they always return
  -1 -- the lookback window must exceed the RSI period"
**Reject:** "fixed bug at line 47", "deleted broken function"

## Page Layout

Every page must have this frontmatter:

```yaml
---
category: trading | ecommerce | business | infrastructure | lessons
title: Short descriptive title
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: low | medium | high | confirmed
---
```

Followed by markdown body with `[[wikilinks]]` for cross-references to other
pages.

## Default Decision: REJECT

If content does not clearly match one of the five categories above AND
provide genuine signal (not recoverable from git/logs/code), REJECT.
"""


def bootstrap_schema_file() -> None:
    """Write 00-schema.md if missing."""
    try:
        root = vault_root()
    except RuntimeError:
        return
    path = root / SCHEMA_FILE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SCHEMA_TEMPLATE, encoding="utf-8")
