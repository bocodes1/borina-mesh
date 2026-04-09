# Wiki Engine — Phase B Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** A Claude Code skill that fires on Stop hook and POSTs the session's work summary to the Borina API (`/memory/propose`), so PC and Mac Mini Claude Code sessions go through the same reviewer as Borina agents.

**Architecture:** Single skill at `~/.claude/skills/wiki-proposer/SKILL.md` + a small Python helper script that captures recent session context and posts it to the Borina API URL. Registered as a Stop hook in Claude Code settings.

**Tech Stack:** Python stdlib only (urllib for HTTP). No new dependencies.

---

## Task 1: Create the skill file

**Files:**
- Create: `~/.claude/skills/wiki-proposer/SKILL.md`
- Create: `~/.claude/skills/wiki-proposer/propose.py`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p ~/.claude/skills/wiki-proposer
```

(On Windows bash: `mkdir -p /c/Users/wenbo/.claude/skills/wiki-proposer`)

- [ ] **Step 2: Write SKILL.md**

Write to `/c/Users/wenbo/.claude/skills/wiki-proposer/SKILL.md`:

```markdown
---
name: wiki-proposer
description: Submit session work to the Borina wiki engine for curation. Fires automatically at session end via Stop hook, or can be invoked manually when you want the reviewer to consider the current session's findings. Use when user says "propose this to wiki", "send to curator", or at session end.
---

# Wiki Proposer

Submits session work to the Borina wiki engine at `/memory/propose` for review by the Curator subagent. The Curator decides signal vs noise and applies approved edits to the Obsidian vault.

## When to Invoke

- **Automatically on session end** (Stop hook — configured in `~/.claude/settings.json`)
- **Manually** when the user asks for the current session's work to be curated

## What Gets Submitted

A short, high-signal summary of the session:
- What was decided (decisions, trade-offs)
- What was learned (lessons, gotchas)
- What changed (files created/modified, new entities, new concepts)
- NOT included: routine tool output, build logs, "tests passed", "committed", etc.

## Execution

Run `propose.py` passing a JSON payload via stdin or as an argument. The script POSTs to the Borina API and logs the response.

### Default endpoint

The script reads `BORINA_API_URL` from environment (defaults to `http://100.116.121.128:8000`). Override by setting the env var in `~/.claude/settings.json` or shell profile.

### Manual invocation

When the user asks "submit this session to wiki":
1. Write a short summary markdown (3-10 bullet points, focused on signal only)
2. Run: `python ~/.claude/skills/wiki-proposer/propose.py --source "claude-code:pc" --prompt "session summary" --content "[the summary markdown]"`
3. Report the queued proposal ID back to the user

### Hook invocation (automatic)

When Stop hook fires, the skill has ~30 seconds before Claude Code exits. The script runs non-interactively with the session transcript location available via the `CLAUDE_TRANSCRIPT_PATH` environment variable (set by Claude Code).

1. Read the transcript
2. Extract decisions / lessons / entity changes (skip routine output)
3. POST to `/memory/propose`
4. Exit silently

## Output Contract

The skill does NOT modify the wiki directly. It only queues proposals. The reviewer on the Borina API decides what happens next and updates the wiki within its next sweep (every 30 min, or triggered manually via `/wiki/review`).

## Failure Modes

- **Borina API unreachable:** log warning to `~/.claude/skills/wiki-proposer/errors.log`, exit 0 (don't block session stop)
- **Invalid payload:** log error, exit 0
- **Network timeout:** 10s timeout, log warning, exit 0

Never fail the session stop — always exit 0.
```

- [ ] **Step 3: Write propose.py helper**

Write to `/c/Users/wenbo/.claude/skills/wiki-proposer/propose.py`:

```python
#!/usr/bin/env python3
"""Submit a proposal to the Borina wiki engine via /memory/propose.

Can be invoked two ways:
1. CLI args: --source X --prompt Y --content Z
2. Stop hook: reads CLAUDE_TRANSCRIPT_PATH env var, extracts summary, posts

Always exits 0 so session stop isn't blocked.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

DEFAULT_API_URL = "http://100.116.121.128:8000"
TIMEOUT_SECONDS = 10
ERROR_LOG = Path.home() / ".claude" / "skills" / "wiki-proposer" / "errors.log"


def log_error(msg: str) -> None:
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ERROR_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] {msg}\n")


def post_proposal(api_url: str, payload: dict) -> dict | None:
    """POST to /memory/propose. Returns response dict or None on failure."""
    req = urllib.request.Request(
        f"{api_url}/memory/propose",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        log_error(f"URLError: {e}")
        return None
    except Exception as e:
        log_error(f"unexpected: {e}")
        return None


def extract_from_transcript(transcript_path: Path) -> str:
    """Pull a short summary from a Claude Code transcript file.

    The transcript is a JSONL file with user/assistant messages. We concatenate
    the last N assistant messages' text content and cap at ~4000 chars. The
    reviewer will decide what's signal vs noise — our job is just to ship a
    reasonable candidate.
    """
    if not transcript_path.exists():
        return ""

    try:
        lines = transcript_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        log_error(f"transcript read failed: {e}")
        return ""

    assistant_texts: list[str] = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("role") == "assistant":
            content = rec.get("content")
            if isinstance(content, str):
                assistant_texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        assistant_texts.append(block.get("text", ""))
        if len(assistant_texts) >= 10:
            break

    joined = "\n\n---\n\n".join(reversed(assistant_texts))
    return joined[:4000]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=None)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--content", default=None)
    parser.add_argument("--api-url", default=os.environ.get("BORINA_API_URL", DEFAULT_API_URL))
    args = parser.parse_args()

    source = args.source or os.environ.get("WIKI_SOURCE", "claude-code")
    prompt = args.prompt or "Session summary"
    content = args.content

    if content is None:
        transcript_path_raw = os.environ.get("CLAUDE_TRANSCRIPT_PATH", "")
        if transcript_path_raw:
            content = extract_from_transcript(Path(transcript_path_raw))

    if not content:
        log_error("no content to propose (no --content arg, no transcript)")
        return 0

    payload = {
        "source": source,
        "agent_id": "claude-code",
        "prompt": prompt[:500],
        "content": content[:20000],
    }

    result = post_proposal(args.api_url, payload)
    if result is None:
        log_error("post failed (see above)")
    else:
        print(f"wiki-proposer: queued {result.get('id', 'unknown')}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make executable (Unix only, harmless on Windows)**

```bash
chmod +x ~/.claude/skills/wiki-proposer/propose.py 2>/dev/null || true
```

---

## Task 2: Register Stop hook in settings.json

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Read current settings**

```bash
cat ~/.claude/settings.json
```
(Or `/c/Users/wenbo/.claude/settings.json` on Windows bash.)

- [ ] **Step 2: Add a Stop hook that runs propose.py**

In `~/.claude/settings.json`, under the `hooks` section, add (or merge into existing) a Stop entry. The hook command is:

```
python /c/Users/wenbo/.claude/skills/wiki-proposer/propose.py --source "claude-code:$(hostname)"
```

Mac equivalent:
```
python3 ~/.claude/skills/wiki-proposer/propose.py --source "claude-code:$(hostname)"
```

The exact JSON patch depends on current file. Example final structure:

```json
{
  "hooks": {
    "Stop": "python /c/Users/wenbo/.claude/skills/wiki-proposer/propose.py --source \"claude-code:$(hostname)\""
  }
}
```

If a Stop hook already exists (e.g., for obsidian-memory-sync), CHAIN them with `&&` or run both: `existing_command && python ... propose.py ...`.

- [ ] **Step 3: Test manually**

```bash
BORINA_API_URL=http://100.116.121.128:8000 python /c/Users/wenbo/.claude/skills/wiki-proposer/propose.py --source test-manual --prompt "manual test" --content "This is a manual test proposal from Phase B installation."
```
Expected: prints `wiki-proposer: queued <id>` on stderr, no error. Check the vault at `_queue/pending/` for a new `.json` file.

- [ ] **Step 4: Verify errors.log is empty** (unless there were real errors)

```bash
cat ~/.claude/skills/wiki-proposer/errors.log 2>/dev/null || echo "no errors"
```
