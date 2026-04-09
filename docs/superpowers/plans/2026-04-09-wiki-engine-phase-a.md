# Wiki Engine — Phase A Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Check-box (`- [ ]`) syntax.

**Goal:** Build a Karpathy-style LLM wiki curation engine inside Borina Mesh. Shared queue + reviewer subagent + mutator + learned-pattern curator memory. All Borina agents (and later Claude Code sessions) propose memory through one reviewer that decides signal/noise before writing to the wiki.

**Architecture:** New `wiki_engine` Python module inside `borina-mesh/apps/api/`. Filesystem queue at `$VAULT/_queue/pending/*.json` (Obsidian Sync replicates across machines). Reviewer runs as a Borina agent on schedule + on-demand. Wiki pages are standard Obsidian markdown (YAML frontmatter + `[[wikilinks]]`) organized under `entities/`, `concepts/`, `decisions/`, `sources/` with `index.md` + `log.md` + `curator-memory.md`.

**Tech Stack:** Python 3.11, Claude Agent SDK (reviewer dispatching), SQLModel (for audit trail DB rows), frontmatter parsing via `python-frontmatter`, pathlib. No new dependencies beyond python-frontmatter.

---

## File Structure (Additions)

```
borina-mesh/apps/api/
├── wiki_engine/
│   ├── __init__.py
│   ├── paths.py               # Vault path resolution + directory layout
│   ├── schema.py              # Page types, validation, lint rules
│   ├── queue.py               # Filesystem queue: enqueue/pop/list pending
│   ├── curator_memory.py      # Read/update the learned-patterns file
│   ├── reviewer.py            # Signal/noise decision via Claude subprocess
│   ├── mutator.py             # Apply approved edits to wiki files
│   └── audit.py               # approved.jsonl / rejected.jsonl writers
├── routes/
│   └── wiki.py                # POST /memory/propose, GET /wiki/*
├── agents/
│   └── curator.py             # New Borina agent: runs reviewer on schedule
└── tests/
    ├── test_wiki_queue.py
    ├── test_wiki_schema.py
    ├── test_wiki_mutator.py
    └── test_wiki_routes.py
```

Vault additions (bootstrapped by the engine on first run):
```
$OBSIDIAN_VAULT_PATH/
├── 00-schema.md              # Wiki conventions (the curator's rulebook)
├── index.md                  # Content catalog
├── log.md                    # Append-only chronological record
├── curator-memory.md         # Learned signal/noise patterns (reviewer owns)
├── entities/                 # People, projects, systems
├── concepts/                 # Abstract knowledge, patterns
├── decisions/                # ADR-style records
├── sources/                  # Raw inputs
├── _queue/
│   ├── pending/              # Proposed memory awaiting review
│   ├── approved.jsonl        # Audit: what got accepted + why
│   └── rejected.jsonl        # Audit: what got filtered + why
└── _archive/                 # Quarantined old content (filled by Phase C)
```

---

## Task 1: Vault paths + schema file bootstrap

**Files:**
- Create: `apps/api/wiki_engine/__init__.py`
- Create: `apps/api/wiki_engine/paths.py`

- [ ] **Step 1: Create empty `__init__.py`**

Write an empty file at `borina-mesh/apps/api/wiki_engine/__init__.py`.

- [ ] **Step 2: Write paths.py**

```python
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
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/wiki_engine/__init__.py apps/api/wiki_engine/paths.py
git commit -m "feat(wiki): vault path resolver + layout bootstrap"
```

---

## Task 2: Schema + initial curator memory + initial schema file

**Files:**
- Create: `apps/api/wiki_engine/schema.py`
- Create: `apps/api/wiki_engine/curator_memory.py`
- Create: `apps/api/tests/test_wiki_schema.py`

- [ ] **Step 1: Write test for schema validation**

Write to `borina-mesh/apps/api/tests/test_wiki_schema.py`:

```python
import pytest
from wiki_engine.schema import (
    PageType, validate_frontmatter, parse_page, serialize_page, WikiPage
)


def test_page_types_exist():
    assert PageType.ENTITY.value == "entity"
    assert PageType.CONCEPT.value == "concept"
    assert PageType.DECISION.value == "decision"
    assert PageType.SOURCE.value == "source"


def test_validate_frontmatter_entity_ok():
    ok, errors = validate_frontmatter({
        "type": "entity",
        "status": "active",
        "created": "2026-04-09",
        "updated": "2026-04-09",
        "confidence": "high",
    })
    assert ok, errors


def test_validate_frontmatter_missing_type_fails():
    ok, errors = validate_frontmatter({"status": "active"})
    assert not ok
    assert any("type" in e for e in errors)


def test_validate_frontmatter_unknown_type_fails():
    ok, errors = validate_frontmatter({"type": "rubbish"})
    assert not ok


def test_parse_and_serialize_roundtrip():
    md = "---\ntype: entity\nstatus: active\ncreated: 2026-04-09\nupdated: 2026-04-09\nconfidence: high\n---\n\n# Test Entity\n\nBody here.\n"
    page = parse_page(md)
    assert isinstance(page, WikiPage)
    assert page.frontmatter["type"] == "entity"
    assert "Test Entity" in page.body
    out = serialize_page(page)
    assert "type: entity" in out
    assert "# Test Entity" in out
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_wiki_schema.py -v
```
Expected: FAIL — `ModuleNotFoundError: wiki_engine.schema`

- [ ] **Step 3: Write schema.py**

```python
"""Wiki page schema: types, validation, parse/serialize.

Uses a minimal YAML-frontmatter parser to avoid adding the `python-frontmatter`
dependency just yet. We already have PyYAML transitively via other deps.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import yaml


class PageType(str, Enum):
    ENTITY = "entity"      # People, projects, systems, tools
    CONCEPT = "concept"    # Abstract knowledge, patterns, lessons
    DECISION = "decision"  # Decision records (ADR-style)
    SOURCE = "source"      # Raw ingested material


REQUIRED_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "entity":   {"type", "status", "created", "updated"},
    "concept":  {"type", "created", "updated"},
    "decision": {"type", "status", "created"},
    "source":   {"type", "created", "origin"},
}

ALLOWED_STATUSES = {"active", "inactive", "archived", "draft", "superseded"}
ALLOWED_CONFIDENCE = {"low", "medium", "high", "confirmed"}


@dataclass
class WikiPage:
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""


def validate_frontmatter(fm: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, errors). Empty errors list means valid."""
    errors: list[str] = []

    type_value = fm.get("type")
    if not type_value:
        errors.append("missing required field: type")
        return False, errors

    if type_value not in (t.value for t in PageType):
        errors.append(f"unknown type: {type_value}")
        return False, errors

    required = REQUIRED_FIELDS_BY_TYPE.get(type_value, set())
    for key in required:
        if key not in fm:
            errors.append(f"missing required field for type={type_value}: {key}")

    status = fm.get("status")
    if status is not None and status not in ALLOWED_STATUSES:
        errors.append(f"invalid status: {status}")

    confidence = fm.get("confidence")
    if confidence is not None and confidence not in ALLOWED_CONFIDENCE:
        errors.append(f"invalid confidence: {confidence}")

    return (len(errors) == 0), errors


def parse_page(text: str) -> WikiPage:
    """Parse a markdown file with optional YAML frontmatter."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            header = text[4:end]
            body = text[end + 5 :]
            try:
                fm = yaml.safe_load(header) or {}
                if not isinstance(fm, dict):
                    fm = {}
            except yaml.YAMLError:
                fm = {}
            return WikiPage(frontmatter=fm, body=body)
    return WikiPage(frontmatter={}, body=text)


def serialize_page(page: WikiPage) -> str:
    """Write a WikiPage back to markdown with YAML frontmatter."""
    if page.frontmatter:
        header = yaml.safe_dump(page.frontmatter, sort_keys=False, default_flow_style=False).strip()
        return f"---\n{header}\n---\n\n{page.body.lstrip()}"
    return page.body
```

- [ ] **Step 4: Write curator_memory.py**

```python
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
```

- [ ] **Step 5: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_wiki_schema.py -v
```
Expected: all 5 tests pass

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/wiki_engine/schema.py apps/api/wiki_engine/curator_memory.py apps/api/tests/test_wiki_schema.py
git commit -m "feat(wiki): page schema + validation + curator memory bootstrap"
```

---

## Task 3: Filesystem queue

**Files:**
- Create: `apps/api/wiki_engine/queue.py`
- Create: `apps/api/tests/test_wiki_queue.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_wiki_queue.py`:

```python
import pytest
import os
from pathlib import Path
from wiki_engine.queue import enqueue_proposal, list_pending, pop_pending, Proposal


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_enqueue_creates_file(vault):
    prop_id = enqueue_proposal(
        source="test",
        agent_id="ceo",
        prompt="test prompt",
        content="test content",
    )
    pending_files = list((vault / "_queue" / "pending").glob("*.json"))
    assert len(pending_files) == 1
    assert prop_id in pending_files[0].name


def test_list_pending(vault):
    enqueue_proposal(source="a", agent_id="ceo", prompt="p1", content="c1")
    enqueue_proposal(source="b", agent_id="scout", prompt="p2", content="c2")
    items = list_pending()
    assert len(items) == 2
    assert {i.agent_id for i in items} == {"ceo", "scout"}


def test_pop_pending_removes_file(vault):
    enqueue_proposal(source="x", agent_id="ceo", prompt="p", content="c")
    items = list_pending()
    assert len(items) == 1
    popped = pop_pending(items[0].id)
    assert popped is not None
    assert popped.agent_id == "ceo"
    assert len(list_pending()) == 0


def test_pop_nonexistent_returns_none(vault):
    result = pop_pending("nonexistent-id")
    assert result is None
```

- [ ] **Step 2: Run to verify fail**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh/apps/api
python -m pytest tests/test_wiki_queue.py -v
```

- [ ] **Step 3: Write queue.py**

```python
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_wiki_queue.py -v
```
Expected: 4 pass

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/wiki_engine/queue.py apps/api/tests/test_wiki_queue.py
git commit -m "feat(wiki): filesystem-backed proposal queue"
```

---

## Task 4: Mutator — apply approved edits to wiki files

**Files:**
- Create: `apps/api/wiki_engine/mutator.py`
- Create: `apps/api/wiki_engine/audit.py`
- Create: `apps/api/tests/test_wiki_mutator.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_wiki_mutator.py`:

```python
import pytest
import json
from pathlib import Path
from wiki_engine.mutator import apply_edit, EditOp
from wiki_engine.audit import log_approved, log_rejected


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_create_entity_page(vault):
    edit = EditOp(
        action="create",
        page_type="entity",
        slug="borina-mesh",
        frontmatter={
            "type": "entity",
            "status": "active",
            "created": "2026-04-09",
            "updated": "2026-04-09",
        },
        body="# Borina Mesh\n\nMulti-agent command center.",
    )
    path = apply_edit(edit)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "type: entity" in content
    assert "# Borina Mesh" in content


def test_append_to_existing(vault):
    entity_dir = vault / "entities"
    entity_dir.mkdir(parents=True)
    (entity_dir / "test.md").write_text(
        "---\ntype: entity\nstatus: active\ncreated: 2026-04-09\nupdated: 2026-04-09\n---\n\n# Test\n\nOriginal.\n",
        encoding="utf-8"
    )

    edit = EditOp(
        action="append",
        page_type="entity",
        slug="test",
        frontmatter={},
        body="\n## Update\n\nNew info appended.\n",
    )
    path = apply_edit(edit)
    content = path.read_text(encoding="utf-8")
    assert "Original." in content
    assert "New info appended." in content


def test_log_approved_writes_jsonl(vault):
    log_approved(
        proposal_id="abc123",
        reason="valuable decision record",
        edits=[{"action": "create", "page_type": "decision", "slug": "test"}],
    )
    log_file = vault / "_queue" / "approved.jsonl"
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["proposal_id"] == "abc123"


def test_log_rejected_writes_jsonl(vault):
    log_rejected(
        proposal_id="def456",
        reason="routine session log, no signal",
    )
    log_file = vault / "_queue" / "rejected.jsonl"
    assert log_file.exists()
    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["proposal_id"] == "def456"
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/test_wiki_mutator.py -v
```

- [ ] **Step 3: Write mutator.py**

```python
"""Apply approved edits to wiki files."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_engine.paths import (
    vault_root, ensure_vault_layout,
    ENTITIES_DIR, CONCEPTS_DIR, DECISIONS_DIR, SOURCES_DIR,
    INDEX_FILE, LOG_FILE,
)
from wiki_engine.schema import parse_page, serialize_page, WikiPage


DIR_BY_TYPE = {
    "entity": ENTITIES_DIR,
    "concept": CONCEPTS_DIR,
    "decision": DECISIONS_DIR,
    "source": SOURCES_DIR,
}


@dataclass
class EditOp:
    action: str          # "create", "append", "update_frontmatter"
    page_type: str       # entity | concept | decision | source
    slug: str            # e.g. "borina-mesh"
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""


def _page_path(page_type: str, slug: str) -> Path:
    root = ensure_vault_layout()
    sub = DIR_BY_TYPE.get(page_type)
    if sub is None:
        raise ValueError(f"unknown page type: {page_type}")
    safe_slug = slug.strip().lower().replace(" ", "-")
    return root / sub / f"{safe_slug}.md"


def apply_edit(edit: EditOp) -> Path:
    """Apply a single edit op to the wiki. Returns the affected file path."""
    path = _page_path(edit.page_type, edit.slug)
    path.parent.mkdir(parents=True, exist_ok=True)

    if edit.action == "create":
        page = WikiPage(frontmatter=edit.frontmatter, body=edit.body)
        path.write_text(serialize_page(page), encoding="utf-8")
    elif edit.action == "append":
        if path.exists():
            current = parse_page(path.read_text(encoding="utf-8"))
            current.body = (current.body.rstrip() + "\n" + edit.body).lstrip()
            if edit.frontmatter:
                current.frontmatter.update(edit.frontmatter)
            # Bump updated timestamp if the page has one
            if "updated" in current.frontmatter:
                current.frontmatter["updated"] = datetime.utcnow().strftime("%Y-%m-%d")
            path.write_text(serialize_page(current), encoding="utf-8")
        else:
            # Treat append-to-missing as create
            page = WikiPage(frontmatter=edit.frontmatter, body=edit.body)
            path.write_text(serialize_page(page), encoding="utf-8")
    elif edit.action == "update_frontmatter":
        if path.exists():
            current = parse_page(path.read_text(encoding="utf-8"))
            current.frontmatter.update(edit.frontmatter)
            if "updated" in current.frontmatter:
                current.frontmatter["updated"] = datetime.utcnow().strftime("%Y-%m-%d")
            path.write_text(serialize_page(current), encoding="utf-8")
    else:
        raise ValueError(f"unknown action: {edit.action}")

    return path


def append_to_log(message: str) -> None:
    """Append a line to log.md with timestamp prefix."""
    root = ensure_vault_layout()
    log_path = root / LOG_FILE
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    line = f"## [{ts}] {message}\n"
    if log_path.exists():
        log_path.write_text(log_path.read_text(encoding="utf-8").rstrip() + "\n" + line, encoding="utf-8")
    else:
        log_path.write_text(f"# Activity Log\n\n{line}", encoding="utf-8")
```

- [ ] **Step 4: Write audit.py**

```python
"""Append-only audit trail for review decisions."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_engine.paths import ensure_vault_layout, APPROVED_JSONL, REJECTED_JSONL


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
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_wiki_mutator.py -v
```
Expected: 4 pass

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/wiki_engine/mutator.py apps/api/wiki_engine/audit.py apps/api/tests/test_wiki_mutator.py
git commit -m "feat(wiki): mutator + audit trail for approved/rejected proposals"
```

---

## Task 5: Reviewer subagent

**Files:**
- Create: `apps/api/wiki_engine/reviewer.py`

- [ ] **Step 1: Write reviewer.py**

```python
"""Reviewer subagent — decides signal/noise for a proposal and emits edits.

Uses Claude Agent SDK (subprocess mode, Max subscription). Reads curator_memory
before deciding. Returns a structured decision:

{
    "decision": "approve" | "reject",
    "reason": "short explanation",
    "edits": [EditOp dicts],
    "learned_pattern": null | {"kind": "signal|noise", "pattern": "..."}
}
"""

import json
import re
from typing import AsyncIterator

from wiki_engine.queue import Proposal
from wiki_engine.curator_memory import read_curator_memory, append_learned_pattern


REVIEWER_SYSTEM_PROMPT = """You are the Borina Wiki Curator reviewer. Your job is
to decide whether a proposed memory item is signal (keep) or noise (filter).

You will be given:
1. The current curator memory file (learned patterns about signal vs noise)
2. A single proposal with source, agent_id, prompt, and content

You MUST output a single JSON object with this shape, and nothing else:

{
  "decision": "approve" | "reject",
  "reason": "one-sentence rationale referencing a curator memory rule",
  "edits": [
    {
      "action": "create" | "append" | "update_frontmatter",
      "page_type": "entity" | "concept" | "decision" | "source",
      "slug": "kebab-case-slug",
      "frontmatter": { "type": "entity|concept|decision|source", "status": "...", "created": "YYYY-MM-DD", "updated": "YYYY-MM-DD", "confidence": "..." },
      "body": "markdown body with [[wikilinks]] where appropriate"
    }
  ],
  "learned_pattern": null | { "kind": "signal" | "noise", "pattern": "short description of what you learned" }
}

Rules:
- If decision is "reject", edits MUST be an empty array.
- If decision is "approve", edits MUST contain at least one operation.
- Only emit learned_pattern if this proposal taught you something NOT already in curator memory. Otherwise null.
- Prefer append over create when a matching page likely exists.
- Use kebab-case slugs without file extensions.
- Body should be concise, written in prose, with [[wikilinks]] to cross-reference
  other likely pages (e.g. [[borina-mesh]], [[polymarket-bot]]).
- Bump the "updated" frontmatter field to today's date on any append.
"""


async def review_proposal(proposal: Proposal) -> dict:
    """Dispatch the reviewer subagent for one proposal.

    Returns the parsed decision dict. Raises on transport errors but catches
    JSON parse errors and returns a reject-with-reason decision.
    """
    curator_memory = read_curator_memory()

    user_message = f"""## Curator Memory (current learned patterns)

{curator_memory}

---

## Proposal to Review

- **id**: {proposal.id}
- **source**: {proposal.source}
- **agent_id**: {proposal.agent_id}
- **prompt**: {proposal.prompt}

### Content

{proposal.content}

---

Output ONLY the JSON object described in your system prompt. No prose around it."""

    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except ImportError:
        return {
            "decision": "reject",
            "reason": "claude-agent-sdk not installed",
            "edits": [],
            "learned_pattern": None,
        }

    options = ClaudeAgentOptions(
        system_prompt=REVIEWER_SYSTEM_PROMPT,
        model="claude-opus-4-6",
    )

    buffer_parts: list[str] = []
    try:
        async for message in query(prompt=user_message, options=options):
            text = _extract_text(message)
            if text:
                buffer_parts.append(text)
    except Exception as e:
        return {
            "decision": "reject",
            "reason": f"reviewer error: {e}",
            "edits": [],
            "learned_pattern": None,
        }

    full = "".join(buffer_parts).strip()
    decision = _extract_json_object(full)
    if decision is None:
        return {
            "decision": "reject",
            "reason": f"reviewer returned non-JSON output: {full[:200]}",
            "edits": [],
            "learned_pattern": None,
        }

    # Apply learned pattern to curator memory
    lp = decision.get("learned_pattern")
    if lp and isinstance(lp, dict) and lp.get("pattern"):
        try:
            append_learned_pattern(lp["pattern"], lp.get("kind", "signal"))
        except Exception as e:
            print(f"[reviewer] failed to append learned pattern: {e}")

    return decision


def _extract_text(message) -> str | None:
    if hasattr(message, "content") and isinstance(message.content, list):
        parts = []
        for block in message.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts) if parts else None
    if hasattr(message, "text"):
        return message.text
    return None


def _extract_json_object(text: str) -> dict | None:
    """Find the first top-level JSON object in the text."""
    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: find first { ... } matching braces
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None
```

- [ ] **Step 2: Commit (no tests — this talks to live Claude, covered by routes test)**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/wiki_engine/reviewer.py
git commit -m "feat(wiki): reviewer subagent that emits signal/noise decisions"
```

---

## Task 6: Process-pending runner

**Files:**
- Modify: `apps/api/wiki_engine/reviewer.py` (add batch runner)

- [ ] **Step 1: Append process_pending to reviewer.py**

Add this function to the bottom of `wiki_engine/reviewer.py`:

```python
async def process_pending(max_items: int = 20) -> dict:
    """Pop pending proposals one at a time, review each, apply edits.

    Returns a summary dict: {processed, approved, rejected, errors}.
    """
    from wiki_engine.queue import list_pending, pop_pending
    from wiki_engine.mutator import apply_edit, append_to_log, EditOp
    from wiki_engine.audit import log_approved, log_rejected

    summary = {"processed": 0, "approved": 0, "rejected": 0, "errors": 0}

    pending = list_pending()[:max_items]
    for prop in pending:
        try:
            decision = await review_proposal(prop)
        except Exception as e:
            print(f"[reviewer] fatal review error on {prop.id}: {e}")
            summary["errors"] += 1
            continue

        pop_pending(prop.id)
        summary["processed"] += 1

        if decision.get("decision") == "approve":
            edits = decision.get("edits", [])
            applied_dicts: list[dict] = []
            for edit_dict in edits:
                try:
                    op = EditOp(
                        action=edit_dict.get("action", "create"),
                        page_type=edit_dict.get("page_type", "entity"),
                        slug=edit_dict.get("slug", "unknown"),
                        frontmatter=edit_dict.get("frontmatter", {}),
                        body=edit_dict.get("body", ""),
                    )
                    apply_edit(op)
                    applied_dicts.append(edit_dict)
                except Exception as e:
                    print(f"[reviewer] failed edit for {prop.id}: {e}")
                    summary["errors"] += 1
            if applied_dicts:
                log_approved(
                    proposal_id=prop.id,
                    reason=decision.get("reason", ""),
                    edits=applied_dicts,
                )
                summary["approved"] += 1
                append_to_log(
                    f"approved | {prop.source} | {prop.agent_id} | "
                    f"{decision.get('reason', '')[:80]}"
                )
            else:
                # Approved but no edits actually applied → treat as rejection
                log_rejected(
                    proposal_id=prop.id,
                    reason="approved but all edits failed to apply",
                )
                summary["rejected"] += 1
        else:
            log_rejected(
                proposal_id=prop.id,
                reason=decision.get("reason", "no reason given"),
            )
            summary["rejected"] += 1

    return summary
```

- [ ] **Step 2: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/wiki_engine/reviewer.py
git commit -m "feat(wiki): process_pending batch runner"
```

---

## Task 7: API routes — /memory/propose + /wiki/status

**Files:**
- Create: `apps/api/routes/wiki.py`
- Modify: `apps/api/main.py`
- Create: `apps/api/tests/test_wiki_routes.py`

- [ ] **Step 1: Write failing test**

Write to `borina-mesh/apps/api/tests/test_wiki_routes.py`:

```python
import pytest
from fastapi.testclient import TestClient
import os

# Set vault BEFORE importing the app so lifespan sees it
os.environ["OBSIDIAN_VAULT_PATH"] = "/tmp/borina-test-vault"

import agents.ceo  # noqa
import agents.scout  # noqa
import agents.polymarket  # noqa
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
from main import app

client = TestClient(app)


def test_propose_creates_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.post(
        "/memory/propose",
        json={
            "source": "test",
            "agent_id": "ceo",
            "prompt": "test prompt",
            "content": "test content",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["queued"] is True


def test_propose_requires_content(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.post(
        "/memory/propose",
        json={"source": "test", "agent_id": "ceo", "prompt": "p"},
    )
    assert response.status_code in (400, 422)


def test_wiki_status(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    response = client.get("/wiki/status")
    assert response.status_code == 200
    data = response.json()
    assert "pending_count" in data
    assert "vault_root" in data
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_wiki_routes.py -v
```

- [ ] **Step 3: Write routes/wiki.py**

```python
"""Wiki engine HTTP routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wiki_engine.queue import enqueue_proposal, list_pending
from wiki_engine.paths import vault_root


router = APIRouter(tags=["wiki"])


class ProposalIn(BaseModel):
    source: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


@router.post("/memory/propose")
async def propose_memory(body: ProposalIn):
    """Submit a proposal to be reviewed. Returns queued id."""
    try:
        pid = enqueue_proposal(
            source=body.source,
            agent_id=body.agent_id,
            prompt=body.prompt,
            content=body.content,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"id": pid, "queued": True}


@router.get("/wiki/status")
async def wiki_status():
    """Return current engine state."""
    try:
        root = vault_root()
    except RuntimeError:
        return {"vault_root": None, "pending_count": 0, "configured": False}

    pending = list_pending()
    return {
        "configured": True,
        "vault_root": str(root),
        "pending_count": len(pending),
        "pending_sample": [
            {"id": p.id, "source": p.source, "agent_id": p.agent_id}
            for p in pending[:5]
        ],
    }


@router.post("/wiki/review")
async def trigger_review(max_items: int = 20):
    """Manually trigger a batch review run."""
    from wiki_engine.reviewer import process_pending
    summary = await process_pending(max_items=max_items)
    return summary
```

- [ ] **Step 4: Mount in main.py**

Add to `apps/api/main.py`:
```python
from routes import wiki as wiki_routes
# ...
app.include_router(wiki_routes.router)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_wiki_routes.py -v
```
Expected: 3 pass

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/routes/wiki.py apps/api/main.py apps/api/tests/test_wiki_routes.py
git commit -m "feat(wiki): POST /memory/propose + GET /wiki/status + POST /wiki/review"
```

---

## Task 8: Curator Agent (Borina-registered)

**Files:**
- Create: `apps/api/agents/curator.py`
- Modify: `apps/api/main.py`
- Modify: `apps/api/scheduler.py`

- [ ] **Step 1: Write curator.py**

```python
"""Curator Agent — runs the reviewer on pending proposals.

Registered as a Borina agent so it appears in the dashboard and can be
triggered manually or on schedule. Overrides stream() to call the
wiki_engine reviewer instead of running a generic Claude prompt.
"""

from typing import AsyncIterator
from agents.base import Agent, registry


class CuratorAgent(Agent):
    id = "curator"
    name = "Curator"
    emoji = "\U0001F4DA"  # books
    tagline = "Reviews pending memory proposals and curates the wiki"
    system_prompt = """You are the Curator agent. You review pending memory
proposals from other agents and sessions, decide signal vs noise, and apply
approved edits to the wiki. You do this by running the wiki_engine's
process_pending batch runner."""
    tools = ["wiki_engine"]
    model = "claude-opus-4-6"

    async def stream(self, prompt: str, job_id: int | None = None) -> AsyncIterator[dict]:
        """Run the wiki_engine reviewer on all pending proposals."""
        from events import bus, ActivityEvent
        from wiki_engine.reviewer import process_pending

        await bus.publish(ActivityEvent(
            agent_id=self.id,
            kind="started",
            message="Curator reviewing pending proposals",
            job_id=job_id,
        ))

        yield {"type": "text", "content": "Curator: processing pending proposals...\n"}

        try:
            summary = await process_pending(max_items=50)
        except Exception as e:
            yield {"type": "error", "content": f"Curator error: {e}"}
            await bus.publish(ActivityEvent(
                agent_id=self.id, kind="failed",
                message=f"Curator failed: {e}", job_id=job_id,
            ))
            yield {"type": "done", "content": ""}
            return

        report = (
            f"Processed: {summary['processed']}\n"
            f"Approved:  {summary['approved']}\n"
            f"Rejected:  {summary['rejected']}\n"
            f"Errors:    {summary['errors']}\n"
        )
        yield {"type": "text", "content": report}

        await bus.publish(ActivityEvent(
            agent_id=self.id,
            kind="completed",
            message=f"Curator: {summary['approved']} approved, {summary['rejected']} rejected",
            job_id=job_id,
        ))
        yield {"type": "done", "content": ""}


registry.register(CuratorAgent)
```

- [ ] **Step 2: Import in main.py**

Add to `apps/api/main.py` imports:
```python
import agents.curator  # noqa
```

- [ ] **Step 3: Add curator to default schedules**

In `apps/api/scheduler.py`, inside `register_defaults()`, add:
```python
        "curator":           "*/30 * * * *",  # Every 30 min — wiki reviewer sweep
```

- [ ] **Step 4: Run backend tests**

```bash
python -m pytest tests/ -v
```
Expected: all prior tests still passing + new ones

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/agents/curator.py apps/api/main.py apps/api/scheduler.py
git commit -m "feat(wiki): Curator agent + 30-min scheduled review sweeps"
```

---

## Task 9: Wire Borina's save_run_output through the queue

**Files:**
- Modify: `apps/api/artifacts.py`

- [ ] **Step 1: Update save_run_output to also propose to queue**

In `apps/api/artifacts.py`, modify `save_run_output` so that AFTER writing the file, it also enqueues a proposal to the wiki engine (unless the agent is the curator itself — to avoid infinite loops).

Add this near the bottom of `save_run_output`, right before `return pdf_path`:

```python
    # Also propose this run to the wiki engine (unless it IS the curator)
    if agent_id != "curator":
        try:
            from wiki_engine.queue import enqueue_proposal
            enqueue_proposal(
                source=f"borina:{agent_id}",
                agent_id=agent_id,
                prompt=prompt,
                content=output,
            )
        except RuntimeError:
            # Vault not configured — silently skip
            pass
        except Exception as e:
            print(f"[artifacts] failed to enqueue proposal: {e}")
```

- [ ] **Step 2: Run all tests**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 3: Commit + push**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/artifacts.py
git commit -m "feat(wiki): Borina agents auto-propose runs to the wiki queue

Every completed agent run (except curator itself) enqueues a memory proposal
alongside the existing PDF file write. The curator picks it up on the next
sweep and decides signal vs noise.
"
git push origin main
```

---

## Task 10: Bootstrap 00-schema.md on first startup

**Files:**
- Modify: `apps/api/main.py`
- Modify: `apps/api/wiki_engine/paths.py`

- [ ] **Step 1: Add bootstrap_schema function to paths.py**

Append to `wiki_engine/paths.py`:

```python
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
```

- [ ] **Step 2: Call from main.py lifespan**

In `apps/api/main.py`, inside `lifespan` function, after `init_db()`, add:

```python
    try:
        from wiki_engine.paths import bootstrap_schema_file, ensure_vault_layout
        ensure_vault_layout()
        bootstrap_schema_file()
        # Bootstrap curator memory file too
        from wiki_engine.curator_memory import read_curator_memory
        read_curator_memory()  # side effect: writes initial file if missing
    except RuntimeError:
        print("[wiki] OBSIDIAN_VAULT_PATH not set — wiki engine disabled")
    except Exception as e:
        print(f"[wiki] bootstrap error: {e}")
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 4: Commit + push**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/borina-mesh
git add apps/api/wiki_engine/paths.py apps/api/main.py
git commit -m "feat(wiki): bootstrap schema + curator memory on API startup"
git push origin main
```
