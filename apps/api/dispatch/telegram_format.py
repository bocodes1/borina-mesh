"""Telegram outbound formatter (spec §4).

EVERY outbound Telegram message passes through here so replies are short,
emoji-free, left-aligned, whitespace-collapsed, MarkdownV2-escaped, and
length-capped — independent of how the model wrote them. Depth lives in the
attached PDF; the chat body is a short digest.
"""
from __future__ import annotations

import os
import re

MAX_LEN = 4096
# A completed dispatch is only allowed to expand past the line cap when a
# concrete "big task" signal fires (long artifact OR multi-section result).
BIG_TASK_CHARS = 1800


def telegram_max_lines() -> int:
    try:
        return max(1, int(os.getenv("TELEGRAM_MAX_LINES", "3")))
    except ValueError:
        return 3


def is_big_task(markdown: str) -> bool:
    """Concrete trigger (not vibes): long output, OR a structured result with
    multiple distinct sections / many items."""
    headings = len(re.findall(r"(?m)^#{1,3}\s", markdown))
    bullets = len(re.findall(r"(?m)^\s*[-*•]\s", markdown))
    return len(markdown) > BIG_TASK_CHARS or headings >= 3 or bullets >= 8


def cap_lines(text: str, max_lines: int) -> str:
    """Hard cap on line count. If exceeded, keep the first (max_lines-1) lines
    and replace the rest with a single PDF pointer."""
    lines = [ln for ln in text.split("\n") if ln != ""]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    pointer = escape_markdown_v2("(full detail in the attached PDF)")
    return "\n".join(lines[: max(1, max_lines - 1)] + [pointer])

# Emoji + pictographic + variation selectors + ZWJ.
_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # flags
    "\U0001F300-\U0001FAFF"  # symbols & pictographs, supplemental
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F000-\U0001F0FF"
    "\U00002190-\U000021FF"  # arrows
    "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # ZWJ
    "\U000024C2"
    "]+",
    flags=re.UNICODE,
)

# MarkdownV2 reserved characters.
_MDV2 = r"_*[]()~`>#+-=|{}.!\\"
_MDV2_RE = re.compile("([" + re.escape(_MDV2) + "])")


def strip_emojis(text: str) -> str:
    return _EMOJI_RE.sub("", text)


def normalize_whitespace(text: str) -> str:
    """Dedent every line to the left margin (kills weird indentation), trim
    trailing spaces, collapse 3+ blank lines to one."""
    lines = [ln.replace("\t", "    ").rstrip().lstrip() for ln in text.splitlines()]
    out: list[str] = []
    blanks = 0
    for ln in lines:
        if ln == "":
            blanks += 1
            if blanks <= 1:
                out.append("")
        else:
            blanks = 0
            out.append(ln)
    return "\n".join(out).strip()


def escape_markdown_v2(text: str) -> str:
    return _MDV2_RE.sub(r"\\\1", text)


def _escape_link(url: str) -> str:
    # Inside a MarkdownV2 link target only ) and \ must be escaped.
    return url.replace("\\", "\\\\").replace(")", "\\)")


def truncate(text: str, *, limit: int = MAX_LEN, pointer: str = "") -> str:
    if len(text) <= limit:
        return text
    tail = pointer or "\n\n\\(full detail in the attached PDF\\)"
    keep = max(0, limit - len(tail))
    return text[:keep].rstrip() + tail


def format_telegram(raw: str, *, limit: int = MAX_LEN, max_lines: int | None = None) -> str:
    """Clean + escape + line-cap an arbitrary message (acks, errors).
    MarkdownV2-safe and terse: multi-paragraph input collapses to the cap."""
    cleaned = normalize_whitespace(strip_emojis(raw))
    escaped = escape_markdown_v2(cleaned)
    capped = cap_lines(escaped, max_lines if max_lines is not None else telegram_max_lines())
    return truncate(capped, limit=limit)


def format_answer_reply(*, agent: str, markdown: str, deep_link: str = "", limit: int = MAX_LEN) -> str:
    """No-PDF chat reply: send the agent's ACTUAL answer (cleaned, escaped,
    capped to Telegram's limit), not a one-line headline. This is the DEFAULT —
    the PDF path (format_dispatch_reply) is opt-in.

    The answer already went through clean_agent_output upstream, so here we just
    normalize whitespace, strip emojis, escape MarkdownV2, and length-cap.
    """
    cleaned = normalize_whitespace(strip_emojis(markdown))
    escaped = escape_markdown_v2(cleaned)
    pointer = ""
    if deep_link:
        pointer = "\n\n" + f"[open in mesh]({_escape_link(deep_link)})"
    body = truncate(escaped, limit=max(0, limit - len(pointer)))
    return body + pointer


def _headline_and_body(markdown: str) -> tuple[str, list[str]]:
    cleaned = normalize_whitespace(strip_emojis(markdown))
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    headline = ""
    body: list[str] = []
    for ln in lines:
        stripped = re.sub(r"^[#>\-*•]+\s*", "", ln).strip()
        if not stripped:
            continue
        if not headline:
            headline = stripped
        elif len(body) < 4 and len(stripped) <= 100:
            body.append(stripped)
    return headline or "report ready", body


def format_dispatch_reply(*, agent: str, markdown: str, deep_link: str, limit: int = MAX_LEN) -> str:
    """Terse-by-default dispatch reply.

    Default: 1–3 short lines (headline + optional one supporting line + the
    artifact link), no paragraph breaks. Only when a concrete big-task signal
    fires (long artifact / multi-section result) does it expand to a longer
    sectioned digest that still LEADS with a one-line TL;DR. Depth stays in the
    attached PDF either way.
    """
    headline, body = _headline_and_body(markdown)
    head_line = escape_markdown_v2(f"> {agent}: {headline}")
    link_line = f"[full report]({_escape_link(deep_link)})"
    max_lines = telegram_max_lines()

    if not is_big_task(markdown):
        lines = [head_line]
        if max_lines >= 3 and body:
            lines.append(escape_markdown_v2(f"• {body[0]}"))
        lines.append(link_line)
        return truncate("\n".join(lines), limit=limit)

    # Big-task escape hatch — leading TL;DR, scannable, still capped.
    tldr = escape_markdown_v2(f"> TL;DR {agent}: {headline}")
    section_lines = [escape_markdown_v2(f"• {b}") for b in body[:5]]
    pointer = escape_markdown_v2("full detail in the attached PDF")
    text = "\n".join([tldr, *section_lines, pointer, link_line])
    if len(text) > limit:
        text = "\n".join([tldr, pointer, link_line])
    return truncate(text, limit=limit)
