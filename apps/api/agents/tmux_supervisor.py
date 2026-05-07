"""Tmux-based supervisor for long-lived `claude` CLI sessions.

Each agent runs inside its own tmux session executing `claude --dangerously-skip-permissions`
indefinitely. Prompts are pasted via `tmux load-buffer` + `paste-buffer -p` so multi-line
input lands as a single bracketed-paste block. Output is read with `tmux capture-pane`,
ANSI codes stripped.

Session names are namespaced as `borina-p${BORINA_PANE_NUMBER}-{agent_id}` so up to 8
parallel pane instances of this refactor never collide on tmux session names during
verification.

All subprocess calls capture stderr and raise ``RuntimeError`` with full context — never
empty error messages.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


PANE_NUMBER = os.environ.get("BORINA_PANE_NUMBER", "0")

_ANSI_RE = re.compile(
    r"""
    \x1B   # ESC
    (?:
        [@-Z\\-_]                    # 7-bit C1 Fe (except CSI)
      | \[ [0-?]* [ -/]* [@-~]       # CSI sequence
      | \] [^\x07\x1B]* (?:\x07|\x1B\\)  # OSC sequence terminated by BEL or ST
      | [PX^_] [^\x07\x1B]* (?:\x07|\x1B\\)  # DCS/PM/APC/SOS
      | [()][AB012]                  # charset selection
    )
    """,
    re.VERBOSE,
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a captured tmux pane."""
    return _ANSI_RE.sub("", text)


def _resolve_claude_path() -> str:
    """Resolve the absolute path to the ``claude`` CLI binary.

    Order:
      1. ``$CLAUDE_CLI_PATH`` env var (if set and exists)
      2. ``shutil.which('claude')``
      3. Hardcoded fallbacks: ``~/.npm-global/bin/claude``, ``/opt/homebrew/bin/claude``,
         ``~/.local/bin/claude``, ``/usr/local/bin/claude``
    """
    env_path = os.environ.get("CLAUDE_CLI_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file() or candidate.is_symlink():
            return str(candidate)

    found = shutil.which("claude")
    if found:
        return found

    fallbacks = [
        Path.home() / ".npm-global" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
    ]
    for p in fallbacks:
        if p.is_file() or p.is_symlink():
            return str(p)

    raise RuntimeError(
        "Cannot locate the `claude` CLI. Tried: $CLAUDE_CLI_PATH="
        f"{env_path!r}, shutil.which('claude'), fallbacks={[str(p) for p in fallbacks]}"
    )


def _run(
    cmd: list[str],
    *,
    input_text: Optional[str] = None,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess:
    """Run a subprocess capturing stdout+stderr without raising on non-zero exit."""
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _check(
    cmd: list[str],
    *,
    input_text: Optional[str] = None,
    timeout: float = 10.0,
) -> str:
    """Run a subprocess; raise RuntimeError with full context on non-zero exit."""
    result = _run(cmd, input_text=input_text, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(shlex.quote(c) for c in cmd)} "
            f"(rc={result.returncode}) "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return result.stdout


@dataclass
class SessionInfo:
    agent_id: str
    session_name: str
    workdir: str
    system_prompt: str
    created_at: float = field(default_factory=time.time)


class TmuxSupervisor:
    """Pool of long-lived claude CLI sessions running inside named tmux sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _session_name(agent_id: str) -> str:
        return f"borina-p{PANE_NUMBER}-{agent_id}"

    def _tmux_session_exists(self, session_name: str) -> bool:
        result = _run(["tmux", "has-session", "-t", session_name], timeout=5.0)
        return result.returncode == 0

    def session_exists(self, agent_id: str) -> bool:
        return self._tmux_session_exists(self._session_name(agent_id))

    def spawn(self, agent_id: str, workdir: str, system_prompt: str) -> SessionInfo:
        """Spawn a tmux session running ``claude --dangerously-skip-permissions``.

        Re-adopts an existing tmux session if one with the namespaced name already
        exists (so an API restart doesn't break long-running agents).
        """
        session_name = self._session_name(agent_id)
        with self._lock:
            workdir_path = Path(workdir).expanduser().resolve()
            workdir_path.mkdir(parents=True, exist_ok=True)

            try:
                (workdir_path / "CLAUDE.md").write_text(
                    f"# Agent system prompt — {agent_id}\n\n{system_prompt}\n",
                    encoding="utf-8",
                )
            except OSError as e:
                raise RuntimeError(
                    f"failed to write CLAUDE.md in {workdir_path}: {type(e).__name__}: {e!r}"
                ) from e

            info = SessionInfo(
                agent_id=agent_id,
                session_name=session_name,
                workdir=str(workdir_path),
                system_prompt=system_prompt,
            )

            if self._tmux_session_exists(session_name):
                self._sessions[agent_id] = info
                return info

            claude_path = _resolve_claude_path()
            launch_cmd = f"{shlex.quote(claude_path)} --dangerously-skip-permissions"

            create = _run(
                [
                    "tmux", "new-session",
                    "-d",
                    "-s", session_name,
                    "-c", str(workdir_path),
                    "-x", "220", "-y", "50",
                    launch_cmd,
                ],
                timeout=15.0,
            )
            if create.returncode != 0:
                raise RuntimeError(
                    f"tmux new-session failed for {session_name!r}: "
                    f"rc={create.returncode} stdout={create.stdout!r} "
                    f"stderr={create.stderr!r} cmd={launch_cmd!r} "
                    f"cwd={workdir_path!s}"
                )

            self._sessions[agent_id] = info
            self._dismiss_first_run_dialogs(session_name)
            return info

    def _dismiss_first_run_dialogs(self, session_name: str, max_wait: float = 8.0) -> None:
        """Auto-press Enter to clear claude's first-run "trust this folder" dialog.

        Claude shows a trust dialog the first time it opens a workspace path. The
        ``--dangerously-skip-permissions`` flag silences per-tool permission prompts
        but not the trust dialog. We poll the pane for trust-dialog markers and send
        Enter once if we see them — otherwise the REPL would block on the dialog and
        any prompts we send would be typed into the dialog as text.
        """
        deadline = time.monotonic() + max_wait
        dismissed = False
        while time.monotonic() < deadline:
            time.sleep(0.4)
            try:
                cap = _run(
                    ["tmux", "capture-pane", "-p", "-t", session_name, "-S", "-50"],
                    timeout=5.0,
                )
            except subprocess.TimeoutExpired:
                continue
            if cap.returncode != 0:
                continue
            pane = strip_ansi(cap.stdout).lower()
            if not dismissed and (
                "trust this folder" in pane
                or "yes, i trust" in pane
                or "is this a project you created" in pane
            ):
                _run(["tmux", "send-keys", "-t", session_name, "Enter"], timeout=5.0)
                dismissed = True
                continue
            # If claude's input prompt indicator is showing, we're ready.
            if "│ >" in pane or " >  try" in pane or "shortcuts" in pane:
                return
        # Timed out — caller's wait_for_idle will surface any remaining issue.
        return

    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Send a (possibly multi-line) prompt via load-buffer + paste-buffer + Enter.

        Uses bracketed-paste mode (``-p``) so the claude REPL receives the full prompt
        as one input rather than line-by-line submissions.
        """
        session_name = self._session_name(agent_id)
        if not self._tmux_session_exists(session_name):
            raise RuntimeError(
                f"cannot send prompt: session {session_name!r} for agent {agent_id!r} "
                f"does not exist (spawn first)"
            )

        buf_name = f"borina-buf-{uuid.uuid4().hex[:10]}"

        load = _run(
            ["tmux", "load-buffer", "-b", buf_name, "-"],
            input_text=prompt,
            timeout=5.0,
        )
        if load.returncode != 0:
            raise RuntimeError(
                f"tmux load-buffer failed: rc={load.returncode} "
                f"stdout={load.stdout!r} stderr={load.stderr!r} buf={buf_name!r}"
            )

        try:
            paste = _run(
                ["tmux", "paste-buffer", "-t", session_name, "-b", buf_name, "-p", "-d"],
                timeout=5.0,
            )
            if paste.returncode != 0:
                raise RuntimeError(
                    f"tmux paste-buffer failed: rc={paste.returncode} "
                    f"stdout={paste.stdout!r} stderr={paste.stderr!r} "
                    f"target={session_name!r} buf={buf_name!r}"
                )
        except Exception:
            _run(["tmux", "delete-buffer", "-b", buf_name], timeout=5.0)
            raise

        # Small delay so the bracketed paste lands fully before we send Enter.
        time.sleep(0.4)

        enter = _run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            timeout=5.0,
        )
        if enter.returncode != 0:
            raise RuntimeError(
                f"tmux send-keys Enter failed: rc={enter.returncode} "
                f"stdout={enter.stdout!r} stderr={enter.stderr!r} "
                f"target={session_name!r}"
            )

    def capture(self, agent_id: str, lines: int = 200) -> str:
        """Capture the last ``lines`` lines of the pane, with ANSI codes stripped."""
        session_name = self._session_name(agent_id)
        if not self._tmux_session_exists(session_name):
            raise RuntimeError(
                f"cannot capture: session {session_name!r} for agent {agent_id!r} "
                f"does not exist"
            )

        result = _run(
            [
                "tmux", "capture-pane",
                "-p", "-t", session_name,
                "-S", f"-{int(lines)}",
            ],
            timeout=5.0,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tmux capture-pane failed: rc={result.returncode} "
                f"stdout={result.stdout!r} stderr={result.stderr!r} "
                f"target={session_name!r}"
            )
        return strip_ansi(result.stdout)

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: float = 4.0,
        timeout_seconds: float = 60.0,
    ) -> str:
        """Block until the pane has been unchanged for ``idle_seconds`` (rolling window).

        Heuristic: claude is still working as long as the pane keeps changing; once it
        stops printing for the configured idle window the response is considered
        complete. On overall timeout, returns the most recent capture rather than
        raising — caller can treat the partial output as best-effort.
        """
        deadline = time.monotonic() + timeout_seconds
        last_text = ""
        last_change = time.monotonic()
        first = True

        while time.monotonic() < deadline:
            try:
                current = self.capture(agent_id, lines=400)
            except RuntimeError:
                # Session vanished mid-wait — return what we had.
                return last_text

            if first:
                last_text = current
                last_change = time.monotonic()
                first = False
            elif current != last_text:
                last_text = current
                last_change = time.monotonic()
            elif (time.monotonic() - last_change) >= idle_seconds:
                return current

            time.sleep(0.5)

        return last_text

    def restart(self, agent_id: str) -> SessionInfo:
        """Kill and respawn the agent's session in the same workdir with the same prompt."""
        info = self._sessions.get(agent_id)
        if info is None:
            raise RuntimeError(
                f"agent {agent_id!r} is not known to the supervisor (call spawn first); "
                f"known agents: {sorted(self._sessions)}"
            )
        self.kill(agent_id)
        return self.spawn(agent_id, info.workdir, info.system_prompt)

    def kill(self, agent_id: str) -> bool:
        """Kill the tmux session if it exists; clear any local registry entry. Returns True if a session was killed."""
        session_name = self._session_name(agent_id)
        if not self._tmux_session_exists(session_name):
            self._sessions.pop(agent_id, None)
            return False
        result = _run(["tmux", "kill-session", "-t", session_name], timeout=5.0)
        if result.returncode != 0:
            raise RuntimeError(
                f"tmux kill-session failed: rc={result.returncode} "
                f"stdout={result.stdout!r} stderr={result.stderr!r} "
                f"target={session_name!r}"
            )
        self._sessions.pop(agent_id, None)
        return True

    def list_sessions(self) -> list[dict]:
        """Snapshot of all sessions the supervisor knows about, with liveness."""
        out: list[dict] = []
        for agent_id, info in self._sessions.items():
            out.append({
                "agent_id": agent_id,
                "session_name": info.session_name,
                "workdir": info.workdir,
                "alive": self._tmux_session_exists(info.session_name),
                "created_at": info.created_at,
            })
        return out


_singleton: TmuxSupervisor | None = None
_singleton_lock = threading.Lock()


def get_supervisor() -> TmuxSupervisor:
    """Module-level singleton accessor."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = TmuxSupervisor()
    return _singleton
