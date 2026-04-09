"""Apply approved edits to wiki v2 subcategory files with lifecycle management."""

import re
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

from wiki_engine.paths import (
    vault_root, ensure_vault_layout,
    LOG_FILE,
)
from wiki_engine.schema import SUBCATEGORY_FILES


@dataclass
class EditOp:
    action: str          # "append" | "retire" | "create" (legacy)
    category: str        # one of the 5 categories
    subcategory: str = ""    # e.g. "strategies", "metrics", "products"
    title: str = ""          # entry title (H3)
    body: str = ""       # markdown content (for append)
    status: str = "ACTIVE"   # ACTIVE or RETIRED
    retire_reason: str = ""  # why it was retired (for retire action)
    # Legacy fields kept for backward compatibility with v2.0 "create" action
    slug: str = ""
    frontmatter: dict[str, Any] = field(default_factory=dict)


def _subcategory_path(category: str, subcategory: str) -> Path:
    """Resolve the file path for a given category + subcategory."""
    root = ensure_vault_layout()
    cat_files = SUBCATEGORY_FILES.get(category)
    if cat_files is None:
        raise ValueError(f"unknown category: {category}")
    rel_path = cat_files.get(subcategory)
    if rel_path is None:
        raise ValueError(f"unknown subcategory '{subcategory}' for category '{category}'")
    return root / rel_path


def _find_active_section_end(lines: list[str]) -> int:
    """Return the line index where content should be inserted before ## Retired."""
    retired_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Retired":
            retired_idx = i
            break
    if retired_idx is not None:
        # Insert before the ## Retired section (with blank line)
        return retired_idx
    return len(lines)


def _build_entry(title: str, body: str, status: str, retire_reason: str = "") -> str:
    """Build a formatted entry block."""
    if status == "RETIRED" and retire_reason:
        status_line = f"**Status: RETIRED — {retire_reason}**"
    elif status == "RETIRED":
        status_line = "**Status: RETIRED**"
    else:
        status_line = "**Status: ACTIVE**"

    lines = [f"### {title}", "", status_line, ""]
    if body.strip():
        lines.append(body.strip())
        lines.append("")
    return "\n".join(lines)


def apply_edit(edit: EditOp) -> Path:
    """Apply a single edit op to the wiki. Returns the affected file path."""

    # Handle legacy "create" action for backward compatibility
    if edit.action == "create":
        return _legacy_create(edit)

    if edit.action == "append":
        return _apply_append(edit)
    elif edit.action == "retire":
        return _apply_retire(edit)
    else:
        raise ValueError(f"unknown action: {edit.action}")


def _apply_append(edit: EditOp) -> Path:
    """Append an entry under today's date header in the Active section."""
    path = _subcategory_path(edit.category, edit.subcategory)
    path.parent.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    date_header = f"## {today}"
    entry_block = _build_entry(edit.title, edit.body, edit.status, edit.retire_reason)

    if not path.exists():
        raise FileNotFoundError(
            f"Subcategory file does not exist: {path}. "
            "Run bootstrap_subcategory_files() first."
        )

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    # Find the ## Active section
    active_section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Active":
            active_section_idx = i
            break

    if active_section_idx is None:
        # No ## Active section found — just append at end before ## Retired
        retired_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "## Retired":
                retired_idx = i
                break
        insert_at = retired_idx if retired_idx is not None else len(lines)
    else:
        # Look for today's date header within the Active section
        insert_at = None
        retired_idx = None
        for i in range(active_section_idx + 1, len(lines)):
            if lines[i].strip() == "## Retired":
                retired_idx = i
                break
            if lines[i].strip() == date_header:
                # Found today's date header — insert after it (and any blank lines)
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                insert_at = j
                break
        if insert_at is None:
            # No date header for today — insert one right after ## Active
            insert_at = active_section_idx + 1
            entry_block = f"\n{date_header}\n\n{entry_block}"

    # Build new content
    before = "".join(lines[:insert_at])
    after = "".join(lines[insert_at:])

    if insert_at == active_section_idx + 1 and entry_block.startswith(f"\n{date_header}"):
        # Already prefixed with date header
        new_content = before + entry_block + "\n" + after
    else:
        new_content = before + entry_block + "\n" + after

    # Update frontmatter updated date if present
    new_content = _update_frontmatter_date(new_content, today)
    path.write_text(new_content, encoding="utf-8")
    return path


def _apply_retire(edit: EditOp) -> Path:
    """Find an entry by title, mark it RETIRED, move to ## Retired section."""
    path = _subcategory_path(edit.category, edit.subcategory)
    if not path.exists():
        raise FileNotFoundError(f"Subcategory file does not exist: {path}")

    content = path.read_text(encoding="utf-8")
    title_pattern = re.compile(r"^### " + re.escape(edit.title) + r"\s*$", re.MULTILINE)
    match = title_pattern.search(content)
    if not match:
        raise ValueError(f"Entry titled '{edit.title}' not found in {path}")

    # Find the entry block: from ### Title to next ### or ## or end
    entry_start = match.start()
    rest = content[entry_start:]
    # Find end of this entry
    next_section = re.search(r"\n(?:#{2,3} )", rest[1:])
    if next_section:
        entry_end = entry_start + 1 + next_section.start()
    else:
        entry_end = len(content)

    entry_block = content[entry_start:entry_end]

    # Replace ACTIVE status with RETIRED in the entry block
    retired_block = re.sub(
        r"\*\*Status: ACTIVE\*\*",
        f"**Status: RETIRED — {edit.retire_reason}**" if edit.retire_reason else "**Status: RETIRED**",
        entry_block,
    )

    # Remove from original location
    content_without_entry = content[:entry_start] + content[entry_end:]
    content_without_entry = content_without_entry.rstrip() + "\n"

    # Find or create ## Retired section
    retired_section_match = re.search(r"^## Retired\s*$", content_without_entry, re.MULTILINE)
    if retired_section_match:
        insert_pos = retired_section_match.end()
        new_content = (
            content_without_entry[:insert_pos]
            + "\n\n"
            + retired_block.strip()
            + "\n"
            + content_without_entry[insert_pos:]
        )
    else:
        new_content = content_without_entry.rstrip() + "\n\n## Retired\n\n" + retired_block.strip() + "\n"

    today = date.today().isoformat()
    new_content = _update_frontmatter_date(new_content, today)
    path.write_text(new_content, encoding="utf-8")
    return path


def _update_frontmatter_date(content: str, today: str) -> str:
    """Update the 'updated:' field in YAML frontmatter if present."""
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            header = content[4:end]
            new_header = re.sub(r"^updated:.*$", f"updated: {today}", header, flags=re.MULTILINE)
            return "---\n" + new_header + content[end:]
    return content


def _legacy_create(edit: EditOp) -> Path:
    """Legacy create action — write a page directly by slug (v2.0 compatibility)."""
    from wiki_engine.paths import TRADING_DIR, ECOMMERCE_DIR, BUSINESS_DIR, INFRASTRUCTURE_DIR, LESSONS_DIR
    from wiki_engine.schema import parse_page, serialize_page, WikiPage

    DIR_BY_CATEGORY = {
        "trading": TRADING_DIR,
        "ecommerce": ECOMMERCE_DIR,
        "business": BUSINESS_DIR,
        "infrastructure": INFRASTRUCTURE_DIR,
        "lessons": LESSONS_DIR,
    }

    root = ensure_vault_layout()
    sub = DIR_BY_CATEGORY.get(edit.category)
    if sub is None:
        raise ValueError(f"unknown category: {edit.category}")

    safe_slug = edit.slug.strip().lower().replace(" ", "-").replace("/", "-") if edit.slug else "untitled"
    path = root / sub / f"{safe_slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    page = WikiPage(frontmatter=edit.frontmatter, body=edit.body)
    path.write_text(serialize_page(page), encoding="utf-8")
    return path


def append_to_log(message: str) -> None:
    """Append a line to log.md with timestamp prefix."""
    root = ensure_vault_layout()
    log_path = root / LOG_FILE
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    line = f"- [{ts}] {message}\n"
    if log_path.exists():
        log_path.write_text(log_path.read_text(encoding="utf-8").rstrip() + "\n" + line, encoding="utf-8")
    else:
        log_path.write_text(f"# Activity Log\n\n{line}", encoding="utf-8")
