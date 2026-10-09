"""Launch Studio shell-out client (M5, contracts §9).

The mesh never imports studio code and never reads its project files: it runs
`npx -y pnpm@12.8.1 studio …` inside ~/dev/launch-studio and reads the LAST
stdout line, the studio's machine line. Every call returns a StudioResult and
never raises, so a broken studio can't put a traceback into Bo's chat.

The child gets a small allow-listed environment: the mesh's own secrets
(Telegram token, OAuth tokens, API keys) never reach a headless Claude run.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

STUDIO_CMD = ["npx", "-y", "pnpm@12.8.1", "studio"]
ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "SHELL", "CLAUDE_CLI_PATH", "GITHUB_TOKEN")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")  # contracts §2
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TRACE_RE = re.compile(r"Traceback|^\s*at |\bError:|node:internal|\.(?:ts|js|mjs|py):\d+")


@dataclass
class StudioResult:
    code: Optional[int]                              # None: it never finished (timeout, not installed)
    last: str = ""                                   # last non-empty stdout line, cleaned
    lines: list[str] = field(default_factory=list)   # every stdout line, cleaned (for logs)
    error: str = ""                                  # short, chat-safe reason when not ok
    raw: str = ""                                    # last stdout line as printed; JSON is parsed from this

    @property
    def ok(self) -> bool:
        return self.code == 0


# (argv, cwd, env, timeout) -> (exit code, or None on timeout; stdout; stderr)
Runner = Callable[[list[str], Path, dict, float], tuple[Optional[int], str, str]]


def studio_dir() -> Path:
    return Path(os.getenv("STUDIO_DIR", "").strip() or (Path.home() / "dev" / "launch-studio"))


def studio_env() -> dict:
    """The child's whole environment: what node, pnpm and claude need, plus STUDIO_*."""
    env = {k: os.environ[k] for k in ENV_KEEP if os.environ.get(k)}
    env.update({k: v for k, v in os.environ.items() if k.startswith("STUDIO_")})
    return env


def _killpg(pid: int, grace: float = 3.0) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def popen_runner(argv: list[str], cwd: Path, env: dict, timeout: float) -> tuple[Optional[int], str, str]:
    """Own process group (start_new_session), so a timeout also kills the node and
    claude processes npx started, not just npx."""
    proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        _killpg(proc.pid)
        out, err = proc.communicate()
        return None, out or "", err or ""


runner: Runner = popen_runner  # tests replace this with a fake


def clean_line(s: str) -> str:
    s = _CTRL_RE.sub("", _ANSI_RE.sub("", s)).strip()
    return re.sub(r"\s+", " ", s)[:300]


def chat_reason(text: str, code: Optional[int]) -> str:
    """A reason fit for Bo's chat: never a stack trace or a source path."""
    t = clean_line(text)
    if not t or _TRACE_RE.search(t):
        return f"studio failed (exit {'none' if code is None else code}); details are in the mesh log"
    return t[:200]


def _stderr_reason(err: str) -> str:
    """The studio's own error line (`studio <name>: <message>` or `usage: …`), which it
    prints on stderr between pnpm's `$ node …` banner and its ELIFECYCLE line. Empty when
    stderr holds a stack trace, so chat_reason falls back to the generic line."""
    lines = [clean_line(ln) for ln in err.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith("$ ") and "ELIFECYCLE" not in ln
             and not ln.lower().startswith("npm warn")]
    if not lines or any(_TRACE_RE.search(ln) for ln in lines[-6:]):
        return ""
    return re.sub(r"^studio [a-z-]+: ", "", lines[-1])


def run(args: list[str], timeout: float = 120.0) -> StudioResult:
    d = studio_dir()
    if not d.is_dir():
        return StudioResult(None, error="launch-studio is not installed on this machine")
    try:
        code, out, err = runner([*STUDIO_CMD, *args], d, studio_env(), timeout)
    except FileNotFoundError:
        return StudioResult(None, error="npx is not on the mesh's PATH")
    except Exception as exc:  # noqa: BLE001 — a broken studio must never crash a handler
        return StudioResult(None, error=f"studio call failed ({type(exc).__name__})")
    printed = [ln for ln in out.splitlines() if ln.strip()]
    raw = _ANSI_RE.sub("", printed[-1]).strip() if printed else ""
    lines = [clean_line(ln) for ln in printed]
    last = lines[-1] if lines else ""
    print(f"[studio] {args[0] if args else '-'} -> exit {code}: {last[:160]}")
    if code != 0:
        for ln in err.splitlines()[-8:]:  # the details chat_reason points Bo at
            print(f"[studio] {args[0] if args else '-'} stderr: {clean_line(ln)}")
    if code is None:
        return StudioResult(None, last, lines, f"timed out after {int(timeout)} s", raw)
    if code == 0:
        return StudioResult(0, last, lines, "", raw)
    detail = last[len("FAIL "):] if last.startswith("FAIL ") else (_stderr_reason(err) or last)
    return StudioResult(code, last, lines, chat_reason(detail, code), raw)


def json_line(res: StudioResult) -> Optional[dict]:
    if not res.ok or not res.raw.startswith("{"):
        return None
    try:
        obj = json.loads(res.raw)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def pending_stops() -> Optional[list[dict]]:
    """Every pending stop across projects (`studio stops --pending --json`), or None if the CLI failed."""
    obj = json_line(run(["stops", "--pending", "--json"], timeout=90))
    stops = obj.get("stops") if obj else None
    return [s for s in stops if isinstance(s, dict)] if isinstance(stops, list) else None


def projects() -> Optional[list[dict]]:
    """Every project (`studio status --json`), or None if the CLI failed."""
    obj = json_line(run(["status", "--json"], timeout=90))
    items = obj.get("projects") if obj else None
    return [p for p in items if isinstance(p, dict)] if isinstance(items, list) else None
