"""Long-lived tmux session pool for headless `claude` CLI agents.

Each agent gets one persistent tmux session running
`claude --dangerously-skip-permissions` in interactive (TUI) mode. The
supervisor spawns, prompts, captures, and kills these sessions, and re-adopts
existing tmux sessions across API restarts.

Session names are namespaced per pane so multiple parallel worktrees on the
same machine do not collide on tmux session names: ``borina-p<PANE>-<agent>``.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

# Strip ANSI escape sequences (CSI + OSC) from captured pane content.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)"
)
_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏◐◓◑◒"
_TIMER_RE = re.compile(r"\(\s*\d+s[\s·•]+esc to interrupt\s*\)", re.IGNORECASE)

def _pane_number() -> str:
    """Read pane id from env at call time so a `load_dotenv()` that runs
    after this module is imported still takes effect on session naming."""
    return os.environ.get("BORINA_PANE_NUMBER", "1")


def _session_prefix() -> str:
    return f"borina-p{_pane_number()}-"

_CLAUDE_FALLBACKS = [
    str(Path.home() / ".npm-global" / "bin" / "claude"),
    "/opt/homebrew/bin/claude",
    str(Path.home() / ".local" / "bin" / "claude"),
]


def _resolve_claude() -> str:
    """Resolve the absolute path to the `claude` CLI.

    Order: CLAUDE_CLI_PATH env var → shutil.which('claude') → hardcoded fallbacks.
    Raises RuntimeError with PATH context if not found.
    """
    env_path = os.environ.get("CLAUDE_CLI_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    found = shutil.which("claude")
    if found:
        return found
    for cand in _CLAUDE_FALLBACKS:
        if Path(cand).exists():
            return cand
    raise RuntimeError(
        "claude CLI not found. Set CLAUDE_CLI_PATH or install via "
        "`npm i -g @anthropic-ai/claude-code`. "
        f"PATH={os.environ.get('PATH')}"
    )


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _normalize_for_idle(text: str) -> str:
    """Strip animation/timer artifacts so wait_for_idle doesn't reset every frame."""
    if any(c in text for c in _SPINNER_CHARS):
        text = re.sub(f"[{_SPINNER_CHARS}]+", "", text)
    text = _TIMER_RE.sub("", text)
    return text


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a subprocess; capture stderr; raise RuntimeError with full context on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"binary not found: {cmd[0]} ({e}) | PATH={os.environ.get('PATH')}"
        ) from e
    if result.returncode != 0:
        raise RuntimeError(
            f"{shlex.join(cmd)} failed (exit {result.returncode}) | "
            f"stdout={result.stdout!r} | stderr={result.stderr!r}"
        )
    return result


@dataclass
class SessionInfo:
    agent_id: str
    session_name: str
    workdir: str
    system_prompt: str
    spawned_at: float


class TmuxSupervisor:
    """Manages a pool of long-lived tmux sessions, one per agent."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._lock = Lock()
        self._claude_path: Optional[str] = None

    # ── helpers ────────────────────────────────────────────────────────────

    def _claude(self) -> str:
        if self._claude_path is None:
            self._claude_path = _resolve_claude()
        return self._claude_path

    def _session_name(self, agent_id: str) -> str:
        return f"{_session_prefix()}{agent_id}"

    def _buffer_name(self, agent_id: str) -> str:
        # Unique per call so two concurrent send_prompt() calls on the same
        # agent cannot clobber each other's paste buffer.
        return f"borina-buf-{agent_id}-{uuid.uuid4().hex[:8]}"

    # ── public API ─────────────────────────────────────────────────────────

    def session_exists(self, agent_id: str) -> bool:
        name = self._session_name(agent_id)
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    def list_sessions(self) -> list[dict]:
        """Snapshot every borina-p{pane}-* session tmux currently owns.

        Queries tmux directly so externally created sessions and sessions
        that survived an API restart are still visible — not just the
        in-memory dict. In-memory metadata (workdir, spawned_at) is merged
        in when available.
        """
        prefix = _session_prefix()
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}|#{session_created}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # No tmux server running yet → no sessions.
            return []
        out: list[dict] = []
        with self._lock:
            for line in result.stdout.splitlines():
                name, _, created = line.strip().partition("|")
                if not name.startswith(prefix):
                    continue
                agent_id = name[len(prefix):]
                info = self._sessions.get(agent_id)
                out.append({
                    "agent_id": agent_id,
                    "session_name": name,
                    "workdir": info.workdir if info else None,
                    "spawned_at": info.spawned_at if info else (
                        float(created) if created.isdigit() else None
                    ),
                    "alive": True,
                    "tracked": info is not None,
                })
        return out

    def spawn(self, agent_id: str, workdir: str, system_prompt: str) -> SessionInfo:
        """Start a tmux session running `claude` in `workdir`.

        Re-adopts an already-running tmux session of the same name (e.g. across
        API restarts) instead of erroring out.
        """
        with self._lock:
            name = self._session_name(agent_id)
            workdir_path = Path(workdir).expanduser()
            workdir_path.mkdir(parents=True, exist_ok=True)
            workdir_resolved = str(workdir_path.resolve())

            if self.session_exists(agent_id):
                info = self._sessions.get(agent_id) or SessionInfo(
                    agent_id=agent_id,
                    session_name=name,
                    workdir=workdir_resolved,
                    system_prompt=system_prompt,
                    spawned_at=time.time(),
                )
                self._sessions[agent_id] = info
                return info

            claude = self._claude()
            cmd_in_pane = (
                f"cd {shlex.quote(workdir_resolved)} && "
                f"{shlex.quote(claude)} --dangerously-skip-permissions"
            )
            if system_prompt:
                cmd_in_pane += f" --append-system-prompt {shlex.quote(system_prompt)}"

            _run([
                "tmux", "new-session", "-d", "-s", name,
                "-x", "220", "-y", "50",
                "bash", "-lc", cmd_in_pane,
            ])

            info = SessionInfo(
                agent_id=agent_id,
                session_name=name,
                workdir=workdir_resolved,
                system_prompt=system_prompt,
                spawned_at=time.time(),
            )
            self._sessions[agent_id] = info
            return info

    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Send a (possibly multi-line) prompt and press Enter to submit."""
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"tmux session for agent '{agent_id}' does not exist; spawn first"
            )
        name = self._session_name(agent_id)
        buf = self._buffer_name(agent_id)

        # tmux load-buffer reads from stdin when path is "-".
        try:
            res = subprocess.run(
                ["tmux", "load-buffer", "-b", buf, "-"],
                input=prompt, text=True, capture_output=True,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"tmux not found: {e}") from e
        if res.returncode != 0:
            raise RuntimeError(
                f"tmux load-buffer failed (exit {res.returncode}) | "
                f"stderr={res.stderr!r}"
            )

        _run(["tmux", "paste-buffer", "-b", buf, "-d", "-t", name])
        # Brief settle so paste is fully reflected before Enter.
        time.sleep(0.3)
        _run(["tmux", "send-keys", "-t", name, "Enter"])

    def send_keys(self, agent_id: str, *keys: str) -> None:
        """Send raw tmux key sequences (e.g., ``send_keys(id, 'Enter')`` or
        ``send_keys(id, 'C-c')``). Used to dismiss modal dialogs without
        triggering the paste-buffer flow."""
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"tmux session for agent '{agent_id}' does not exist"
            )
        name = self._session_name(agent_id)
        _run(["tmux", "send-keys", "-t", name, *keys])

    def capture(self, agent_id: str, lines: int = 200) -> str:
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"tmux session for agent '{agent_id}' does not exist"
            )
        name = self._session_name(agent_id)
        # -p prints to stdout, -S -<n> starts at line n above the bottom.
        result = _run([
            "tmux", "capture-pane", "-p", "-t", name, "-S", f"-{int(lines)}",
        ])
        return _strip_ansi(result.stdout)

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: int = 4,
        timeout_seconds: int = 600,
    ) -> str:
        """Block until pane content is unchanged for `idle_seconds`.

        Returns the final captured output. On timeout returns the last capture
        (partial output) instead of raising — callers can inspect what came
        through.
        """
        deadline = time.time() + timeout_seconds
        last_norm = _normalize_for_idle(self.capture(agent_id, lines=400))
        last_change = time.time()
        while time.time() < deadline:
            time.sleep(0.5)
            current = self.capture(agent_id, lines=400)
            current_norm = _normalize_for_idle(current)
            if current_norm != last_norm:
                last_norm = current_norm
                last_change = time.time()
            elif time.time() - last_change >= idle_seconds:
                return current
        # Timeout — return whatever we have.
        return self.capture(agent_id, lines=400)

    def restart(self, agent_id: str) -> SessionInfo:
        """Kill and re-spawn an agent's session, preserving workdir and system prompt."""
        with self._lock:
            info = self._sessions.get(agent_id)
            if info is None and not self.session_exists(agent_id):
                raise KeyError(f"agent_id '{agent_id}' is not known to supervisor")
            workdir = info.workdir if info else str(
                Path.home() / ".borina" / "agents" / f"p{_pane_number()}" / agent_id
            )
            system_prompt = info.system_prompt if info else ""
            name = self._session_name(agent_id)
            subprocess.run(
                ["tmux", "kill-session", "-t", name],
                capture_output=True, text=True,
            )
            self._sessions.pop(agent_id, None)
        # Spawn outside the lock to avoid holding it during a sleep.
        return self.spawn(agent_id, workdir, system_prompt)

    def kill(self, agent_id: str) -> bool:
        """Kill a session if it exists. Returns True if a session was killed."""
        with self._lock:
            existed = self.session_exists(agent_id)
            name = self._session_name(agent_id)
            subprocess.run(
                ["tmux", "kill-session", "-t", name],
                capture_output=True, text=True,
            )
            self._sessions.pop(agent_id, None)
            return existed


_singleton: Optional[TmuxSupervisor] = None
_singleton_lock = Lock()


def get_supervisor() -> TmuxSupervisor:
    """Module-level singleton."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = TmuxSupervisor()
        return _singleton
