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
