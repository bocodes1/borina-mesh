"""Answer cleaning + CLI-dump guard — guarantees Telegram never shows raw CLI."""
from dispatch.answer import clean_agent_output, looks_like_cli_dump, wants_pdf


RAW_PANE = """\
⏺ Bash(cat report.md)
  ⎿ Running…
╭──────────────────────────────╮
│ > read-only intel only        │
╰──────────────────────────────╯
\x1b[32m$ python analyze.py\x1b[0m
+++ b/file.py
@@ -1,3 +1,4 @@
⏺ The thesis is intact: revenue is up 22% and margins held steady.
Watch core CPI tomorrow before adding.
  1: Good  2: Bad
esc to interrupt · 1.2k tokens
"""


def test_clean_strips_all_chrome_keeps_prose():
    out = clean_agent_output(RAW_PANE)
    assert "thesis is intact" in out
    assert "Watch core CPI" in out
    # none of the chrome survives
    for junk in ("Bash(", "Running", "╭", "│", "$ python", "+++", "@@", "esc to interrupt", "tokens"):
        assert junk not in out
    assert "\x1b" not in out                       # ANSI gone


def test_looks_like_cli_dump_detects_terminal_scrollback():
    dump = "⏺ Bash(ls)\n  ⎿ done\n$ rm -rf /tmp\n@@ -1 +1 @@"
    assert looks_like_cli_dump(dump) is True


def test_looks_like_cli_dump_passes_real_answer():
    answer = ("BTC held $60K overnight, up 2%. The bounce is intact but the 30yr "
              "is still elevated. Watch core CPI tomorrow.")
    assert looks_like_cli_dump(answer) is False


def test_looks_like_cli_dump_flags_empty_or_tiny():
    assert looks_like_cli_dump("") is True
    assert looks_like_cli_dump("ok") is True


def test_wants_pdf_explicit_only():
    # The bare word "report" must NOT trigger a PDF anymore (the old misfire).
    assert wants_pdf("give me a report on NVDA") is False
    assert wants_pdf("what's the latest on my portfolio?") is False
    # Explicit asks DO trigger.
    assert wants_pdf("send it as a pdf") is True
    assert wants_pdf("/pdf please") is True
    assert wants_pdf("I want a full report") is True
    assert wants_pdf("put it in writing") is True
