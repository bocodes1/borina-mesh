"""Clean agent answers (Phase 7).

The dispatch reply (and any PDF) must contain the agent's ANSWER, not the raw
tmux pane scrollback. We learned this twice already (daily brief, planner): the
pane capture carries the echoed prompt, ⏺ tool-call displays, Bash(...)/Write()
blocks, box-drawing, the feedback prompt and mode bar. Same fix here.

Primary path: instruct the agent to write its final answer to a known file in
its workdir, then read that file. Fallback: aggressively clean the pane capture.

Also exposes `wants_pdf` — a PDF is opt-in (only when the user asks for one).
"""
from __future__ import annotations

import re
from pathlib import Path

ANSWER_INSTRUCTION = """

IMPORTANT - how to return your answer:
Write your COMPLETE final answer as clean markdown to this exact file path:
  {answer_file}
Write ONLY the answer into that file - no tool logs, no shell commands, no
preamble like "here is". Lead with ONE plain summary sentence, then the detail.
You may use tools while working, but the file must contain just the finished
answer. Do not paste the answer into the terminal."""

# ANSI / terminal control sequences — stripped before anything else.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Lines that are pure TUI / tool-call chrome — dropped entirely.
_DROP_PREFIXES = (
    "⎿", "│", "╭", "╰", "╮", "╯", "├", "┤", "└", "┌", "┐", "─", "═",
    "✻", "✽", "❯", "⏵⏵", "▐", "▕", "█",
)
_DROP_CONTAINS = (
    "How is Claude doing this session",
    "bypass permissions",
    "esc to interrupt",
    "ctrl+o to expand",
    "ctrl+c to",
    "Shell cwd was reset",
    "tokens ·",
    "Context left until",
    "auto-compact",
)
# A line that IS a tool call / command / log / diff — not prose.
_TOOL_CALL_RE = re.compile(
    r"^[⏺●○•]?\s*(Bash|Write|Read|Edit|Update|MultiEdit|Glob|Grep|Task|WebFetch|WebSearch|TodoWrite|NotebookEdit)\(",
)
_SHELL_RE = re.compile(r"^\s*(\$|❯|>>>|#)\s+\S")          # shell prompts / commands
_DIFF_RE = re.compile(r"^\s*(\+\+\+|---|@@|\+[^+]|diff --git|index [0-9a-f])")
_PATHY_RE = re.compile(r"^\s*(/[\w./-]+|[\w./-]+\.(py|ts|tsx|js|json|md|sh|txt)):?\s*$")
_FEEDBACK_RE = re.compile(r"^\s*\d+:\s*(Bad|Fine|Good|Dismiss)\b")
_SPINNER_RE = re.compile(r"^\s*[✻✽✶✷✢·∗*].*\(\d+s\b|^\s*(Running|Thinking|Working|Pondering|Cogitating)[.…]")
_MORE_LINES_RE = re.compile(r"^\s*…?\s*[+(]\d+\s*(lines|tokens|more)")
_INSTRUCTION_MARKERS = (
    "Produce a complete markdown report",
    "how to return your answer",
    "Write your COMPLETE final answer",
    "read-only intel only",
    "Telegram request",
    "Do not paste the answer into the terminal",
)


def clean_agent_output(raw: str) -> str:
    """Best-effort: strip tmux/TUI chrome, ANSI codes, tool-call displays, shell
    commands and diffs from a pane capture, keeping only the prose."""
    if not raw:
        return ""
    raw = _ANSI_RE.sub("", raw)
    out: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if any(s.startswith(p) for p in _DROP_PREFIXES):
            continue
        if _TOOL_CALL_RE.match(s) or _SHELL_RE.match(s) or _DIFF_RE.match(s) or _PATHY_RE.match(s):
            continue
        if _FEEDBACK_RE.match(s) or _SPINNER_RE.match(s) or _MORE_LINES_RE.match(s):
            continue
        if any(c in s for c in _DROP_CONTAINS):
            continue
        if any(m in s for m in _INSTRUCTION_MARKERS):
            continue
        # Prose emitted by the model is marked with a leading ⏺/● — keep the text.
        s = re.sub(r"^[⏺●○]\s*", "", s)
        out.append(s)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Markers that, if they survive cleaning, mean we're still looking at raw CLI.
_CLI_SIGNATURE_RE = re.compile(
    r"⏺|╭|╰|│|⎿|\bBash\(|\bWrite\(|\bTodoWrite\(|esc to interrupt|"
    r"bypass permissions|\x1b\[|^\s*\$\s|@@ -\d",
    re.MULTILINE,
)


def looks_like_cli_dump(text: str) -> bool:
    """True if the text still reads like a terminal scrollback rather than an
    answer — the last line of defence so raw CLI never reaches Telegram."""
    if not text or len(text.strip()) < 12:
        return True
    if _CLI_SIGNATURE_RE.search(text):
        return True
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    # Mostly command/path/diff lines, almost no sentences → a dump.
    chrome = sum(
        1 for ln in lines
        if _SHELL_RE.match(ln) or _DIFF_RE.match(ln) or _PATHY_RE.match(ln) or _TOOL_CALL_RE.match(ln)
    )
    sentences = sum(1 for ln in lines if re.search(r"[a-z]{3,}.*[.!?](\s|$)", ln))
    return chrome > len(lines) * 0.5 and sentences == 0


_CLI_FALLBACK = (
    "I finished the run, but couldn't pull a clean summary out of it. "
    "The full output is saved — open it in the mesh."
)


def _agent_workdir(agent_id: str) -> Path:
    from agents.runner_v2 import AGENT_REGISTRY, _workdir_root

    entry = AGENT_REGISTRY.get(agent_id, {})
    return Path(entry.get("workdir") or (_workdir_root() / agent_id))


def answer_file(agent_id: str, job_id: int, workdir: Path | None = None) -> Path:
    base = workdir or _agent_workdir(agent_id)
    return base / "answers" / f"job{job_id}.md"


async def _run_agent_task(agent_id: str, prompt: str, **kw):
    from agents.runner_v2 import run_agent_task

    return await run_agent_task(agent_id, prompt, **kw)


async def run_agent_for_answer(agent_id: str, prompt: str, job_id: int) -> str:
    """Run the agent and return its CLEAN answer: the handoff file if it wrote
    one, else the aggressively-cleaned pane capture."""
    wd = _agent_workdir(agent_id)
    af = answer_file(agent_id, job_id, wd)
    try:
        af.parent.mkdir(parents=True, exist_ok=True)
        if af.exists():
            af.unlink()
    except OSError:
        pass

    full_prompt = prompt + ANSWER_INSTRUCTION.format(answer_file=af)
    result = await _run_agent_task(agent_id, full_prompt)

    try:
        if af.exists():
            txt = af.read_text().strip()
            if len(txt) >= 20 and not looks_like_cli_dump(txt):
                return txt
    except OSError:
        pass
    # Fallback: clean the pane capture. If it STILL looks like raw CLI, send a
    # safe human line instead of dumping terminal scrollback into Telegram.
    cleaned = clean_agent_output(getattr(result, "output", "") or "")
    if looks_like_cli_dump(cleaned):
        return _CLI_FALLBACK
    return cleaned


# ── PDF opt-in ───────────────────────────────────────────────────────────────

# Explicit only — the bare word "report" no longer flips the format (that was
# the misfire that made the same question come back in two wildly different
# shapes). PDF is opt-in: the user has to actually ask for one.
_PDF_RE = re.compile(
    r"(?:^|\s)/pdf\b"
    r"|\bpdf\b"
    r"|\bwrite[\s-]?ups?\b"
    r"|\bdocuments?\b"
    r"|\bin writing\b"
    r"|\b(?:full|detailed) (?:report|write[\s-]?up)\b",
    re.IGNORECASE,
)


def wants_pdf(text: str) -> bool:
    """True only when the user EXPLICITLY asks for a written artifact — a PDF,
    write-up, document, or a 'full/detailed report'. The bare word 'report'
    ('give me a report on NVDA') does NOT trigger it (that was the misfire)."""
    return bool(_PDF_RE.search(text or ""))
