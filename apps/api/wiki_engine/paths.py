"""Vault path resolution + directory layout for wiki v2 (5 categories, 13 subcategory files)."""

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


def bootstrap_subcategory_files(root: Path | None = None) -> list[Path]:
    """Create the 13 subcategory files if they don't exist. Returns list of created paths."""
    from wiki_engine.schema import SUBCATEGORY_FILES

    try:
        r = root or vault_root()
    except RuntimeError:
        return []

    ensure_vault_layout(r)

    HUMAN_TITLES = {
        ("trading", "strategies"): "Trading Strategies",
        ("trading", "metrics"): "Trading Metrics",
        ("trading", "leaderboard"): "Trader Leaderboard",
        ("trading", "bot-config"): "Bot Configuration",
        ("ecommerce", "products"): "Products",
        ("ecommerce", "campaigns"): "Ad Campaigns",
        ("ecommerce", "store"): "Store",
        ("business", "decisions"): "Business Decisions",
        ("business", "finances"): "Finances",
        ("infrastructure", "services"): "Services",
        ("infrastructure", "automation"): "Automation",
        ("lessons", "technical"): "Technical Lessons",
        ("lessons", "operational"): "Operational Lessons",
    }

    created = []
    for category, subcats in SUBCATEGORY_FILES.items():
        for subcategory, rel_path in subcats.items():
            file_path = r / rel_path
            if not file_path.exists():
                human_title = HUMAN_TITLES.get((category, subcategory), subcategory.title())
                template = _subcategory_template(category, subcategory, human_title)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(template, encoding="utf-8")
                created.append(file_path)

    return created


def _subcategory_template(category: str, subcategory: str, human_title: str) -> str:
    return f"""---
category: {category}
subcategory: {subcategory}
title: {human_title}
updated: 2026-04-09
---

# {human_title}

## Active

(Entries appended here by the reviewer)

## Retired

(Superseded entries moved here with retirement reason)
"""


SCHEMA_TEMPLATE = """---
category: infrastructure
title: Borina Wiki Schema
created: 2026-04-09
updated: 2026-04-09
confidence: high
---

# Borina Wiki Schema (v2.1)

This file defines the 5 categories, 13 subcategory files, and the rules the
Reviewer subagent follows. The Reviewer reads this before every decision and
defaults to REJECT unless the content clearly matches a category.

## The 13 Subcategory Files

### trading/
| File | Subcategory | What Goes Here |
|------|-------------|----------------|
| `trading/strategies.md` | strategies | Bot strategies, exit policies, entry rules, signal logic with data |
| `trading/metrics.md` | metrics | Paper/live trade performance numbers, win rates, P&L summaries |
| `trading/leaderboard.md` | leaderboard | Whale wallet profiles, top trader analysis, copy-trade targets |
| `trading/bot-config.md` | bot-config | Bot parameters, thresholds, config values that affect behavior |

### ecommerce/
| File | Subcategory | What Goes Here |
|------|-------------|----------------|
| `ecommerce/products.md` | products | KaloData product finds with GMV numbers, trending items, margin analysis |
| `ecommerce/campaigns.md` | campaigns | Meta/Google ad performance, ROAS data, creative observations |
| `ecommerce/store.md` | store | Shopify theme decisions, store setup facts, competitor teardowns |

### business/
| File | Subcategory | What Goes Here |
|------|-------------|----------------|
| `business/decisions.md` | decisions | Money-impact decisions with rationale (budget shifts, pivots, pricing) |
| `business/finances.md` | finances | Financial facts, revenue figures, cost structures |

### infrastructure/
| File | Subcategory | What Goes Here |
|------|-------------|----------------|
| `infrastructure/services.md` | services | IPs, ports, endpoints, service dependencies, LaunchAgent configs |
| `infrastructure/automation.md` | automation | Cron schedules, pipeline configs, automation rules |

### lessons/
| File | Subcategory | What Goes Here |
|------|-------------|----------------|
| `lessons/technical.md` | technical | Code/system gotchas with pattern + fix |
| `lessons/operational.md` | operational | Process/workflow lessons, decision-making gotchas |

## Entry Format

Each entry is appended under a date header:

```markdown
## YYYY-MM-DD

### Entry Title

**Status: ACTIVE**

Entry body with concrete data, specific numbers, and dates.
```

## Active/Retired Lifecycle

- Every entry starts as **ACTIVE**
- When new info supersedes an old entry, the old entry is moved to `## Retired`
  with a status of `**Status: RETIRED — reason**`
- The `## Active` and `## Retired` sections are at the bottom of each file

## Default Decision: REJECT

If content does not clearly match one of the 13 subcategories AND provide
genuine signal (not recoverable from git/logs/code), REJECT.
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
