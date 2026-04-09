"""Wiki v2 page schema: 5 categories + 13 subcategory files + lifecycle management."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import yaml


class Category(str, Enum):
    TRADING = "trading"
    ECOMMERCE = "ecommerce"
    BUSINESS = "business"
    INFRASTRUCTURE = "infrastructure"
    LESSONS = "lessons"


# Each category has specific subcategory files. The reviewer must append
# to the correct file, never create new files outside this list.
SUBCATEGORY_FILES = {
    "trading": {
        "strategies": "trading/strategies.md",
        "metrics": "trading/metrics.md",
        "leaderboard": "trading/leaderboard.md",
        "bot-config": "trading/bot-config.md",
    },
    "ecommerce": {
        "products": "ecommerce/products.md",
        "campaigns": "ecommerce/campaigns.md",
        "store": "ecommerce/store.md",
    },
    "business": {
        "decisions": "business/decisions.md",
        "finances": "business/finances.md",
    },
    "infrastructure": {
        "services": "infrastructure/services.md",
        "automation": "infrastructure/automation.md",
    },
    "lessons": {
        "technical": "lessons/technical.md",
        "operational": "lessons/operational.md",
    },
}

REQUIRED_FIELDS = {"category", "title", "created", "updated", "confidence"}
ALLOWED_CONFIDENCE = {"low", "medium", "high", "confirmed"}


@dataclass
class WikiPage:
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""


def validate_frontmatter(fm: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, errors). Empty errors list means valid."""
    errors: list[str] = []
    for key in REQUIRED_FIELDS:
        if key not in fm:
            errors.append(f"missing required field: {key}")

    category = fm.get("category")
    if category is not None and category not in (c.value for c in Category):
        errors.append(f"unknown category: {category}")

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
            body = text[end + 5:]
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
