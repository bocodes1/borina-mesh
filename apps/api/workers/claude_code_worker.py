"""Headless Claude Code worker. Spawns `claude -p` in a per-job git worktree."""

import os
import shlex
import subprocess
import threading
from pathlib import Path
from workers.handoff import HandoffPayload

WORKTREE_ROOT = Path(os.environ.get("BORINA_WORKTREE_ROOT", ".borina-workers")).resolve()
LOG_ROOT = Path(os.environ.get("BORINA_LOG_ROOT", "logs/jobs")).resolve()
DEFAULT_CMD = os.environ.get("BORINA_CLAUDE_CMD", "claude")
DEFAULT_TIMEOUT = int(os.environ.get("BORINA_WORKER_TIMEOUT", "14400"))


def _create_worktree(repo: Path, job_id: int, base_branch: str) -> Path:
    worktree_root = Path(os.environ.get("BORINA_WORKTREE_ROOT", str(WORKTREE_ROOT))).resolve()
    worktree_root.mkdir(parents=True, exist_ok=True)
    target = worktree_root / str(job_id)
    if target.exists():
        return target
    branch = f"borina/job-{job_id}"
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(target), base_branch],
        cwd=repo, check=True,
    )
    return target


def _write_task_file(worktree: Path, payload: HandoffPayload) -> None:
    parts = [f"# Borina Task\n\n{payload.prompt}\n"]
    if payload.cwd_snapshot:
        parts.append(f"\n## git status\n```\n{payload.cwd_snapshot}\n```\n")
    if payload.diff_snapshot:
        parts.append(f"\n## diff\n```diff\n{payload.diff_snapshot}\n```\n")
    if payload.recent_files:
        parts.append("\n## Recent files\n" + "\n".join(f"- {f}" for f in payload.recent_files) + "\n")
    if payload.conversation_tail:
        parts.append(f"\n## Conversation context\n{payload.conversation_tail}\n")
    (worktree / "BORINA_TASK.md").write_text("".join(parts), encoding="utf-8")


def run_worker_sync(job_id: int, payload: HandoffPayload) -> dict:
    """Run synchronously. Returns dict with exit_code, worktree, log_path, log_tail, diff."""
    repo = Path(payload.repo_path).resolve()
    worktree = _create_worktree(repo, job_id, payload.base_branch)
    _write_task_file(worktree, payload)

    # Re-read env vars at call time so tests can monkeypatch them
    log_root = Path(os.environ.get("BORINA_LOG_ROOT", "logs/jobs")).resolve()
    claude_cmd = os.environ.get("BORINA_CLAUDE_CMD", "claude")
    worker_timeout = int(os.environ.get("BORINA_WORKER_TIMEOUT", "14400"))

    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"{job_id}.jsonl"

    task_content = (worktree / "BORINA_TASK.md").read_text(encoding="utf-8")
    # shlex.split with posix=False preserves Windows backslashes correctly
    cmd_parts = shlex.split(claude_cmd, posix=False) if " " in claude_cmd else [claude_cmd]
    cmd = cmd_parts + ["-p", task_content, "--output-format", "stream-json"]

    # shell=True on Windows so subprocess can find npm shims like claude.cmd
    use_shell = os.name == "nt"
    with open(log_path, "w", encoding="utf-8") as logf:
        proc = subprocess.run(
            cmd, cwd=worktree, stdout=logf, stderr=subprocess.STDOUT,
            timeout=worker_timeout, shell=use_shell,
        )

    log_tail = "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-30:])
    diff = subprocess.run(
        ["git", "diff", payload.base_branch],
        cwd=worktree, capture_output=True, text=True,
    ).stdout

    return {
        "exit_code": proc.returncode,
        "worktree": str(worktree),
        "log_path": str(log_path),
        "log_tail": log_tail,
        "diff": diff,
    }


def enqueue_worker(job_id: int, payload: HandoffPayload) -> None:
    """Spawn worker in a background thread."""
    def _runner():
        from datetime import datetime
        from db import session_scope
        from models import Job, JobStatus

        try:
            result = run_worker_sync(job_id, payload)
            with session_scope() as s:
                job = s.get(Job, job_id)
                job.status = JobStatus.COMPLETED if result["exit_code"] == 0 else JobStatus.FAILED
                job.completed_at = datetime.utcnow()
                job.log_path = result["log_path"]
                job.worker_branch = f"borina/job-{job_id}"
                s.add(job)
                s.commit()
            _post_completion_qa(job_id, result, payload.prompt)
        except Exception as e:
            try:
                with session_scope() as s:
                    job = s.get(Job, job_id)
                    if job:
                        job.status = JobStatus.FAILED
                        job.error = str(e)
                        s.add(job)
                        s.commit()
            except Exception:
                pass

    threading.Thread(target=_runner, daemon=True).start()


def _post_completion_qa(job_id: int, result: dict, prompt: str) -> None:
    """Run QA Director review on the diff + summary, then notify."""
    import asyncio
    from agents.qa_director import QADirector
    from db import session_scope
    from models import Job

    artifact = f"## Diff\n{result['diff']}\n\n## Log tail\n{result['log_tail']}"
    loop = asyncio.new_event_loop()
    try:
        review = loop.run_until_complete(QADirector().review(artifact, prompt))
    finally:
        loop.close()

    with session_scope() as s:
        job = s.get(Job, job_id)
        job.qa_verdict = review.verdict.value
        job.qa_notes = review.notes
        s.add(job)
        s.commit()

    _notify(job_id, review)


def _notify(job_id: int, review) -> None:
    """Telegram + vault note on completion."""
    import os
    import requests
    from pathlib import Path
    from datetime import date

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    dash = os.environ.get("BORINA_DASHBOARD_URL", "http://localhost:3000")

    icon = {"approve": "✅", "approve_with_notes": "⚠️",
            "request_rerun": "🔁", "block": "⛔"}.get(review.verdict.value, "•")
    msg = f"{icon} Job {job_id} done — {review.verdict.value}\n{review.notes[:300]}\n{dash}/jobs/{job_id}"

    if token and chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": msg}, timeout=10,
            )
        except Exception:
            pass

    vault = os.environ.get("OBSIDIAN_VAULT_PATH")
    if vault:
        notes_dir = Path(vault) / "borina-jobs"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / f"{date.today()}-job-{job_id}.md").write_text(msg, encoding="utf-8")
