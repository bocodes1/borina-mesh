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

# Lines that are pure TUI / tool-call chrome — dropped entirely.
_DROP_PREFIXES = (
    "⎿", "│", "╭", "╰", "✻", "✽", "❯", "⏵⏵",
)
_DROP_CONTAINS = (
    "How is Claude doing this session",
    "bypass permissions",
    "esc to interrupt",
    "ctrl+o to expand",
    "Shell cwd was reset",
    "tokens ·",
)
_TOOL_CALL_RE = re.compile(r"^⏺\s*(Bash|Write|Read|Edit|Update|Glob|Grep|Task|WebFetch|WebSearch|TodoWrite)\(")
_FEEDBACK_RE = re.compile(r"^\s*\d+:\s*(Bad|Fine|Good|Dismiss)\b")
_SPINNER_RE = re.compile(r"^\s*[✻✽✶✷·].*\(\d+s\b")
_MORE_LINES_RE = re.compile(r"^\s*…\s*\+\d+\s*lines")
_INSTRUCTION_MARKERS = (
    "Produce a complete markdown report",
    "how to return your answer",
    "Write your COMPLETE final answer",
    "read-only intel only",
    "Telegram request",
)


def clean_agent_output(raw: str) -> str:
    """Best-effort: strip tmux/TUI chrome and tool-call displays from a pane
    capture, keeping the prose. The ⏺ marker on a prose line is removed."""
    if not raw:
        return ""
    out: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if any(s.startswith(p) for p in _DROP_PREFIXES):
            continue
        if _TOOL_CALL_RE.match(s):
            continue
        if _FEEDBACK_RE.match(s) or _SPINNER_RE.match(s) or _MORE_LINES_RE.match(s):
            continue
        if any(c in s for c in _DROP_CONTAINS):
            continue
        if any(m in s for m in _INSTRUCTION_MARKERS):
            continue
        # Prose emitted by the model is marked with a leading ⏺ — keep the text.
        if s.startswith("⏺"):
            s = s[1:].strip()
        out.append(s)
    # Collapse 3+ blank lines.
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
            if len(txt) >= 20:  # a real answer, not an empty stub
                return txt
    except OSError:
        pass
    return clean_agent_output(getattr(result, "output", "") or "")


# ── PDF opt-in ───────────────────────────────────────────────────────────────

_PDF_RE = re.compile(
    r"\b(pdf|reports?|write[\s-]?ups?|documents?|\bdocs?\b|in writing|"
    r"full (write|report)|detailed (report|write))\b",
    re.IGNORECASE,
)


def wants_pdf(text: str) -> bool:
    """True only when the user explicitly asks for a PDF/report/document."""
    return bool(_PDF_RE.search(text or ""))
