"""Telegram outbound formatter (spec §4)."""
import re

from dispatch.telegram_format import (
    strip_emojis,
    normalize_whitespace,
    escape_markdown_v2,
    format_telegram,
    format_dispatch_reply,
    MAX_LEN,
)

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U0000FE0F\U0000200D]"
)


def test_strip_emojis():
    assert "rocket" in strip_emojis("rocket 🚀🔥✅")
    assert not EMOJI_RE.search(strip_emojis("done ✅ 🎉 shipping 🚀"))


def test_normalize_whitespace_dedents_and_collapses():
    messy = "   indented line  \n\n\n\n      another   \n\t\ttabbed"
    out = normalize_whitespace(messy)
    # left-aligned: no line starts with whitespace
    assert all(not ln.startswith((" ", "\t")) for ln in out.splitlines())
    # no trailing whitespace
    assert all(ln == ln.rstrip() for ln in out.splitlines())
    # 3+ blank lines collapsed to at most one blank
    assert "\n\n\n" not in out


def test_escape_markdown_v2():
    assert escape_markdown_v2("a.b!c-d") == "a\\.b\\!c\\-d"
    assert escape_markdown_v2("(x)[y]") == "\\(x\\)\\[y\\]"


def test_format_telegram_messy_input():
    messy = "  Hello 🚀🚀 \n\n\n\n   world! Costs $5.00 (a lot).  \n" + "x" * 50
    out = format_telegram(messy)
    assert not EMOJI_RE.search(out)               # emoji-free
    assert "\n\n\n" not in out                    # whitespace-collapsed
    assert all(not ln.startswith(" ") for ln in out.splitlines())  # left-aligned
    assert "\\!" in out and "\\." in out          # escaped


def test_format_telegram_length_cap():
    out = format_telegram("x" * (MAX_LEN + 2000))
    assert len(out) <= MAX_LEN
    assert "PDF" in out  # pointer to the attached report


def test_format_dispatch_reply_is_short_clean_and_linked():
    markdown = (
        "# NVDA deep dive 🚀\n\n"
        "   The thesis is intact.\n\n\n\n"
        "Revenue up 22%. Margins steady!\n"
        + "\n".join(f"- point {i} with some detail here" for i in range(20))
    )
    out = format_dispatch_reply(agent="researcher", markdown=markdown, deep_link="http://host:3000/artifacts?id=2026-06-05/x.pdf")
    assert not EMOJI_RE.search(out)               # no emojis
    assert "\n\n\n" not in out                    # clean spacing
    assert "full report" in out                   # artifact link present
    assert "researcher" in out                    # headline mentions the agent
    # short digest: not a wall of text
    assert out.count("\n") < 12
    assert len(out) <= MAX_LEN


def test_dispatch_reply_truncates_when_huge():
    huge = "headline here\n\n" + ("very long body line. " * 500)
    out = format_dispatch_reply(agent="ceo", markdown=huge, deep_link="http://h/a?id=x")
    assert len(out) <= MAX_LEN
    assert "full report" in out


def test_simple_reply_is_terse():
    out = format_dispatch_reply(
        agent="researcher", markdown="AAPL looks fine, no thesis change.",
        deep_link="http://h:3000/artifacts?id=2026-06-05/x.pdf",
    )
    lines = [l for l in out.split("\n") if l]
    assert len(lines) <= 3                 # 1-3 short lines
    assert "\n\n" not in out               # no paragraph breaks
    assert "full report" in out


def test_multiparagraph_model_output_collapses(monkeypatch):
    monkeypatch.setenv("TELEGRAM_MAX_LINES", "3")
    prose = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n\nFourth paragraph."
    out = format_telegram(prose)
    lines = [l for l in out.split("\n") if l]
    assert len(lines) <= 3
    assert "PDF" in out                    # collapsed → pointer


def test_big_task_expands_with_leading_tldr():
    big = "# Portfolio review\n\n" + "\n".join(
        f"## Holding {i}\n\nDetail line {i} with enough text to matter." for i in range(6)
    )
    out = format_dispatch_reply(agent="researcher", markdown=big, deep_link="http://h/a?id=x")
    assert "TL;DR" in out                   # leads with a one-line TL;DR
    assert not EMOJI_RE.search(out)         # still emoji-free
    assert len(out) <= MAX_LEN              # still capped
    assert len([l for l in out.split("\n") if l]) > 3  # expanded beyond terse


def test_format_answer_reply_sends_the_answer_not_one_line():
    from dispatch.telegram_format import format_answer_reply
    md = ("BTC held $60K overnight, up 2%.\n\n"
          "The bounce is intact but the 30yr is still elevated. "
          "Watch core CPI tomorrow.")
    out = format_answer_reply(agent="researcher", markdown=md, deep_link="http://x/a")
    # The actual answer content is present (not collapsed to a headline).
    assert "30yr is still elevated" in out
    assert "BTC held" in out
    # No emojis, escaped, within Telegram's limit.
    assert len(out) <= 4096


def test_format_answer_reply_caps_long_answers():
    from dispatch.telegram_format import format_answer_reply
    md = "summary line\n\n" + ("x " * 5000)
    out = format_answer_reply(agent="ceo", markdown=md, deep_link="http://x/a")
    assert len(out) <= 4096
