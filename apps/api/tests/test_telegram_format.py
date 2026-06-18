"""Telegram outbound formatter — HTML, clean, OpenClaw-style (foundation §B)."""
import re

from dispatch.telegram_format import (
    strip_emojis,
    normalize_whitespace,
    escape_html,
    render_telegram_html,
    format_telegram,
    format_answer_reply,
    format_dispatch_reply,
    MAX_LEN,
)

# Pictographic emoji only — meaningful symbols (→ ✓ ™) are NOT in here.
PICTO_RE = re.compile("[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\U0000FE0F\U0000200D]")


def test_strip_emojis_removes_pictographs():
    assert "rocket" in strip_emojis("rocket 🚀🔥")
    assert not PICTO_RE.search(strip_emojis("done 🎉 shipping 🚀"))


def test_strip_emojis_keeps_meaningful_glyphs():
    # The old formatter ate these — they must survive now.
    kept = strip_emojis("revenue → up ↑, thesis ✓, Borina™ • point")
    assert "→" in kept and "↑" in kept and "✓" in kept and "™" in kept and "•" in kept


def test_escape_html_only_amp_lt_gt():
    assert escape_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"
    # Punctuation that MarkdownV2 mangled is now untouched — no backslashes.
    assert escape_html("3.2% (Q1). cost-basis!") == "3.2% (Q1). cost-basis!"


def test_no_markdownv2_backslash_spatter():
    out = format_answer_reply(agent="researcher", markdown="Revenue up 3.2% (Q1). Margins steady!", deep_link="")
    assert "\\" not in out                       # no escaped-dot/paren/bang spatter
    assert "3.2% (Q1)" in out


def test_render_html_bold_code_link_bullets():
    md = "# NVDA\n\n**Thesis** intact. Use `RSI` here.\n- point one\n- point two\n[docs](https://x.io/d)"
    out = render_telegram_html(md)
    assert "<b>NVDA</b>" in out                   # heading → bold
    assert "<b>Thesis</b>" in out                 # bold
    assert "<code>RSI</code>" in out              # inline code
    assert '<a href="https://x.io/d">docs</a>' in out
    assert "• point one" in out and "• point two" in out


def test_render_html_escapes_angle_brackets_in_prose():
    out = render_telegram_html("compare a<b and c>d & e")
    assert "a&lt;b" in out and "c&gt;d" in out and "&amp;" in out
    assert "<b" not in out.replace("&lt;", "")    # no stray real tags from prose


def test_render_html_code_fence_to_pre():
    out = render_telegram_html("here:\n```\n$ rm -rf /tmp/x\n```\ndone")
    assert "<pre>" in out and "</pre>" in out
    assert "rm -rf" in out


def test_render_html_never_raises_on_garbage():
    # Unbalanced markers / weird input must not blow up the reply path.
    out = render_telegram_html("**unclosed [bad](http:// `code")
    assert isinstance(out, str) and out


def test_format_telegram_messy_input_is_clean_html():
    messy = "  Hello 🚀🚀 \n\n\n\n   world! Costs $5.00 (a lot).  "
    out = format_telegram(messy)
    assert not PICTO_RE.search(out)               # emoji-free
    assert "\n\n\n" not in out                    # whitespace-collapsed
    assert "\\" not in out                        # not MarkdownV2
    assert "$5.00 (a lot)" in out                 # punctuation intact


def test_format_telegram_length_cap():
    out = format_telegram("x" * (MAX_LEN + 2000))
    assert len(out) <= MAX_LEN


def test_format_answer_reply_sends_the_answer():
    md = ("BTC held $60K overnight, up 2%.\n\n"
          "The bounce is intact but the 30yr is still elevated. "
          "Watch core CPI tomorrow.")
    out = format_answer_reply(agent="researcher", markdown=md, deep_link="http://x/a")
    assert "30yr is still elevated" in out
    assert "BTC held" in out
    assert len(out) <= MAX_LEN


def test_format_answer_reply_short_answer_has_no_link_noise():
    # A short answer goes out whole, with no "full answer" link appended.
    out = format_answer_reply(agent="researcher", markdown="AAPL looks fine, no thesis change.", deep_link="http://x/a")
    assert "AAPL looks fine" in out
    assert "full answer" not in out


def test_format_answer_reply_caps_long_answers_with_link():
    md = "summary line.\n\n" + ("word " * 5000)
    out = format_answer_reply(agent="ceo", markdown=md, deep_link="http://x/a")
    assert len(out) <= MAX_LEN
    assert "full answer" in out                   # truncated → link to the rest
    assert "…" in out                             # clean truncation marker


def test_format_answer_reply_truncation_keeps_html_intact():
    # Bold marker near the cut must not produce a dangling <b>.
    md = "**lead summary that matters**\n\n" + ("detail sentence here. " * 800)
    out = format_answer_reply(agent="ceo", markdown=md, deep_link="http://x/a")
    assert out.count("<b>") == out.count("</b>")
    assert out.count("<a ") == out.count("</a>")


def test_format_dispatch_reply_terse_and_linked():
    out = format_dispatch_reply(
        agent="researcher", markdown="AAPL looks fine, no thesis change.",
        deep_link="http://h:3000/artifacts?id=2026-06-05/x.pdf",
    )
    lines = [l for l in out.split("\n") if l]
    assert len(lines) <= 3
    assert "full report" in out
    assert "researcher" in out


def test_format_dispatch_reply_big_task_expands_with_tldr():
    big = "# Portfolio review\n\n" + "\n".join(
        f"## Holding {i}\n\nDetail line {i} with enough text to matter." for i in range(6)
    )
    out = format_dispatch_reply(agent="researcher", markdown=big, deep_link="http://h/a?id=x")
    assert "TL;DR" in out
    assert len(out) <= MAX_LEN
    assert len([l for l in out.split("\n") if l]) > 2
