"""Apply approved edits to wiki v3 — individual pages per entry + category index hubs."""

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


def _make_slug(title: str, existing_slugs: set[str] | None = None) -> str:
    """Convert a title to a kebab-case slug, max 50 chars, deduped."""
    # lowercase, replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:50].rstrip("-")
    if not slug:
        slug = "untitled"
    if existing_slugs is None:
        return slug
    # deduplicate
    candidate = slug
    n = 2
    while candidate in existing_slugs:
        suffix = f"-{n}"
        candidate = slug[: 50 - len(suffix)] + suffix
        n += 1
    return candidate


def _category_dir(category: str) -> str:
    """Map category name to directory name (they're the same in v3)."""
    dirs = {
        "trading": "trading",
        "ecommerce": "ecommerce",
        "business": "business",
        "infrastructure": "infrastructure",
        "lessons": "lessons",
    }
    if category not in dirs:
        raise ValueError(f"unknown category: {category}")
    return dirs[category]


def _subcategory_path(category: str, subcategory: str) -> Path:
    """Resolve the _index.md path for a given category (v3: all writes go to individual pages)."""
    root = ensure_vault_layout()
    cat_files = SUBCATEGORY_FILES.get(category)
    if cat_files is None:
        raise ValueError(f"unknown category: {category}")
    if subcategory not in cat_files:
        raise ValueError(f"unknown subcategory '{subcategory}' for category '{category}'")
    # Return the category _index.md path (used for backwards-compat checks)
    cat_dir = _category_dir(category)
    return root / cat_dir / "_index.md"


def _find_active_section_end(lines: list[str]) -> int:
    """Return the line index where content should be inserted before ## Retired."""
    retired_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Retired":
            retired_idx = i
            break
    if retired_idx is not None:
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


def _build_individual_page(
    category: str,
    subcategory: str,
    title: str,
    body: str,
    status: str,
    created: str,
    updated: str,
) -> str:
    """Build a complete individual page with frontmatter, content, and Related section."""
    status_lower = status.lower()
    fm_lines = [
        "---",
        f"category: {category}",
        f'title: "{title}"',
        f"status: {status_lower}",
        f"created: {created}",
        f"updated: {updated}",
        "---",
        "",
        f"# {title}",
        "",
        f"**Status: {status}** | Created: {created}",
        "",
    ]
    if body.strip():
        fm_lines.append(body.strip())
        fm_lines.append("")
    fm_lines.extend([
        "---",
        "## Related",
        f"- [[{category}/_index|{category.title()} Hub]]",
        "",
    ])
    return "\n".join(fm_lines)


def _update_category_index(root: Path, category: str, slug: str, title: str) -> None:
    """Append a [[wikilink]] to the category _index.md for the new page."""
    index_path = root / _category_dir(category) / "_index.md"
    if not index_path.exists():
        return
    content = index_path.read_text(encoding="utf-8")
    link = f"- [[{category}/{slug}|{title}]]"
    # Insert before "## Related Categories" if present, else append
    if "## Related Categories" in content:
        content = content.replace(
            "## Related Categories",
            f"{link}\n\n## Related Categories",
        )
    else:
        content = content.rstrip() + f"\n{link}\n"
    index_path.write_text(content, encoding="utf-8")


def apply_edit(edit: EditOp) -> Path:
    """Apply a single edit op to the wiki. Returns the affected file path.

    v3 behaviour for action="append":
    - Creates a new individual .md file at {category}/{slug}.md
    - Updates the category _index.md with a new [[wikilink]]
    """

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
    """Create a new individual page file for the entry (v3 behaviour)."""
    # Validate category + subcategory
    cat_files = SUBCATEGORY_FILES.get(edit.category)
    if cat_files is None:
        raise ValueError(f"unknown category: {edit.category}")
    if edit.subcategory not in cat_files:
        raise ValueError(f"unknown subcategory '{edit.subcategory}' for category '{edit.category}'")

    root = ensure_vault_layout()
    cat_dir = _category_dir(edit.category)
    category_path = root / cat_dir
    category_path.mkdir(parents=True, exist_ok=True)

    # Collect existing slugs in this category dir to avoid collisions
    existing_slugs = {p.stem for p in category_path.glob("*.md") if p.stem != "_index"}
    slug = _make_slug(edit.title, existing_slugs)

    today = date.today().isoformat()
    page_path = category_path / f"{slug}.md"

    page_content = _build_individual_page(
        category=edit.category,
        subcategory=edit.subcategory,
        title=edit.title,
        body=edit.body,
        status=edit.status,
        created=today,
        updated=today,
    )
    page_path.write_text(page_content, encoding="utf-8")

    # Update the category _index.md
    _update_category_index(root, edit.category, slug, edit.title)

    return page_path


def _apply_retire(edit: EditOp) -> Path:
    """Find a page by title slug, mark it RETIRED in its frontmatter."""
    # Validate
    cat_files = SUBCATEGORY_FILES.get(edit.category)
    if cat_files is None:
        raise ValueError(f"unknown category: {edit.category}")
    if edit.subcategory not in cat_files:
        raise ValueError(f"unknown subcategory '{edit.subcategory}' for category '{edit.category}'")

    root = ensure_vault_layout()
    cat_dir = _category_dir(edit.category)
    category_path = root / cat_dir

    # Find the page by matching title in frontmatter or H1
    target_path = None
    for md_file in category_path.glob("*.md"):
        if md_file.stem == "_index":
            continue
        content = md_file.read_text(encoding="utf-8")
        # Check frontmatter title or H1 heading
        if f'title: "{edit.title}"' in content or f"# {edit.title}" in content:
            target_path = md_file
            break

    if target_path is None:
        raise ValueError(f"Entry titled '{edit.title}' not found in {category_path}")

    content = target_path.read_text(encoding="utf-8")
    today = date.today().isoformat()

    # Update status in frontmatter
    if edit.retire_reason:
        retired_status = f"RETIRED — {edit.retire_reason}"
    else:
        retired_status = "RETIRED"

    content = re.sub(r"^status: \w+", f"status: retired", content, flags=re.MULTILINE)
    content = re.sub(r"^updated:.*$", f"updated: {today}", content, flags=re.MULTILINE)
    # Update the Status line in the body
    content = re.sub(
        r"\*\*Status: ACTIVE\*\*",
        f"**Status: {retired_status}**",
        content,
    )
    target_path.write_text(content, encoding="utf-8")
    return target_path


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
