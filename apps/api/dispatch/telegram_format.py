"""Telegram outbound formatter (spec §4).

EVERY outbound Telegram message passes through here so replies are short,
emoji-free, left-aligned, whitespace-collapsed, MarkdownV2-escaped, and
length-capped — independent of how the model wrote them. Depth lives in the
attached PDF; the chat body is a short digest.
"""
from __future__ import annotations

import re

MAX_LEN = 4096

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


def format_telegram(raw: str, *, limit: int = MAX_LEN) -> str:
    """Clean + escape an arbitrary message (acks, errors). MarkdownV2-safe."""
    cleaned = normalize_whitespace(strip_emojis(raw))
    escaped = escape_markdown_v2(cleaned)
    return truncate(escaped, limit=limit)


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
    """Short structured digest for a completed dispatch: one headline, up to 4
    short bullet lines, a blank line, then the artifact deep-link."""
    headline, body = _headline_and_body(markdown)

    head_line = escape_markdown_v2(f"> {agent}: {headline}")
    bullet_lines = [escape_markdown_v2(f"• {b}") for b in body]
    link_line = f"[full report]({_escape_link(deep_link)})"

    blocks = [head_line]
    if bullet_lines:
        blocks.append("\n".join(bullet_lines))
    blocks.append(link_line)
    text = "\n\n".join(blocks)

    if len(text) > limit:
        # Drop body, keep headline + pointer + link.
        pointer = escape_markdown_v2("(full detail in the attached PDF)")
        text = f"{head_line}\n\n{pointer}\n\n{link_line}"
    return text
