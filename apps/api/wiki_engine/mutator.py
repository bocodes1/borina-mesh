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
