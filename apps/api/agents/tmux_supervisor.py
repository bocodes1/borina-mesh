"""Tmux session pool for long-lived `claude` CLI agents.

Each agent runs `claude --dangerously-skip-permissions` inside a detached tmux
session named `borina-p${PANE_NUMBER}-{agent_id}`. Sessions persist across API
restarts and are re-adopted on spawn().

Why tmux instead of the SDK / -p subprocess pattern:
  * The CLI authenticates via the user's ~/.claude credentials — no API key.
  * A long-lived REPL keeps prior prompts in conversation context and reuses
    Claude's filesystem permissions.
  * tmux gives us free buffering + scrollback so we can recover output even
    after a uvicorn reload.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]|\r")


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences and stray carriage returns."""
    return _ANSI_RE.sub("", text)


def _detect_pane_number() -> str:
    """Return the pane index used to namespace tmux session names.

    Resolution order: BORINA_PANE_NUMBER → PANE_NUMBER → parse from cwd
    (`.worktrees/pane-N`) → "0".
    """
    for var in ("BORINA_PANE_NUMBER", "PANE_NUMBER"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    cwd = str(Path.cwd())
    m = re.search(r"\.worktrees[/\\]pane-(\d+)", cwd)
    if m:
        return m.group(1)
    return "0"


def _resolve_claude_path() -> str:
    """Resolve the absolute path to the `claude` CLI binary.

    Order: CLAUDE_CLI_PATH env → shutil.which("claude") → hardcoded fallbacks.
    Raises RuntimeError if no executable is found, with all candidates listed.
    """
    candidates: list[tuple[str, str]] = []

    env_path = os.environ.get("CLAUDE_CLI_PATH", "").strip()
    if env_path:
        candidates.append(("CLAUDE_CLI_PATH", env_path))

    which = shutil.which("claude")
    if which:
        candidates.append(("shutil.which", which))

    for fallback in (
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.npm-global/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ):
        candidates.append(("fallback", fallback))

    tried: list[str] = []
    for source, path in candidates:
        tried.append(f"{source}={path}")
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    raise RuntimeError(
        "Could not locate `claude` CLI executable. Tried: "
        + " | ".join(tried)
        + f" | PATH={os.environ.get('PATH', '')}"
    )


def _run_tmux(*args: str, check: bool = True, input_text: Optional[str] = None,
              timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    """Run a `tmux` command, capturing both stdout and stderr.

    Raises RuntimeError on non-zero exit when check=True, with the full command
    and stderr message — never empty errors.
    """
    cmd = ["tmux", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"tmux not found on PATH: {e!r}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"tmux command timed out after {timeout}s: {' '.join(cmd)!r} | {e!r}"
        ) from e
    if check and result.returncode != 0:
        raise RuntimeError(
            f"tmux command failed (exit {result.returncode}): {' '.join(cmd)!r} | "
            f"stderr={result.stderr.strip()!r} | stdout={result.stdout.strip()!r}"
        )
    return result


class TmuxSupervisor:
    """Pool manager for long-lived claude CLI sessions in tmux."""

    def __init__(self, pane_number: Optional[str] = None,
                 claude_path: Optional[str] = None) -> None:
        self.pane_number = pane_number or _detect_pane_number()
        self._claude_path = claude_path
        self._lock = threading.RLock()
        self._meta: dict[str, dict] = {}

    @property
    def claude_path(self) -> str:
        if self._claude_path is None:
            self._claude_path = _resolve_claude_path()
        return self._claude_path

    def session_name(self, agent_id: str) -> str:
        """Pane-namespaced session name so 8 parallel instances do not collide."""
        return f"borina-p{self.pane_number}-{agent_id}"

    def session_exists(self, agent_id: str) -> bool:
        name = self.session_name(agent_id)
        result = _run_tmux("has-session", "-t", name, check=False)
        return result.returncode == 0

    def list_sessions(self) -> list[dict]:
        """Return metadata for every borina-p{pane}-* session tmux currently owns."""
        prefix = f"borina-p{self.pane_number}-"
        result = _run_tmux(
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_created}\t#{session_attached}",
            check=False,
        )
        if result.returncode != 0:
            # No tmux server running yet → no sessions.
            return []
        sessions: list[dict] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if not parts or not parts[0].startswith(prefix):
                continue
            name = parts[0]
            agent_id = name[len(prefix):]
            created = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            attached = parts[2] if len(parts) > 2 else "0"
            with self._lock:
                meta = dict(self._meta.get(agent_id, {}))
            sessions.append({
                "agent_id": agent_id,
                "session_name": name,
                "created_at": created,
                "attached": attached == "1",
                "workdir": meta.get("workdir"),
                "system_prompt_set": bool(meta.get("system_prompt")),
            })
        return sessions

    def spawn(self, agent_id: str, workdir: str, system_prompt: str = "") -> dict:
        """Create or re-adopt a tmux session running claude in interactive mode.

        Idempotent: if the named session already exists, we record metadata
        and return without re-launching. This protects against API restarts.
        """
        if not agent_id or "/" in agent_id or " " in agent_id:
            raise RuntimeError(f"Invalid agent_id: {agent_id!r}")

        name = self.session_name(agent_id)
        workdir_path = Path(workdir).expanduser()
        try:
            workdir_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise RuntimeError(
                f"Could not create workdir {workdir_path!s}: {type(e).__name__}: {e!r}"
            ) from e

        with self._lock:
            if self.session_exists(agent_id):
                # Re-adopt: leave the running claude alone. Preserve the
                # original workdir + system_prompt if we already recorded
                # them — overwriting would surprise restart() callers.
                existing = self._meta.get(agent_id, {})
                self._meta[agent_id] = {
                    "workdir": existing.get("workdir") or str(workdir_path),
                    "system_prompt": existing.get("system_prompt") or system_prompt,
                    "spawned_at": existing.get("spawned_at", time.time()),
                    "readopted": True,
                }
                return {
                    "agent_id": agent_id,
                    "session_name": name,
                    "workdir": self._meta[agent_id]["workdir"],
                    "status": "readopted",
                }

            # Create detached tmux session in the workdir with a plain shell.
            _run_tmux(
                "new-session",
                "-d",
                "-s", name,
                "-c", str(workdir_path),
                "-x", "220",
                "-y", "50",
            )

            # Build the claude command. Use --append-system-prompt when supplied
            # so the CLI loads it into context at startup.
            claude_path = self.claude_path
            cmd_parts = [_shell_quote(claude_path), "--dangerously-skip-permissions"]
            if system_prompt:
                cmd_parts.extend([
                    "--append-system-prompt",
                    _shell_quote(system_prompt),
                ])
            cmd_str = " ".join(cmd_parts)

            # Type the command literally so any embedded key names (like "Enter"
            # inside the prompt) are not interpreted as keystrokes.
            _run_tmux("send-keys", "-t", name, "-l", cmd_str)
            _run_tmux("send-keys", "-t", name, "Enter")

            self._meta[agent_id] = {
                "workdir": str(workdir_path),
                "system_prompt": system_prompt,
                "spawned_at": time.time(),
                "readopted": False,
            }

        # Handle first-run prompts (folder-trust dialog) so the next caller
        # sees a ready REPL rather than a blocking confirmation screen.
        try:
            self._prime_session(agent_id, deadline=time.monotonic() + 12.0)
        except Exception as e:
            # Priming is best-effort — if it fails, callers can still send
            # prompts manually. Surface the reason in returned metadata.
            return {
                "agent_id": agent_id,
                "session_name": name,
                "workdir": str(workdir_path),
                "status": "spawned",
                "prime_warning": f"{type(e).__name__}: {e!r}",
            }

        return {
            "agent_id": agent_id,
            "session_name": name,
            "workdir": str(workdir_path),
            "status": "spawned",
        }

    def _prime_session(self, agent_id: str, deadline: float) -> None:
        """Walk through any first-run dialogs (folder trust, theme picker)
        until a normal claude REPL prompt is visible."""
        name = self.session_name(agent_id)
        seen_trust = False
        seen_theme = False
        while time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                pane = self.capture(agent_id, lines=80).lower()
            except RuntimeError:
                return
            # Folder-trust dialog
            if "trust" in pane and ("yes" in pane or "trust this folder" in pane):
                if not seen_trust:
                    _run_tmux("send-keys", "-t", name, "Enter")
                    seen_trust = True
                    time.sleep(1.0)
                    continue
            # Theme picker on first run
            if "choose" in pane and "theme" in pane and not seen_theme:
                _run_tmux("send-keys", "-t", name, "Enter")
                seen_theme = True
                time.sleep(1.0)
                continue
            # Login prompt — bail out fast, supervisor can't auto-resolve this
            if "log in" in pane and "anthropic" in pane:
                return
            # Heuristic: a settled prompt has the box-drawing prompt frame.
            if "│ >" in pane or "shortcuts" in pane or "ctrl+" in pane:
                return

    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Send a (possibly multi-line) prompt to the agent's claude REPL.

        Uses tmux's paste buffer so newlines and special characters survive
        intact — send-keys would interpret each line and break on long input.
        """
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"Session for agent {agent_id!r} does not exist (name={self.session_name(agent_id)!r})"
            )

        name = self.session_name(agent_id)

        # Write to a temp file so tmux load-buffer can ingest it without us
        # worrying about embedded null bytes or shell quoting.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as tmp:
            tmp.write(prompt)
            tmp_path = tmp.name

        try:
            _run_tmux("load-buffer", "-b", f"borina-{name}", tmp_path)
            _run_tmux("paste-buffer", "-b", f"borina-{name}", "-t", name, "-d")
            # Small pause so paste-buffer flushes before the Enter — without
            # this Claude sometimes sees the Enter mid-paste and submits a
            # truncated prompt.
            time.sleep(0.1)
            _run_tmux("send-keys", "-t", name, "Enter")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def capture(self, agent_id: str, lines: int = 200) -> str:
        """Return the last `lines` lines of the pane, ANSI-stripped."""
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"Session for agent {agent_id!r} does not exist (name={self.session_name(agent_id)!r})"
            )
        name = self.session_name(agent_id)
        # -p prints to stdout, -S -<n> starts <n> lines back, -e keeps escape codes
        # so we can strip them ourselves consistently.
        result = _run_tmux(
            "capture-pane",
            "-p",
            "-t", name,
            "-S", f"-{int(lines)}",
        )
        return _strip_ansi(result.stdout)

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: float = 4.0,
        timeout_seconds: float = 60.0,
        poll_interval: float = 0.5,
    ) -> str:
        """Block until the pane content has not changed for `idle_seconds`.

        Returns the final captured output. On timeout, returns the latest
        capture instead of raising — callers expect partial output, never
        an empty error.
        """
        if not self.session_exists(agent_id):
            raise RuntimeError(
                f"Session for agent {agent_id!r} does not exist (name={self.session_name(agent_id)!r})"
            )

        deadline = time.monotonic() + timeout_seconds
        last_text = self.capture(agent_id, lines=400)
        last_change = time.monotonic()

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            current = self.capture(agent_id, lines=400)
            if current != last_text:
                last_text = current
                last_change = time.monotonic()
                continue
            if (time.monotonic() - last_change) >= idle_seconds:
                return current

        # Timeout — return what we have. Caller decides whether that's OK.
        return last_text

    def restart(self, agent_id: str) -> dict:
        """Kill the session and re-spawn with the same workdir + system_prompt."""
        with self._lock:
            meta = self._meta.get(agent_id)
            if not meta:
                # Fall back: derive workdir from the running session if possible,
                # otherwise refuse with a typed error so the caller knows what's up.
                if not self.session_exists(agent_id):
                    raise RuntimeError(
                        f"agent {agent_id!r} not known to supervisor and no tmux session "
                        f"named {self.session_name(agent_id)!r} exists"
                    )
                # Session exists but we have no metadata (API restarted before
                # spawn was called this lifetime). We can't safely restart with
                # the original system_prompt, so error out so the user calls
                # spawn() explicitly.
                raise RuntimeError(
                    f"agent {agent_id!r} session exists but supervisor has no metadata; "
                    "call POST /sessions/{agent_id} to provide workdir + system_prompt before restart"
                )

            workdir = meta["workdir"]
            system_prompt = meta.get("system_prompt", "")

        self.kill(agent_id)
        # Clear stored meta so spawn() does not short-circuit into "readopted".
        with self._lock:
            self._meta.pop(agent_id, None)
        return self.spawn(agent_id, workdir, system_prompt)

    def kill(self, agent_id: str) -> bool:
        """Kill the agent's tmux session. Returns True if anything was killed."""
        name = self.session_name(agent_id)
        if not self.session_exists(agent_id):
            with self._lock:
                self._meta.pop(agent_id, None)
            return False
        _run_tmux("kill-session", "-t", name)
        with self._lock:
            self._meta.pop(agent_id, None)
        return True


def _shell_quote(s: str) -> str:
    """POSIX-safe shell quoting for command strings sent through tmux send-keys."""
    if not s:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-_" for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


_supervisor: Optional[TmuxSupervisor] = None
_supervisor_lock = threading.Lock()


def get_supervisor() -> TmuxSupervisor:
    """Module-level singleton."""
    global _supervisor
    if _supervisor is None:
        with _supervisor_lock:
            if _supervisor is None:
                _supervisor = TmuxSupervisor()
    return _supervisor
