"""Tmux Supervisor — pool manager for long-lived `claude` CLI sessions.

Each agent runs inside its own named tmux session executing
`claude --dangerously-skip-permissions` indefinitely. Prompts are pasted into
the live TUI; output is captured by scraping the pane.

Sessions are namespaced with the pane number (`borina-p<N>-<agent_id>`) so
multiple parallel refactor instances on the same machine don't collide on
tmux session names during verification.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PANE_NUMBER = os.environ.get("BORINA_PANE_NUMBER", "0")
SESSION_PREFIX = f"borina-p{PANE_NUMBER}-"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]|\x1b[=>]|[\x00-\x08\x0b-\x1f\x7f]")
_CLAUDE_FALLBACKS = ("~/.npm-global/bin/claude", "/opt/homebrew/bin/claude", "~/.local/bin/claude")


def _resolve_claude_path() -> str:
    """Find the claude CLI: env > PATH > hardcoded fallbacks."""
    explicit = os.environ.get("CLAUDE_CLI_PATH", "").strip()
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    found = shutil.which("claude")
    if found:
        return found
    for cand in _CLAUDE_FALLBACKS:
        p = Path(os.path.expanduser(cand))
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    raise RuntimeError(
        "claude CLI not found — set CLAUDE_CLI_PATH or install it on PATH "
        "(checked env, $PATH, ~/.npm-global/bin/claude, /opt/homebrew/bin/claude, ~/.local/bin/claude)"
    )


def _run(cmd: list[str], *, input_bytes: bytes | None = None, timeout: float = 30.0) -> tuple[int, str, str]:
    """Run a shell command, capture both streams, return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"command timed out after {timeout}s: {shlex.join(cmd)}") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"command not found: {shlex.join(cmd)} ({e})") from e


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and most control bytes from captured pane text."""
    return _ANSI_RE.sub("", text)


@dataclass
class SessionInfo:
    agent_id: str
    session_name: str
    workdir: str
    system_prompt: str
    created_at: float = field(default_factory=time.time)


class TmuxSupervisor:
    """Pool manager for claude tmux sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._lock = threading.Lock()
        if not shutil.which("tmux"):
            raise RuntimeError("tmux is not installed — install via `brew install tmux`")

    def _session_name(self, agent_id: str) -> str:
        return f"{SESSION_PREFIX}{agent_id}"

    def _tmux_has_session(self, name: str) -> bool:
        rc, _, _ = _run(["tmux", "has-session", "-t", name])
        return rc == 0

    def session_exists(self, agent_id: str) -> bool:
        return self._tmux_has_session(self._session_name(agent_id))

    def list_sessions(self) -> list[dict]:
        rc, out, err = _run(["tmux", "list-sessions", "-F", "#{session_name}|#{session_created}"])
        if rc != 0 and "no server running" not in err.lower():
            raise RuntimeError(f"tmux list-sessions failed (rc={rc}): {err.strip() or out.strip()}")
        results: list[dict] = []
        for line in (out or "").splitlines():
            line = line.strip()
            if not line.startswith(SESSION_PREFIX):
                continue
            name, _, created = line.partition("|")
            agent_id = name[len(SESSION_PREFIX):]
            info = self._sessions.get(agent_id)
            results.append({
                "agent_id": agent_id,
                "session_name": name,
                "created_at": created,
                "workdir": info.workdir if info else None,
                "tracked": info is not None,
            })
        return results

    def spawn(self, agent_id: str, workdir: str, system_prompt: str) -> SessionInfo:
        """Create (or re-adopt) a tmux session running `claude` interactively."""
        if not agent_id or not re.fullmatch(r"[a-zA-Z0-9_\-]+", agent_id):
            raise RuntimeError(f"invalid agent_id {agent_id!r} — must match [a-zA-Z0-9_-]+")

        name = self._session_name(agent_id)
        wd = Path(os.path.expanduser(workdir)).resolve()
        wd.mkdir(parents=True, exist_ok=True)

        with self._lock:
            # Re-adopt: if tmux already has the session, just register it.
            if self._tmux_has_session(name):
                info = self._sessions.get(agent_id) or SessionInfo(
                    agent_id=agent_id,
                    session_name=name,
                    workdir=str(wd),
                    system_prompt=system_prompt,
                )
                self._sessions[agent_id] = info
                return info

            claude_bin = _resolve_claude_path()
            cmd_parts = [claude_bin, "--dangerously-skip-permissions"]
            if system_prompt:
                cmd_parts += ["--append-system-prompt", system_prompt]
            shell_cmd = shlex.join(cmd_parts)

            rc, out, err = _run([
                "tmux", "new-session", "-d",
                "-s", name,
                "-c", str(wd),
                "-x", "220", "-y", "50",
                shell_cmd,
            ])
            if rc != 0:
                raise RuntimeError(
                    f"tmux new-session failed for {name!r} (rc={rc}): "
                    f"stderr={err.strip()!r} stdout={out.strip()!r} cmd={shell_cmd!r}"
                )

            info = SessionInfo(
                agent_id=agent_id,
                session_name=name,
                workdir=str(wd),
                system_prompt=system_prompt,
            )
            self._sessions[agent_id] = info
            # The interactive TUI shows a "trust this folder?" dialog even with
            # --dangerously-skip-permissions (per `claude --help`, that flag
            # only skips it in --print mode). Auto-confirm it once on first
            # spawn so callers don't have to.
            self._auto_confirm_trust(name)
            return info

    def _auto_confirm_trust(self, name: str, attempts: int = 6) -> None:
        """Wait for the TUI to draw and dismiss the workspace-trust dialog if visible."""
        for _ in range(attempts):
            time.sleep(1.0)
            try:
                rc, out, _ = _run(
                    ["tmux", "capture-pane", "-p", "-t", name, "-S", "-50", "-E", "-"],
                    timeout=5,
                )
                if rc != 0:
                    return
            except RuntimeError:
                return
            text = _strip_ansi(out)
            if "trust this folder" in text.lower() or "do you trust" in text.lower():
                # Default highlight is "1. Yes, I trust this folder" — Enter confirms.
                _run(["tmux", "send-keys", "-t", name, "Enter"], timeout=5)
                # Give the TUI a beat to redraw before any subsequent send_prompt.
                time.sleep(1.0)
                return
            # If we already see the bypass-permissions banner, we're past the dialog.
            if "bypass permissions" in text.lower():
                return

    def kill(self, agent_id: str) -> bool:
        """Kill the agent's tmux session. Returns True if killed, False if didn't exist."""
        name = self._session_name(agent_id)
        with self._lock:
            self._sessions.pop(agent_id, None)
            if not self._tmux_has_session(name):
                return False
            rc, out, err = _run(["tmux", "kill-session", "-t", name])
            if rc != 0:
                raise RuntimeError(f"tmux kill-session failed for {name!r} (rc={rc}): {err.strip() or out.strip()}")
            return True

    def restart(self, agent_id: str) -> SessionInfo:
        """Kill and respawn using the previously registered workdir + system_prompt."""
        info = self._sessions.get(agent_id)
        if not info:
            raise RuntimeError(
                f"agent {agent_id!r} is not known — spawn() must be called once before restart()"
            )
        self.kill(agent_id)
        # Small delay so tmux fully reclaims the socket entry.
        time.sleep(0.2)
        return self.spawn(agent_id, info.workdir, info.system_prompt)

    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Paste the prompt into the live TUI and submit with Enter.

        Multi-line prompts go through a tmp buffer to avoid send-keys limits and
        to preserve newlines literally instead of having tmux interpret them.
        """
        name = self._session_name(agent_id)
        if not self._tmux_has_session(name):
            raise RuntimeError(f"tmux session {name!r} does not exist — spawn() first")

        # Write prompt to a temp file, load it as a tmux buffer, paste, then Enter.
        buf_name = f"borina-{agent_id}-{int(time.time() * 1000)}"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as tf:
            tf.write(prompt)
            tmp_path = tf.name
        try:
            rc, _, err = _run(["tmux", "load-buffer", "-b", buf_name, tmp_path])
            if rc != 0:
                raise RuntimeError(f"tmux load-buffer failed (rc={rc}): {err.strip()!r}")

            rc, _, err = _run(["tmux", "paste-buffer", "-b", buf_name, "-t", name, "-d"])
            if rc != 0:
                raise RuntimeError(f"tmux paste-buffer failed (rc={rc}): {err.strip()!r}")

            # Small pause so the TUI registers the pasted text before Enter.
            time.sleep(0.25)
            rc, _, err = _run(["tmux", "send-keys", "-t", name, "Enter"])
            if rc != 0:
                raise RuntimeError(f"tmux send-keys Enter failed (rc={rc}): {err.strip()!r}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def capture(self, agent_id: str, lines: int = 200) -> str:
        """Capture the last `lines` of the agent's pane, ANSI-stripped."""
        name = self._session_name(agent_id)
        if not self._tmux_has_session(name):
            raise RuntimeError(f"tmux session {name!r} does not exist — spawn() first")
        # -p: stdout, -S -<lines>: start lines back, -E -: through end of visible
        rc, out, err = _run(["tmux", "capture-pane", "-p", "-t", name, "-S", f"-{lines}", "-E", "-"])
        if rc != 0:
            raise RuntimeError(f"tmux capture-pane failed (rc={rc}): {err.strip() or out.strip()}")
        return _strip_ansi(out)

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: float = 4.0,
        timeout_seconds: float = 600.0,
        poll_interval: float = 0.5,
    ) -> tuple[bool, str]:
        """Block until the pane stops changing for `idle_seconds`, or timeout.

        Returns (idle_reached, captured_text). On timeout, idle_reached=False
        and captured_text holds whatever was visible at the deadline.
        """
        deadline = time.time() + timeout_seconds
        last_text = self.capture(agent_id, lines=400)
        last_change = time.time()
        while time.time() < deadline:
            time.sleep(poll_interval)
            try:
                cur_text = self.capture(agent_id, lines=400)
            except RuntimeError:
                # Session vanished — return whatever we last had.
                return False, last_text
            if cur_text != last_text:
                last_text = cur_text
                last_change = time.time()
            elif time.time() - last_change >= idle_seconds:
                return True, last_text
        return False, last_text


_supervisor: Optional[TmuxSupervisor] = None
_supervisor_lock = threading.Lock()


def get_supervisor() -> TmuxSupervisor:
    """Return the module-level singleton supervisor (lazily initialized)."""
    global _supervisor
    if _supervisor is None:
        with _supervisor_lock:
            if _supervisor is None:
                _supervisor = TmuxSupervisor()
    return _supervisor
