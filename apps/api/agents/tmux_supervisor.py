"""Tmux pool manager for long-lived `claude` CLI sessions.

Each registered agent is bound to a named tmux session running
`claude --dangerously-skip-permissions` indefinitely, so prompts can be
sent without paying per-call startup cost or losing in-session context.

Session names are namespaced per worktree pane via the BORINA_PANE_NUM
env var so that the eight parallel refactor instances don't collide
on the same tmux name during verification.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Lock
from typing import Optional


# ----------------------------------------------------------------------------
# Locating the claude CLI
# ----------------------------------------------------------------------------

_CLAUDE_FALLBACKS = [
    str(Path.home() / ".npm-global" / "bin" / "claude"),
    str(Path.home() / ".local" / "bin" / "claude"),
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
]


def resolve_claude_path() -> str:
    """Resolve the claude CLI binary.

    Order: CLAUDE_CLI_PATH env → shutil.which("claude") → known fallbacks.
    Raises RuntimeError with a clear, actionable message if nothing works.
    """
    explicit = os.environ.get("CLAUDE_CLI_PATH", "").strip()
    if explicit:
        if Path(explicit).is_file() and os.access(explicit, os.X_OK):
            return explicit
        raise RuntimeError(
            f"CLAUDE_CLI_PATH={explicit!r} is set but not an executable file. "
            f"Install claude or unset CLAUDE_CLI_PATH."
        )

    found = shutil.which("claude")
    if found:
        return found

    for candidate in _CLAUDE_FALLBACKS:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate

    raise RuntimeError(
        "claude CLI not found. Set CLAUDE_CLI_PATH or install via "
        "`npm install -g @anthropic-ai/claude-code`. Searched: "
        f"$PATH={os.environ.get('PATH', '')!r}, fallbacks={_CLAUDE_FALLBACKS}"
    )


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

# Strips both colour SGR sequences and bracketed-paste / cursor-control codes.
_ANSI_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\)|[PX^_].*?\x1B\\)"
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _pane_namespace() -> str:
    """Return the pane prefix used to namespace tmux session names.

    BORINA_PANE_NUM is set per-worktree by the verification harness; absent
    it (e.g. in production), we use a stable hostname-based namespace so that
    sessions still don't collide across machines sharing a tmux server.
    """
    pane = os.environ.get("BORINA_PANE_NUM", "").strip()
    if pane:
        return f"borina-p{pane}"
    return "borina"


def _session_name(agent_id: str) -> str:
    return f"{_pane_namespace()}-{agent_id}"


def _run(cmd: list[str], *, timeout: float = 10.0, input_data: Optional[bytes] = None) -> str:
    """Run a subprocess, capture both streams, raise with full context on error."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            input=input_data,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"command not found: {cmd[0]!r} ({e!r})") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"command timed out after {timeout}s: {' '.join(cmd)!r} "
            f"(stdout={e.stdout!r}, stderr={e.stderr!r})"
        ) from e

    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={proc.returncode}): {' '.join(cmd)!r} | "
            f"stdout={proc.stdout.decode('utf-8', 'replace')!r} | "
            f"stderr={proc.stderr.decode('utf-8', 'replace')!r}"
        )
    return proc.stdout.decode("utf-8", "replace")


# ----------------------------------------------------------------------------
# Supervisor
# ----------------------------------------------------------------------------

class TmuxSupervisor:
    """Manages a pool of long-lived `claude` tmux sessions, one per agent."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._known: dict[str, dict] = {}  # agent_id → {workdir, system_prompt, name}

    # ---- session existence ----

    def session_exists(self, agent_id: str) -> bool:
        name = _session_name(agent_id)
        return self._tmux_has(name)

    def _tmux_has(self, name: str) -> bool:
        proc = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True,
        )
        return proc.returncode == 0

    def list_sessions(self) -> list[dict]:
        """Return [{agent_id, name, workdir, exists}] for every registered agent."""
        out = []
        for agent_id, meta in self._known.items():
            out.append({
                "agent_id": agent_id,
                "name": meta["name"],
                "workdir": meta["workdir"],
                "system_prompt": meta.get("system_prompt", ""),
                "exists": self._tmux_has(meta["name"]),
            })
        return out

    # ---- spawn ----

    def spawn(self, agent_id: str, workdir: str, system_prompt: str) -> dict:
        """Spawn (or re-adopt) a tmux session running claude for the given agent.

        Idempotent: if the session already exists in tmux, we re-adopt it
        without restarting claude, which is what we want across API restarts.
        """
        with self._lock:
            return self._spawn_locked(agent_id, workdir, system_prompt)

    def _spawn_locked(self, agent_id: str, workdir: str, system_prompt: str) -> dict:
        if not agent_id or "/" in agent_id or ":" in agent_id or "." in agent_id:
            raise RuntimeError(
                f"invalid agent_id {agent_id!r} — must be a simple slug (a-z, 0-9, -, _)"
            )

        name = _session_name(agent_id)
        Path(workdir).mkdir(parents=True, exist_ok=True)

        if self._tmux_has(name):
            # Re-adopt: keep the running claude, just update our meta.
            self._known[agent_id] = {
                "name": name,
                "workdir": workdir,
                "system_prompt": system_prompt,
                "spawned_at": self._known.get(agent_id, {}).get("spawned_at", time.time()),
                "readopted": True,
            }
            return {
                "agent_id": agent_id,
                "name": name,
                "workdir": workdir,
                "spawned": False,
                "readopted": True,
            }

        claude_path = resolve_claude_path()

        # Build the claude command. We pass system_prompt via --append-system-prompt
        # so the agent's persona is loaded from the moment claude starts.
        claude_cmd_parts = [
            self._shell_quote(claude_path),
            "--dangerously-skip-permissions",
        ]
        if system_prompt:
            claude_cmd_parts += [
                "--append-system-prompt",
                self._shell_quote(system_prompt),
            ]
        claude_cmd = " ".join(claude_cmd_parts)

        # Wrap so the pane stays alive even if claude exits unexpectedly,
        # which keeps capture() useful for post-mortem.
        wrapped = (
            f"cd {self._shell_quote(workdir)} && exec {claude_cmd}; "
            "echo '[claude exited; tmux pane preserved]'; sleep 86400"
        )

        # Reasonable scrollback so capture(lines=...) has history to draw on.
        _run([
            "tmux", "new-session", "-d",
            "-s", name,
            "-x", "200", "-y", "50",
            "-c", workdir,
            "sh", "-lc", wrapped,
        ])

        # Tmux defaults history-limit per-server; bump it for this session.
        try:
            _run(["tmux", "set-option", "-t", name, "history-limit", "10000"])
        except RuntimeError:
            pass  # non-fatal

        self._known[agent_id] = {
            "name": name,
            "workdir": workdir,
            "system_prompt": system_prompt,
            "spawned_at": time.time(),
            "readopted": False,
        }

        # First-run hygiene: claude shows a "trust this folder" dialog on the
        # first ever launch in a directory. The default selection ("Yes")
        # is selected; pressing Enter dismisses it. Detect & dismiss so the
        # session is ready for the first prompt.
        self._dismiss_trust_dialog_if_present(name)

        return {
            "agent_id": agent_id,
            "name": name,
            "workdir": workdir,
            "spawned": True,
            "readopted": False,
        }

    def _dismiss_trust_dialog_if_present(self, name: str, max_wait: float = 6.0) -> bool:
        """Look for the workspace-trust dialog; press Enter to accept if found.

        Returns True if a dialog was dismissed. Non-fatal on any error —
        worst case the caller's first prompt also dismisses it.
        """
        deadline = time.time() + max_wait
        # Trust dialog phrasing — match anything stable across versions.
        markers = ("trust this folder", "Yes, I trust this")
        while time.time() < deadline:
            try:
                proc = subprocess.run(
                    ["tmux", "capture-pane", "-p", "-t", name, "-S", "-100"],
                    capture_output=True, timeout=5,
                )
                pane = proc.stdout.decode("utf-8", "replace")
            except Exception:
                return False
            if any(m in pane for m in markers):
                try:
                    subprocess.run(
                        ["tmux", "send-keys", "-t", name, "Enter"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    return False
                # Give claude a moment to paint the post-trust UI.
                time.sleep(1.0)
                return True
            # Claude's main UI has rendered without a trust dialog → done.
            if "bypass permissions" in pane or "shift+tab" in pane:
                return False
            time.sleep(0.4)
        return False

    # ---- send / capture ----

    def send_prompt(self, agent_id: str, prompt: str) -> None:
        """Paste a multi-line prompt into the session and press Enter.

        Uses load-buffer + paste-buffer so that newlines are preserved and we
        avoid the line-by-line send-keys race where claude submits early.
        """
        meta = self._require_known(agent_id)
        name = meta["name"]
        if not self._tmux_has(name):
            raise RuntimeError(
                f"tmux session {name!r} for agent {agent_id!r} is not running. "
                f"Call spawn() first."
            )

        # Stash prompt in a temp file → load into a unique tmux buffer → paste.
        buf_name = f"borina-{agent_id}-{int(time.time() * 1000)}"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".prompt", delete=False, encoding="utf-8"
        ) as fp:
            fp.write(prompt)
            buf_path = fp.name

        try:
            _run(["tmux", "load-buffer", "-b", buf_name, buf_path])
            try:
                _run(["tmux", "paste-buffer", "-b", buf_name, "-t", name])
            finally:
                # Always free the buffer, even if paste fails.
                subprocess.run(
                    ["tmux", "delete-buffer", "-b", buf_name],
                    capture_output=True,
                )
            # Submit the prompt.
            _run(["tmux", "send-keys", "-t", name, "Enter"])
        finally:
            try:
                os.unlink(buf_path)
            except OSError:
                pass

    def capture(self, agent_id: str, lines: int = 200) -> str:
        """Capture the last `lines` of the pane (with ANSI codes stripped)."""
        meta = self._require_known(agent_id)
        name = meta["name"]
        if not self._tmux_has(name):
            raise RuntimeError(
                f"tmux session {name!r} for agent {agent_id!r} is not running."
            )

        start = -max(1, int(lines))
        out = _run([
            "tmux", "capture-pane",
            "-p",  # print to stdout
            "-t", name,
            "-S", str(start),
            "-J",  # join wrapped lines
            "-e",  # include escape sequences (we strip below)
        ])
        return _strip_ansi(out)

    # ---- idle detection ----

    def wait_for_idle(
        self,
        agent_id: str,
        idle_seconds: float = 4.0,
        timeout_seconds: float = 600.0,
    ) -> str:
        """Block until the pane has been visually unchanged for `idle_seconds`.

        Returns the final captured pane text (ANSI-stripped). On timeout,
        returns the partial output rather than raising — callers want the
        partial response, not an exception.
        """
        deadline = time.time() + max(1.0, timeout_seconds)
        last_text = self.capture(agent_id, lines=400)
        last_change = time.time()

        # Poll every 500ms — fast enough to feel live, slow enough not to
        # thrash a busy pane.
        poll_interval = 0.5

        while time.time() < deadline:
            time.sleep(poll_interval)
            try:
                current = self.capture(agent_id, lines=400)
            except RuntimeError:
                # Session vanished mid-wait — return what we have.
                return last_text

            if current != last_text:
                last_text = current
                last_change = time.time()
                continue

            if time.time() - last_change >= idle_seconds:
                return last_text

        # Timeout — return partial.
        return last_text

    # ---- lifecycle ----

    def restart(self, agent_id: str) -> dict:
        """Kill and respawn the agent's session, preserving its workdir/system prompt."""
        meta = self._require_known(agent_id)
        # Kill if alive, ignore if not.
        if self._tmux_has(meta["name"]):
            try:
                _run(["tmux", "kill-session", "-t", meta["name"]])
            except RuntimeError:
                pass
        # Respawn fresh — call spawn() so all the wrapping is consistent.
        return self.spawn(agent_id, meta["workdir"], meta.get("system_prompt", ""))

    def kill(self, agent_id: str) -> dict:
        """Kill the tmux session and forget the agent."""
        meta = self._known.get(agent_id)
        if not meta:
            raise RuntimeError(
                f"agent {agent_id!r} is not known to the supervisor"
            )
        existed = self._tmux_has(meta["name"])
        if existed:
            try:
                _run(["tmux", "kill-session", "-t", meta["name"]])
            except RuntimeError as e:
                raise RuntimeError(
                    f"failed to kill tmux session {meta['name']!r}: {e}"
                ) from e
        self._known.pop(agent_id, None)
        return {"agent_id": agent_id, "name": meta["name"], "killed": existed}

    # ---- internals ----

    def _require_known(self, agent_id: str) -> dict:
        meta = self._known.get(agent_id)
        if not meta:
            raise RuntimeError(
                f"agent {agent_id!r} is not known to the supervisor — "
                f"call spawn() first. Known: {list(self._known)}"
            )
        return meta

    @staticmethod
    def _shell_quote(value: str) -> str:
        """Quote a value for sh -c. Single-quote and escape any embedded single quotes."""
        return "'" + value.replace("'", "'\"'\"'") + "'"


# ----------------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------------

_SINGLETON: Optional[TmuxSupervisor] = None
_SINGLETON_LOCK = Lock()


def get_supervisor() -> TmuxSupervisor:
    """Return the process-wide TmuxSupervisor singleton."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = TmuxSupervisor()
    return _SINGLETON
