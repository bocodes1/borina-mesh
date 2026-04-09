"""Apply approved edits to wiki v2 category directories."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_engine.paths import (
    vault_root, ensure_vault_layout,
    TRADING_DIR, ECOMMERCE_DIR, BUSINESS_DIR, INFRASTRUCTURE_DIR, LESSONS_DIR,
    LOG_FILE,
)
from wiki_engine.schema import parse_page, serialize_page, WikiPage


DIR_BY_CATEGORY = {
    "trading": TRADING_DIR,
    "ecommerce": ECOMMERCE_DIR,
    "business": BUSINESS_DIR,
    "infrastructure": INFRASTRUCTURE_DIR,
    "lessons": LESSONS_DIR,
}


@dataclass
class EditOp:
    action: str          # "create" | "append"
    category: str        # one of the 5 categories
    slug: str            # kebab-case slug
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""


def _page_path(category: str, slug: str) -> Path:
    root = ensure_vault_layout()
    sub = DIR_BY_CATEGORY.get(category)
    if sub is None:
        raise ValueError(f"unknown category: {category}")
    safe_slug = slug.strip().lower().replace(" ", "-").replace("/", "-")
    return root / sub / f"{safe_slug}.md"


def apply_edit(edit: EditOp) -> Path:
    """Apply a single edit op to the wiki. Returns the affected file path."""
    path = _page_path(edit.category, edit.slug)
    path.parent.mkdir(parents=True, exist_ok=True)

    if edit.action == "create":
        page = WikiPage(frontmatter=edit.frontmatter, body=edit.body)
        path.write_text(serialize_page(page), encoding="utf-8")
    elif edit.action == "append":
        if path.exists():
            current = parse_page(path.read_text(encoding="utf-8"))
            current.body = (current.body.rstrip() + "\n\n" + edit.body).lstrip()
            current.frontmatter["updated"] = datetime.utcnow().strftime("%Y-%m-%d")
            if edit.frontmatter:
                for k, v in edit.frontmatter.items():
                    if k != "created":
                        current.frontmatter[k] = v
            path.write_text(serialize_page(current), encoding="utf-8")
        else:
            # Append-to-missing == create
            page = WikiPage(frontmatter=edit.frontmatter, body=edit.body)
            path.write_text(serialize_page(page), encoding="utf-8")
    else:
        raise ValueError(f"unknown action: {edit.action}")

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
