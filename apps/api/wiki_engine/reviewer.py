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
