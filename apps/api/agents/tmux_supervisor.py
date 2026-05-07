"""Tmux pool manager for long-lived `claude` CLI agent sessions.

Each agent runs `claude --dangerously-skip-permissions` inside a named tmux
session, kept alive across many prompts.  The supervisor namespaces session
names with the local pane number (`BORINA_PANE_NUMBER`) so 8 parallel refactor
sandboxes can coexist on the same machine without colliding.

Public API (also see `get_supervisor()`):
    spawn(agent_id, workdir, system_prompt) -> str
    send_prompt(agent_id, prompt) -> None
    capture(agent_id, lines=200) -> str
    wait_for_idle(agent_id, idle_seconds=4, timeout_seconds=60) -> str
    restart(agent_id) -> str
    kill(agent_id) -> None
    list_sessions() -> list[str]
    session_exists(agent_id) -> bool
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional


# --- ANSI / spinner stripping ------------------------------------------------

# ECMA-48 / VT100 control sequences (CSI, OSC, single-char escapes)
_ANSI_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07|\][^\x1B]*\x1B\\)"
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# --- Pane / session naming ---------------------------------------------------

def _pane_number() -> str:
    """Read pane id from env at call time so .env loads after import still apply."""
    return os.environ.get("BORINA_PANE_NUMBER", "0")


def _session_prefix() -> str:
    return f"borina-p{_pane_number()}-"


# --- Binary resolution -------------------------------------------------------

_TMUX_BIN: Optional[str] = None


def _tmux() -> str:
    global _TMUX_BIN
    if _TMUX_BIN is None:
        _TMUX_BIN = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
    return _TMUX_BIN


def _resolve_claude_path() -> str:
    """Find the claude CLI: env var → PATH → hardcoded fallbacks."""
    candidates: list[str] = []
    env_path = os.environ.get("CLAUDE_CLI_PATH")
    if env_path:
        candidates.append(env_path)
    which = shutil.which("claude")
    if which:
        candidates.append(which)
    candidates.extend([
        os.path.expanduser("~/.npm-global/bin/claude"),
        os.path.expanduser("~/.local/bin/claude"),
        "/opt/homebrew/bin/claude",
    ])
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise RuntimeError(
        f"could not locate `claude` CLI binary; tried: {candidates!r} "
        f"(set CLAUDE_CLI_PATH to override)"
    )


# --- Subprocess wrapper with full error context ------------------------------

def _run(
    cmd: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 10.0,
    allow_rc: tuple[int, ...] = (0,),
) -> tuple[int, str, str]:
    """Run a subprocess. On unexpected non-zero rc, raise RuntimeError with
    full stdout+stderr context.  Returns (rc, stdout, stderr) for callers
    that pass `allow_rc` to permit benign non-zero codes."""
    try:
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"binary not found: {cmd[0]!r} ({e!r})") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"command timed out after {timeout}s: {cmd!r} | "
            f"stdout={e.stdout!r} stderr={e.stderr!r}"
        ) from e
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode not in allow_rc:
        raise RuntimeError(
            f"command failed (rc={proc.returncode}): {cmd!r} | "
            f"stdout={out!r} stderr={err!r}"
        )
    return proc.returncode, out, err


# --- Supervisor --------------------------------------------------------------

class TmuxSupervisor:
    """Singleton-ish manager for a pool of agent tmux sessions."""

    def __init__(self) -> None:
        self._claude_path = _resolve_claude_path()
        # Cache spawn args so restart() can re-spawn with the same config.
        self._spawn_cache: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    # ----- naming --------------------------------------------------------

    def session_name(self, agent_id: str) -> str:
        return f"{_session_prefix()}{agent_id}"

    # ----- existence / listing ------------------------------------------

    def session_exists(self, agent_id: str) -> bool:
        name = self.session_name(agent_id)
        try:
            rc, _, _ = _run(
                [_tmux(), "has-session", "-t", name],
                allow_rc=(0, 1),
                timeout=5,
            )
            return rc == 0
        except RuntimeError:
            return False

    def list_sessions(self) -> list[str]:
        """Return agent ids of every supervisor-owned tmux session that exists."""
        try:
            rc, out, err = _run(
                [_tmux(), "list-sessions", "-F", "#{session_name}"],
                allow_rc=(0, 1),
                timeout=5,
            )
        except RuntimeError as e:
            # tmux server not running yet → treat as empty list.
            if "no server running" in str(e) or "error connecting" in str(e):
                return []
            raise
        if rc != 0:
            return []
        prefix = _session_prefix()
        agents: list[str] = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith(prefix):
                agents.append(line[len(prefix):])
        return agents

    # ----- spawn / kill / restart ---------------------------------------

    def spawn(self, agent_id: str, workdir: str, system_prompt: str) -> str:
        """Create the tmux session if missing and start `claude` inside it.

        Re-adopts an already-running session so an API restart does not
        reset agents.  Returns the tmux session name.
        """
        with self._lock:
            self._spawn_cache[agent_id] = {
                "workdir": workdir,
                "system_prompt": system_prompt or "",
            }
            name = self.session_name(agent_id)
            if self.session_exists(agent_id):
                return name

            wd_path = Path(workdir).expanduser()
            wd_path.mkdir(parents=True, exist_ok=True)

            # Build the claude command line.  Pass system prompt via
            # --append-system-prompt and ALSO drop a CLAUDE.md so the
            # agent has the same context however it's loaded.
            args: list[str] = [self._claude_path, "--dangerously-skip-permissions"]
            if system_prompt:
                args += ["--append-system-prompt", system_prompt]
                try:
                    (wd_path / "CLAUDE.md").write_text(
                        system_prompt, encoding="utf-8"
                    )
                except OSError:
                    pass  # non-fatal; --append-system-prompt is enough

            cmd_str = shlex.join(args)
            _run(
                [
                    _tmux(), "new-session", "-d",
                    "-s", name,
                    "-x", "200", "-y", "50",
                    "-c", str(wd_path),
                    cmd_str,
                ],
                timeout=15,
            )

            # Wait for claude REPL to render its prompt.  Markers are the
            # box-drawing borders or the leading `>` cursor.
            self._wait_for_ready(agent_id, timeout_seconds=30)
            return name

    def _wait_for_ready(self, agent_id: str, timeout_seconds: float = 30.0) -> None:
        """Wait for claude to render its REPL prompt, auto-dismissing the
        first-launch 'trust this folder' confirmation if it appears."""
        deadline = time.time() + timeout_seconds
        repl_markers = ("Try ", "shortcuts", "/help", "Welcome to Claude")
        trust_markers = ("trust this folder", "Yes, I trust", "Is this a project you")
        name = self.session_name(agent_id)
        trust_dismissed = False
        last = ""
        while time.time() < deadline:
            try:
                last = self.capture(agent_id, 80)
            except RuntimeError:
                last = ""
            # Auto-confirm the folder trust prompt at most once.
            if not trust_dismissed and any(m in last for m in trust_markers):
                try:
                    _run([_tmux(), "send-keys", "-t", name, "Enter"], timeout=5)
                except RuntimeError:
                    pass
                trust_dismissed = True
                time.sleep(1.0)
                continue
            if any(m in last for m in repl_markers):
                return
            # Also accept the box-drawing input border once trust is dismissed.
            if trust_dismissed and any(m in last for m in ("│", "╭", "╰", "╮", "╯", ">")):
                return
            time.sleep(0.5)
        # Don't raise — let the caller try anyway; partial output is still useful.

    def kill(self, agent_id: str) -> None:
        if not self.session_exists(agent_id):
            return
        name = self.session_name(agent_id)
        _run([_tmux(), "kill-session", "-t", name], timeout=10)

    def restart(self, agent_id: str) -> str:
        cached = self._spawn_cache.get(agent_id)
        if not cached:
            # Best-effort: synthesise a workdir, leave system_prompt blank.
            cached = {
                "workdir": os.path.expanduser(
                    f"~/.borina/agents/p{_pane_number()}/{agent_id}"
                ),
                "system_prompt": "",
            }
        if self.session_exists(agent_id):
            self.kill(agent_id)
        return self.spawn(agent_id, cached["workdir"], cached["system_prompt"])

    # ----- I/O ----------------------------------------------------------

    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Send a prompt to the live claude REPL via paste-buffer + Enter.

        Newlines are preserved by going through tmux paste-buffer, which
        the terminal delivers as a single bracketed-paste block."""
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"tmux session for agent {agent_id!r} does not exist; "
                f"call spawn() first"
            )
        name = self.session_name(agent_id)
        # Per-call buffer name keeps concurrent prompts from clobbering one another.
        buf = f"borina-{_pane_number()}-{agent_id}-{time.time_ns()}"
        # 1) Stage the prompt text into a named tmux buffer.
        _run(
            [_tmux(), "load-buffer", "-b", buf, "-"],
            input_bytes=prompt.encode("utf-8"),
            timeout=10,
        )
        # 2) Paste it into the target pane and delete the buffer.
        _run([_tmux(), "paste-buffer", "-b", buf, "-t", name, "-d"], timeout=10)
        # 3) Submit by pressing Enter.
        _run([_tmux(), "send-keys", "-t", name, "Enter"], timeout=10)

    def capture(self, agent_id: str, lines: int = 200) -> str:
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"tmux session for agent {agent_id!r} does not exist"
            )
        name = self.session_name(agent_id)
        _, out, _ = _run(
            [
                _tmux(), "capture-pane", "-p", "-t", name,
                "-S", str(-max(1, int(lines))),
            ],
            timeout=10,
        )
        return _strip_ansi(out)

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: float = 4.0,
        timeout_seconds: float = 60.0,
    ) -> str:
        """Block until the pane has been unchanged for `idle_seconds`.

        Returns the most recent capture either way — on timeout, it
        returns the partial output rather than raising, so callers can
        surface what claude did manage to produce."""
        deadline = time.time() + timeout_seconds
        last = self.capture(agent_id, 800)
        last_change = time.time()
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                cur = self.capture(agent_id, 800)
            except RuntimeError:
                # session vanished mid-wait
                return last
            if cur != last:
                last = cur
                last_change = time.time()
            elif (time.time() - last_change) >= idle_seconds:
                return cur
        return last


# --- Module-level singleton --------------------------------------------------

_INSTANCE: Optional[TmuxSupervisor] = None
_INSTANCE_LOCK = threading.Lock()


def get_supervisor() -> TmuxSupervisor:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = TmuxSupervisor()
    return _INSTANCE
