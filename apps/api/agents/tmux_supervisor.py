"""Pool manager for long-lived `claude` CLI sessions running inside tmux.

Each agent has one tmux session whose only window runs `claude` interactively
with --dangerously-skip-permissions. Prompts are injected with `tmux load-buffer`
+ `paste-buffer` (so multi-line input stays a single buffer) followed by an
explicit Enter. Output is read with `tmux capture-pane`.

Session names are namespaced as `borina-p{PANE}-{agent_id}` so the eight
parallel refactor instances cannot collide.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]")
PANE_NUMBER = os.environ.get("BORINA_PANE_NUMBER", "0")
SESSION_PREFIX = f"borina-p{PANE_NUMBER}"

_FALLBACK_CLAUDE_PATHS = (
    str(Path.home() / ".local" / "bin" / "claude"),
    str(Path.home() / ".npm-global" / "bin" / "claude"),
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _resolve_claude_path() -> str:
    explicit = os.environ.get("CLAUDE_CLI_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    for candidate in _FALLBACK_CLAUDE_PATHS:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError(
        "Cannot locate claude CLI. "
        f"Tried CLAUDE_CLI_PATH={explicit!r}, shutil.which=None, "
        f"fallbacks={list(_FALLBACK_CLAUDE_PATHS)}. "
        f"PATH={os.environ.get('PATH')}"
    )


def _run(cmd: list[str], *, check: bool = True, input_data: Optional[bytes] = None) -> subprocess.CompletedProcess:
    """Run a subprocess; on failure raise RuntimeError with the full context."""
    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"command not found: {cmd[0]!r} (cmd={cmd!r}, PATH={os.environ.get('PATH')})"
        ) from e
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        raise RuntimeError(
            f"command {cmd!r} failed (exit={result.returncode}): "
            f"stderr={stderr!r} stdout={stdout!r}"
        )
    return result


@dataclass
class SessionInfo:
    agent_id: str
    session_name: str
    workdir: str
    system_prompt: str
    started_at: float


class TmuxSupervisor:
    """Manage long-lived tmux sessions running `claude` interactively.

    Public surface (matches Step 2 spec):
        spawn(agent_id, workdir, system_prompt) -> SessionInfo
        send_prompt(agent_id, prompt) -> None
        capture(agent_id, lines=200) -> str
        wait_for_idle(agent_id, idle_seconds=4, timeout_seconds=600) -> str
        restart(agent_id) -> SessionInfo
        kill(agent_id) -> None
        list_sessions() -> list[dict]
        session_exists(agent_id) -> bool
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._lock = threading.RLock()
        self._tmux = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
        if not Path(self._tmux).exists():
            raise RuntimeError(
                f"tmux not found at {self._tmux!r} and not on PATH={os.environ.get('PATH')}"
            )

    # ───────────────────────── helpers ────────────────────────────
    def _name(self, agent_id: str) -> str:
        return f"{SESSION_PREFIX}-{agent_id}"

    def _tmux_session_exists(self, name: str) -> bool:
        result = _run([self._tmux, "has-session", "-t", name], check=False)
        return result.returncode == 0

    def _require(self, agent_id: str) -> SessionInfo:
        with self._lock:
            info = self._sessions.get(agent_id)
        if info is None:
            raise KeyError(f"agent {agent_id!r} is not known to the supervisor")
        if not self._tmux_session_exists(info.session_name):
            raise RuntimeError(
                f"tmux session {info.session_name!r} disappeared "
                f"(agent={agent_id!r}); call restart() to revive it"
            )
        return info

    # ───────────────────────── lifecycle ──────────────────────────
    def spawn(self, agent_id: str, workdir: str, system_prompt: str) -> SessionInfo:
        """Start (or re-adopt) a tmux session running claude for this agent."""
        with self._lock:
            session_name = self._name(agent_id)
            Path(workdir).mkdir(parents=True, exist_ok=True)

            if self._tmux_session_exists(session_name):
                info = self._sessions.get(agent_id) or SessionInfo(
                    agent_id=agent_id,
                    session_name=session_name,
                    workdir=workdir,
                    system_prompt=system_prompt,
                    started_at=time.time(),
                )
                self._sessions[agent_id] = info
                return info

            claude_path = _resolve_claude_path()
            cmd_parts = [
                claude_path,
                "--dangerously-skip-permissions",
            ]
            if system_prompt:
                cmd_parts += ["--append-system-prompt", system_prompt]
            shell_cmd = " ".join(_quote(p) for p in cmd_parts)

            _run([
                self._tmux, "new-session",
                "-d",
                "-s", session_name,
                "-c", workdir,
                "-x", "220", "-y", "50",
                shell_cmd,
            ])

            info = SessionInfo(
                agent_id=agent_id,
                session_name=session_name,
                workdir=workdir,
                system_prompt=system_prompt,
                started_at=time.time(),
            )
            self._sessions[agent_id] = info
            self._dismiss_workspace_trust(info)
            return info

    def _dismiss_workspace_trust(self, info: SessionInfo, deadline_s: float = 8.0) -> None:
        """Auto-confirm the 'Is this a project you trust?' prompt that appears
        on first launch in a new workdir. We just press Enter on the default
        ('Yes, I trust this folder') if we see the trust banner.
        """
        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            try:
                screen = self.capture(info.agent_id, lines=80)
            except Exception:
                time.sleep(0.25)
                continue
            if "trust this folder" in screen.lower() or "is this a project" in screen.lower():
                _run([self._tmux, "send-keys", "-t", info.session_name, "Enter"], check=False)
                time.sleep(0.5)
                # Sometimes one Enter just selects; send a second after a beat
                # if the banner is still there.
                screen2 = self.capture(info.agent_id, lines=80)
                if "trust this folder" in screen2.lower():
                    _run([self._tmux, "send-keys", "-t", info.session_name, "Enter"], check=False)
                    time.sleep(0.5)
                return
            time.sleep(0.3)

    def kill(self, agent_id: str) -> None:
        with self._lock:
            info = self._sessions.pop(agent_id, None)
        if info is not None and self._tmux_session_exists(info.session_name):
            _run([self._tmux, "kill-session", "-t", info.session_name], check=False)

    def restart(self, agent_id: str) -> SessionInfo:
        with self._lock:
            info = self._sessions.get(agent_id)
        if info is None:
            raise KeyError(f"agent {agent_id!r} is not known to the supervisor")
        self.kill(agent_id)
        return self.spawn(agent_id, info.workdir, info.system_prompt)

    def session_exists(self, agent_id: str) -> bool:
        with self._lock:
            info = self._sessions.get(agent_id)
        if info is None:
            return False
        return self._tmux_session_exists(info.session_name)

    def list_sessions(self) -> list[dict]:
        with self._lock:
            items = list(self._sessions.values())
        out: list[dict] = []
        for info in items:
            out.append({
                "agent_id": info.agent_id,
                "session_name": info.session_name,
                "workdir": info.workdir,
                "alive": self._tmux_session_exists(info.session_name),
                "started_at": info.started_at,
            })
        return out

    # ───────────────────────── I/O ────────────────────────────────
    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Inject a (possibly multi-line) prompt into the agent's claude session."""
        info = self._require(agent_id)

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".tmuxbuf", delete=False
        ) as f:
            f.write(prompt)
            buf_path = f.name

        try:
            _run([self._tmux, "load-buffer", "-b", info.session_name + "-buf", buf_path])
            _run([self._tmux, "paste-buffer", "-d", "-b", info.session_name + "-buf",
                  "-t", info.session_name])
            _run([self._tmux, "send-keys", "-t", info.session_name, "Enter"])
        finally:
            try:
                os.unlink(buf_path)
            except OSError:
                pass

    def capture(self, agent_id: str, lines: int = 200) -> str:
        """Capture the last N lines of the agent's pane, ANSI-stripped."""
        info = self._require(agent_id)
        result = _run([
            self._tmux, "capture-pane",
            "-p", "-t", info.session_name,
            "-S", f"-{int(lines)}",
        ])
        raw = result.stdout.decode("utf-8", errors="replace")
        return _strip_ansi(raw)

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: float = 4.0,
        timeout_seconds: float = 600.0,
        capture_lines: int = 400,
        poll_interval: float = 0.5,
    ) -> str:
        """Block until the pane content stops changing for `idle_seconds`.

        Returns the final captured pane text. On timeout, returns whatever has
        been captured so far rather than raising — the runner decides how to
        treat partial output.
        """
        start = time.monotonic()
        last_change = start
        last_snapshot = self.capture(agent_id, lines=capture_lines)

        while True:
            now = time.monotonic()
            if now - start > timeout_seconds:
                return last_snapshot
            time.sleep(poll_interval)
            current = self.capture(agent_id, lines=capture_lines)
            if current != last_snapshot:
                last_change = time.monotonic()
                last_snapshot = current
                continue
            if time.monotonic() - last_change >= idle_seconds:
                return current


def _quote(part: str) -> str:
    """Single-quote a shell argument for use in a `tmux new-session ... <cmd>` string."""
    if not part:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-_~" for c in part):
        return part
    escaped = part.replace("'", "'\"'\"'")
    return f"'{escaped}'"


# Module-level singleton
_supervisor: Optional[TmuxSupervisor] = None
_supervisor_lock = threading.Lock()


def get_supervisor() -> TmuxSupervisor:
    global _supervisor
    if _supervisor is None:
        with _supervisor_lock:
            if _supervisor is None:
                _supervisor = TmuxSupervisor()
    return _supervisor
