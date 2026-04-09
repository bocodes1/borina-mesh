"""Wiki v2 reviewer — single-shot synchronous reviewer.

Uses Sonnet 4.6 via Claude Agent SDK subprocess mode. Reads curator memory
before every call. Default decision is REJECT. Outputs a JSON decision that
the caller applies via the mutator.
"""

import json
import re
from datetime import date
from typing import AsyncIterator

from wiki_engine.curator_memory import read_curator_memory
from wiki_engine.audit import log_approved, log_rejected


REVIEWER_SYSTEM_PROMPT = """You are the Borina Wiki v2 Reviewer. Your job is to
decide whether a candidate memory item should be written to the user's vault.

## The 5 Categories

1. **trading** — Polymarket bot strategies, paper-trade results with numbers,
   whale wallet moves, leaderboard profiles, resolution-rule edges, strategy
   decisions with money impact.

2. **ecommerce** — Refined Concept decisions, KaloData product finds with GMV
   numbers, Meta Ad Library observations, Google Ads tuning, Shopify insights,
   competitor teardowns.

3. **business** — Money-impact decisions (pricing, budgets, ad spend, pivots)
   with rationale. Partnerships. Financial facts.

4. **infrastructure** — Non-obvious configs: IPs, endpoints, credential
   locations, cron schedules, service dependencies.

5. **lessons** — Abstracted gotchas with pattern + fix. Things that cost real
   time or money to learn.

## Default Decision: REJECT

You MUST default to REJECT unless the content CLEARLY matches one of the five
categories AND provides signal that is NOT recoverable from git log, CI logs,
code comments, or a 5-minute inspection of the running system.

When in doubt, REJECT.

## Hard Rejects (Never Approve These)

- Code fix / bug fix narratives (line counts, function names, file paths in
  a fix description) — ALWAYS recoverable from git log
- Test pass/fail counts ("35/35 tests passing")
- Commit / push / deploy announcements
- Session progress summaries ("completed Task 5", "in this session we did X")
- Build status / "auto-updater picked up the change"
- Tool invocation traces (debug logs from running the system)
- Install / setup commands (unless describing a non-obvious gotcha)
- Version numbers / upgrade notes (unless critical compatibility decision)
- Meta-commentary about the wiki itself

## Output Format

You MUST output a single JSON object and nothing else:

```json
{
  "decision": "approve" | "reject",
  "category": "trading" | "ecommerce" | "business" | "infrastructure" | "lessons" | null,
  "reason": "one-sentence rationale",
  "page": {
    "slug": "kebab-case-slug",
    "title": "Human readable title",
    "confidence": "low" | "medium" | "high" | "confirmed",
    "body": "# Title\\n\\nMarkdown body with [[wikilinks]] and concrete data."
  }
}
```

Rules:
- If decision is "reject", omit the "page" field and set "category" to null.
- If decision is "approve", "category" and "page" are required.
- The page body must be WRITTEN FRESH — not the raw input content. Extract the
  signal, reshape it into a proper wiki page with a clear title, sections, and
  cross-references to related pages via [[wikilinks]].
- Use specific numbers and dates where they exist in the input.
- NEVER include line numbers, file paths, or commit SHAs in the page body.
- NEVER approve noise with a "it could be useful later" rationale.
"""


async def review_one(content: str, prompt_context: str, source: str) -> dict:
    """Review a single candidate item and return a decision dict.

    Uses Sonnet 4.6 via Claude Agent SDK subprocess mode.
    """
    curator_memory = read_curator_memory()

    user_message = f"""## Curator Memory (learned rejection examples)

{curator_memory}

---

## Candidate to Review

**Source:** {source}
**Context/prompt:** {prompt_context}

### Content

{content}

---

Output ONLY the JSON decision object. Apply the default-reject rule strictly.
Today's date is {date.today().isoformat()}."""

    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except ImportError:
        return _reject("claude-agent-sdk not installed")

    options = ClaudeAgentOptions(
        system_prompt=REVIEWER_SYSTEM_PROMPT,
        model="claude-sonnet-4-6",
    )

    buffer_parts: list[str] = []
    try:
        async for message in query(prompt=user_message, options=options):
            text = _extract_text(message)
            if text:
                buffer_parts.append(text)
    except Exception as e:
        return _reject(f"reviewer error: {e}")

    full = "".join(buffer_parts).strip()
    decision = _extract_json_object(full)
    if decision is None:
        return _reject(f"reviewer returned non-JSON: {full[:200]}")
    return decision


async def review_batch(items: list[dict]) -> dict:
    """Review a batch of items from a session proposal. Each item is a dict
    with content/context/source/id. Returns a summary dict."""
    import asyncio
    from wiki_engine.mutator import apply_edit, append_to_log, EditOp

    summary = {
        "total": len(items),
        "approved": 0,
        "rejected": 0,
        "errors": 0,
        "decisions": [],
    }

    # Review all items in parallel (up to 5 at a time to avoid overloading)
    sem = asyncio.Semaphore(5)

    async def _review(item):
        async with sem:
            try:
                return await review_one(
                    content=item.get("content", ""),
                    prompt_context=item.get("prompt", ""),
                    source=item.get("source", "unknown"),
                )
            except Exception as e:
                return {"decision": "reject", "category": None, "reason": f"exception: {e}"}

    results = await asyncio.gather(*[_review(item) for item in items])

    today = date.today().isoformat()

    for item, decision in zip(items, results):
        item_id = item.get("id", "unknown")
        if decision.get("decision") == "approve":
            page = decision.get("page", {})
            category = decision.get("category")
            if not page or not category:
                log_rejected(
                    proposal_id=item_id,
                    reason="approved but missing category or page",
                )
                summary["rejected"] += 1
                continue

            try:
                op = EditOp(
                    action="create",
                    category=category,
                    slug=page.get("slug", "untitled"),
                    frontmatter={
                        "category": category,
                        "title": page.get("title", "Untitled"),
                        "created": today,
                        "updated": today,
                        "confidence": page.get("confidence", "medium"),
                    },
                    body=page.get("body", ""),
                )
                applied_path = apply_edit(op)
                log_approved(
                    proposal_id=item_id,
                    reason=decision.get("reason", ""),
                    edits=[{
                        "action": "create",
                        "category": category,
                        "slug": op.slug,
                    }],
                )
                append_to_log(
                    f"approved | {item.get('source', '?')} | {category} | "
                    f"{op.slug} — {decision.get('reason', '')[:60]}"
                )
                summary["approved"] += 1
                summary["decisions"].append({
                    "id": item_id,
                    "decision": "approve",
                    "category": category,
                    "path": str(applied_path),
                })
            except Exception as e:
                log_rejected(
                    proposal_id=item_id,
                    reason=f"failed to apply edit: {e}",
                )
                summary["errors"] += 1
        else:
            log_rejected(
                proposal_id=item_id,
                reason=decision.get("reason", "no reason given"),
            )
            summary["rejected"] += 1
            summary["decisions"].append({
                "id": item_id,
                "decision": "reject",
                "reason": decision.get("reason", ""),
            })

    return summary


def _reject(reason: str) -> dict:
    return {"decision": "reject", "category": None, "reason": reason}


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
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

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
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None
