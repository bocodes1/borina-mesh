"""Tmux pool manager for long-lived `claude` CLI sessions.

Each agent runs as `claude --dangerously-skip-permissions` inside its own
tmux session, namespaced by pane number so multiple parallel borina-mesh
worktrees can coexist without colliding on session names.

Public surface:
    supervisor = get_supervisor()
    supervisor.spawn(agent_id, workdir, system_prompt)
    supervisor.send_prompt(agent_id, prompt)
    supervisor.wait_for_idle(agent_id, idle_seconds, timeout_seconds)
    supervisor.capture(agent_id, lines)
    supervisor.restart(agent_id)
    supervisor.kill(agent_id)
    supervisor.list_sessions()
    supervisor.session_exists(agent_id)
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


_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from captured pane text."""
    return _ANSI_RE.sub("", text)


def _pane_number() -> str:
    """Pane suffix for tmux namespacing. Defaults to 0 if unset."""
    return os.environ.get("PANE_NUMBER", "0")


def _session_name(agent_id: str) -> str:
    """Pane-namespaced tmux session name."""
    return f"borina-p{_pane_number()}-{agent_id}"


def _resolve_claude_path() -> str:
    """Resolve absolute path to the `claude` CLI binary.

    Order: CLAUDE_CLI_PATH env → shutil.which → known fallbacks.
    Raises RuntimeError with the search order if not found.
    """
    env_path = os.environ.get("CLAUDE_CLI_PATH")
    if env_path and Path(env_path).is_file() and os.access(env_path, os.X_OK):
        return env_path

    found = shutil.which("claude")
    if found:
        return found

    fallbacks = [
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.npm-global/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ]
    for cand in fallbacks:
        if Path(cand).is_file() and os.access(cand, os.X_OK):
            return cand

    raise RuntimeError(
        "claude CLI not found. Searched: $CLAUDE_CLI_PATH=%r, shutil.which('claude'), %r. "
        "Set CLAUDE_CLI_PATH or install claude." % (env_path, fallbacks)
    )


def _run(cmd: list[str], *, input_data: Optional[bytes] = None, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Run a subprocess and raise RuntimeError with full context on failure."""
    try:
        proc = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"command not found: {cmd[0]} ({e!r})") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"timeout after {timeout}s running {shlex.join(cmd)}: stderr={(e.stderr or b'').decode(errors='replace')!r}"
        ) from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={proc.returncode}): {shlex.join(cmd)}\n"
            f"  stdout={proc.stdout.decode(errors='replace')!r}\n"
            f"  stderr={proc.stderr.decode(errors='replace')!r}"
        )
    return proc


@dataclass
class SessionRecord:
    agent_id: str
    session: str
    workdir: str
    system_prompt: str
    started_at: float = field(default_factory=time.time)


class TmuxSupervisor:
    """Pool manager for tmux-hosted claude CLI sessions."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._lock = threading.Lock()
        self._tmux = shutil.which("tmux") or "/opt/homebrew/bin/tmux"

    # ── identity ────────────────────────────────────────────────────────
    def session_name(self, agent_id: str) -> str:
        return _session_name(agent_id)

    def session_exists(self, agent_id: str) -> bool:
        name = _session_name(agent_id)
        proc = subprocess.run(
            [self._tmux, "has-session", "-t", name],
            capture_output=True,
        )
        return proc.returncode == 0

    # ── lifecycle ───────────────────────────────────────────────────────
    def spawn(self, agent_id: str, workdir: str, system_prompt: str) -> SessionRecord:
        """Spawn a new tmux session running claude. Re-adopts if it already exists."""
        with self._lock:
            name = _session_name(agent_id)
            Path(workdir).mkdir(parents=True, exist_ok=True)

            already = self._records.get(agent_id)
            if already and self.session_exists(agent_id):
                return already

            if self.session_exists(agent_id):
                # External session — re-adopt without restart so API restarts are safe.
                rec = SessionRecord(
                    agent_id=agent_id,
                    session=name,
                    workdir=workdir,
                    system_prompt=system_prompt,
                )
                self._records[agent_id] = rec
                return rec

            claude_bin = _resolve_claude_path()
            # New detached tmux session at workdir, large geometry so claude's TUI doesn't wrap weirdly.
            _run([
                self._tmux, "new-session", "-d",
                "-s", name,
                "-c", workdir,
                "-x", "220", "-y", "50",
            ])

            cmd_parts = [shlex.quote(claude_bin), "--dangerously-skip-permissions"]
            if system_prompt:
                cmd_parts += ["--append-system-prompt", shlex.quote(system_prompt)]
            launch_cmd = " ".join(cmd_parts)
            _run([self._tmux, "send-keys", "-t", name, launch_cmd, "Enter"])

            rec = SessionRecord(
                agent_id=agent_id,
                session=name,
                workdir=workdir,
                system_prompt=system_prompt,
            )
            self._records[agent_id] = rec
            return rec

    def kill(self, agent_id: str) -> None:
        name = _session_name(agent_id)
        with self._lock:
            self._records.pop(agent_id, None)
        proc = subprocess.run(
            [self._tmux, "kill-session", "-t", name],
            capture_output=True,
        )
        # kill-session returns nonzero if it doesn't exist — that's fine.
        if proc.returncode != 0 and b"can't find session" not in proc.stderr.lower() \
                and b"no such" not in proc.stderr.lower() \
                and b"session not found" not in proc.stderr.lower():
            stderr = proc.stderr.decode(errors="replace")
            if stderr.strip():
                raise RuntimeError(f"tmux kill-session failed for {name}: {stderr!r}")

    def restart(self, agent_id: str) -> SessionRecord:
        with self._lock:
            rec = self._records.get(agent_id)
        if not rec:
            raise KeyError(f"agent '{agent_id}' is not known to the supervisor")
        self.kill(agent_id)
        # tiny delay so tmux fully releases the session name
        time.sleep(0.3)
        return self.spawn(agent_id, rec.workdir, rec.system_prompt)

    # ── I/O ─────────────────────────────────────────────────────────────
    def _dismiss_pending_dialog(self, name: str) -> bool:
        """If claude is showing the 'Trust this folder?' or similar startup
        dialog, auto-confirm it. Returns True if a dialog was dismissed.

        Heuristic: capture pane, look for known dialog markers, send Enter
        and a short settle delay before returning.
        """
        try:
            proc = subprocess.run(
                [self._tmux, "capture-pane", "-p", "-J", "-t", name, "-S", "-80"],
                capture_output=True, timeout=5,
            )
            if proc.returncode != 0:
                return False
            text = _strip_ansi(proc.stdout.decode(errors="replace"))
        except Exception:
            return False

        # Trust-folder dialog has option "❯ 1. Yes, I trust this folder" with
        # Enter to confirm. The cursor sits on option 1 by default, so a
        # single Enter accepts.
        markers = [
            "trust this folder",
            "Yes, I trust this folder",
            "Is this a project you created",
        ]
        if any(m.lower() in text.lower() for m in markers):
            subprocess.run(
                [self._tmux, "send-keys", "-t", name, "Enter"],
                capture_output=True, timeout=5,
            )
            time.sleep(1.5)
            return True
        return False

    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Send a (possibly multi-line) prompt to the session and submit with Enter.

        Uses load-buffer + paste-buffer to preserve newlines, then send-keys Enter.
        Auto-dismisses claude's first-launch trust-folder dialog if present.
        """
        name = _session_name(agent_id)
        if not self.session_exists(agent_id):
            raise RuntimeError(f"tmux session {name!r} does not exist (was spawn() called?)")

        # Clear any startup dialog so the prompt isn't interpreted as a menu choice.
        if self._dismiss_pending_dialog(name):
            # Give claude a moment to render the regular input field.
            time.sleep(1.0)

        # Write prompt to a temp file so load-buffer can read it without shell quoting issues.
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".prompt", encoding="utf-8") as f:
            f.write(prompt)
            tmp_path = f.name

        buf_name = f"borina-{agent_id}-{int(time.time()*1000)}"
        try:
            _run([self._tmux, "load-buffer", "-b", buf_name, tmp_path])
            _run([self._tmux, "paste-buffer", "-b", buf_name, "-t", name, "-d"])
            # Small breather so claude's input field receives the paste before Enter.
            time.sleep(0.4)
            _run([self._tmux, "send-keys", "-t", name, "Enter"])
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def capture(self, agent_id: str, lines: int = 200) -> str:
        """Return the last `lines` lines of the pane, ANSI-stripped."""
        name = _session_name(agent_id)
        if not self.session_exists(agent_id):
            raise RuntimeError(f"tmux session {name!r} does not exist (was spawn() called?)")
        # -p prints to stdout, -S -N starts N lines back from the bottom of history,
        # -J joins wrapped lines so we get logical lines.
        proc = _run([
            self._tmux, "capture-pane",
            "-p", "-J",
            "-t", name,
            "-S", f"-{lines}",
        ])
        return _strip_ansi(proc.stdout.decode(errors="replace"))

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: float = 4.0,
        timeout_seconds: float = 600.0,
        poll_interval: float = 0.5,
    ) -> str:
        """Block until the pane content is unchanged for `idle_seconds`, or timeout.

        Returns the final captured output. On timeout, returns whatever was captured
        instead of raising — callers can decide whether the partial result is useful.
        """
        deadline = time.time() + timeout_seconds
        last = self.capture(agent_id, lines=400)
        last_change = time.time()
        while time.time() < deadline:
            time.sleep(poll_interval)
            current = self.capture(agent_id, lines=400)
            if current != last:
                last = current
                last_change = time.time()
                continue
            if (time.time() - last_change) >= idle_seconds:
                return current
        return last

    # ── inventory ───────────────────────────────────────────────────────
    def list_sessions(self) -> list[dict]:
        """Return metadata for every supervised session that currently exists in tmux."""
        out: list[dict] = []
        with self._lock:
            agents = list(self._records.items())
        for agent_id, rec in agents:
            out.append({
                "agent_id": agent_id,
                "session": rec.session,
                "workdir": rec.workdir,
                "system_prompt_chars": len(rec.system_prompt),
                "started_at": rec.started_at,
                "alive": self.session_exists(agent_id),
            })
        return out


_singleton: Optional[TmuxSupervisor] = None
_singleton_lock = threading.Lock()


def get_supervisor() -> TmuxSupervisor:
    """Module-level singleton accessor."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = TmuxSupervisor()
    return _singleton
