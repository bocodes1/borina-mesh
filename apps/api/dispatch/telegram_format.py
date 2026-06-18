"""Telegram outbound formatter — clean, OpenClaw-style replies.

EVERY outbound Telegram message passes through here. The job: turn whatever the
agent wrote (markdown, possibly messy) into a short, readable message that looks
like a person texted it — never a wall of MarkdownV2 backslashes, never raw CLI
chrome, never eaten arrows/checkmarks.

Design (foundation slice §B):
- **HTML parse_mode**, not MarkdownV2. No more `3\\.2% \\(Q1\\)` backslash spatter.
  We render a *small, safe* subset of markdown to Telegram-HTML (<b> <i> <code>
  <pre> <a>) and escape only & < >.
- **Format by size, not keywords.** Short answers go out in full; long answers are
  truncated on a clean boundary with a link to the full artifact. (The PDF path is
  opt-in and handled by the caller.)
- **Clean truncation.** We truncate the PLAIN text before rendering, so a cut never
  lands inside an HTML tag.
- **Meaningful glyphs survive.** strip_emojis removes pictographic emoji (🚀🔥) but
  keeps arrows (→ ↑ ↓), ✓, ™, bullets and dashes.
"""
from __future__ import annotations

import html
import os
import re

MAX_LEN = 4096
# Plain-text budget kept under MAX_LEN so HTML tags + a link never push the
# rendered message past Telegram's limit.
SAFE_BUDGET = 3600
BIG_TASK_CHARS = 1800
_MORE = " …"


def telegram_max_lines() -> int:
    try:
        return max(1, int(os.getenv("TELEGRAM_MAX_LINES", "3")))
    except ValueError:
        return 3


# ── emoji handling ─────────────────────────────────────────────────────────────
# Strip pictographic emoji from the supplementary planes + regional flags +
# variation selectors + ZWJ. Deliberately does NOT touch the BMP arrow/symbol
# ranges, so → ↑ ↓ ✓ ™ • survive (the old formatter ate them).
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # all supplementary pictographs / symbols / emoji
    "\U0001F1E6-\U0001F1FF"  # regional indicator (flags)
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "]+",
    flags=re.UNICODE,
)
# A small curated set of common DECORATIVE emoji that live in the BMP symbol
# ranges. Stripped explicitly so we can keep the meaningful neighbours (✓ → ™).
_BMP_DECORATIVE = "".join((
    "✅",  # ✅ check mark button
    "❌",  # ❌ cross mark
    "❗", "❓", "❔", "❕", "⁉", "‼",  # ! ? marks
    "⭐",  # ⭐ star
    "✨",  # ✨ sparkles
    "⚠",  # ⚠ warning (often paired with FE0F, handled above too)
    "⭕", "❎", "✳", "✴",
    "☑",  # ☑ ballot box with check (emoji-ish)
    "\U0001F44D", "\U0001F44E",  # (already covered by plane range; harmless)
))
_BMP_DECORATIVE_RE = re.compile("[" + re.escape(_BMP_DECORATIVE) + "]+")


def strip_emojis(text: str) -> str:
    return _BMP_DECORATIVE_RE.sub("", _EMOJI_RE.sub("", text))


def normalize_whitespace(text: str) -> str:
    """Dedent every line to the left margin, trim trailing spaces, collapse 3+
    blank lines to one."""
    lines = [ln.replace("\t", "    ").strip() for ln in text.splitlines()]
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


def escape_html(text: str) -> str:
    """Escape only the three characters Telegram HTML cares about: & < >."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── markdown → Telegram-safe HTML ───────────────────────────────────────────────
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")
_ITALIC_RE = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])|(?<![\w_])_([^_\n]+)_(?![\w_])")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_QUOTE_RE = re.compile(r"^\s*>\s?")
_NUM_RE = re.compile(r"^\s*(\d+)[.)]\s+")
_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


def _render_inline(text: str) -> str:
    """Render inline markdown in one line to Telegram HTML.

    Strategy: HTML-escape first (only &<> change; markdown markers survive), then
    convert markers to tags. Link/code contents are stashed behind placeholders so
    bold/italic passes can't reach inside them and produce nested/broken tags.
    """
    escaped = escape_html(text)
    stash: list[str] = []

    def _protect(htmltext: str) -> str:
        stash.append(htmltext)
        return _PLACEHOLDER.format(len(stash) - 1)

    escaped = _LINK_RE.sub(lambda m: _protect(f'<a href="{m.group(2)}">{m.group(1)}</a>'), escaped)
    escaped = _CODE_RE.sub(lambda m: _protect(f"<code>{m.group(1)}</code>"), escaped)
    escaped = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", escaped)
    escaped = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", escaped)
    escaped = _PLACEHOLDER_RE.sub(lambda m: stash[int(m.group(1))], escaped)
    return escaped


def render_telegram_html(markdown: str) -> str:
    """Convert a small subset of markdown to Telegram-safe HTML. Never raises:
    on any unexpected error it falls back to fully-escaped plain text."""
    try:
        text = normalize_whitespace(strip_emojis(markdown))
        out: list[str] = []
        in_fence = False
        fence: list[str] = []
        for ln in text.splitlines():
            if ln.strip().startswith("```"):
                if in_fence:
                    body = escape_html("\n".join(fence))
                    out.append(f"<pre>{body}</pre>")
                    fence = []
                    in_fence = False
                else:
                    in_fence = True
                continue
            if in_fence:
                fence.append(ln)
                continue
            if ln == "":
                out.append("")
                continue
            if _HEADING_RE.match(ln):
                out.append(f"<b>{_render_inline(_HEADING_RE.sub('', ln))}</b>")
            elif _BULLET_RE.match(ln):
                out.append("• " + _render_inline(_BULLET_RE.sub("", ln)))
            elif _NUM_RE.match(ln):
                n = _NUM_RE.match(ln).group(1)
                out.append(f"{n}. " + _render_inline(_NUM_RE.sub("", ln)))
            elif _QUOTE_RE.match(ln):
                out.append(_render_inline(_QUOTE_RE.sub("", ln)))
            else:
                out.append(_render_inline(ln))
        if in_fence and fence:  # unterminated fence
            out.append(f"<pre>{escape_html(chr(10).join(fence))}</pre>")
        return "\n".join(out).strip()
    except Exception:  # noqa: BLE001 — formatting must never crash a reply
        return escape_html(normalize_whitespace(strip_emojis(markdown)))


def _link_html(deep_link: str, label: str = "open in mesh") -> str:
    if not deep_link:
        return ""
    return f'<a href="{escape_html(deep_link)}">{escape_html(label)}</a>'


def _truncate_plain(text: str, budget: int) -> str:
    """Cut plain text on a clean boundary (paragraph > sentence > word), never
    mid-word. Truncation happens BEFORE HTML rendering so no tag is ever split."""
    if len(text) <= budget:
        return text
    window = text[:budget]
    # Prefer a paragraph/line break in the last 40% of the window.
    cut = window.rfind("\n")
    if cut < budget * 0.6:
        sent = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
        cut = sent + 1 if sent >= budget * 0.5 else window.rfind(" ")
    if cut <= 0:
        cut = budget
    return text[:cut].rstrip()


# ── public formatters ───────────────────────────────────────────────────────────
def cap_lines(text: str, max_lines: int) -> str:
    lines = [ln for ln in text.split("\n") if ln != ""]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines])


def format_telegram(raw: str, *, limit: int = MAX_LEN, max_lines: int | None = None) -> str:
    """Clean + render a short system message (acks, errors, status). HTML-safe,
    terse: long input is capped to the line budget."""
    rendered = render_telegram_html(raw)
    rendered = cap_lines(rendered, max_lines if max_lines is not None else telegram_max_lines())
    if len(rendered) > limit:
        # Re-truncate on the plain text to keep tags intact.
        plain = _truncate_plain(normalize_whitespace(strip_emojis(raw)), limit - 40)
        rendered = render_telegram_html(plain)
    return rendered


def format_answer_reply(*, agent: str, markdown: str, deep_link: str = "", limit: int = MAX_LEN) -> str:
    """The DEFAULT chat reply: the agent's ACTUAL answer, cleaned and rendered as
    HTML. Short answers go out whole; long answers are truncated on a clean
    boundary with a link to the full artifact. No PDF (that path is opt-in)."""
    plain = normalize_whitespace(strip_emojis(markdown))
    link = _link_html(deep_link, "full answer")
    budget = min(limit, SAFE_BUDGET) - (len(link) + 4 if link else 0)
    truncated = len(plain) > budget
    if truncated:
        plain = _truncate_plain(plain, budget) + _MORE
    body = render_telegram_html(plain)
    # Only the long/truncated case needs a pointer to the rest — a short answer
    # is complete on its own, so no link noise.
    if link and truncated:
        body = f"{body}\n\n{link}"
    return body


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
        elif len(body) < 5 and len(stripped) <= 120:
            body.append(stripped)
    return headline or "report ready", body


def is_big_task(markdown: str) -> bool:
    headings = len(re.findall(r"(?m)^#{1,3}\s", markdown))
    bullets = len(re.findall(r"(?m)^\s*[-*•]\s", markdown))
    return len(markdown) > BIG_TASK_CHARS or headings >= 3 or bullets >= 8


def format_dispatch_reply(*, agent: str, markdown: str, deep_link: str, limit: int = MAX_LEN) -> str:
    """Terse reply for the PDF path: a one-line headline (+ a supporting line for
    big tasks) and the artifact link. Depth lives in the attached PDF."""
    headline, body = _headline_and_body(markdown)
    link = _link_html(deep_link, "full report")
    if not is_big_task(markdown):
        lines = [f"<b>{escape_html(agent)}:</b> {_render_inline(headline)}"]
        if telegram_max_lines() >= 3 and body:
            lines.append("• " + _render_inline(body[0]))
        lines.append(link)
        return "\n".join(p for p in lines if p)
    tldr = f"<b>TL;DR {escape_html(agent)}:</b> {_render_inline(headline)}"
    section = ["• " + _render_inline(b) for b in body[:5]]
    text = "\n".join([tldr, *section, link])
    if len(text) > limit:
        text = "\n".join([tldr, link])
    return text
