"""Autonomous builder (Bo's spec 2026-06-10): "build: <task>" from Telegram →
a DETACHED headless Claude Code run in a git worktree of this repo. True
autonomy: it implements, verifies the full suites itself, and ships
(merge → rebuild → kickstart → push) without asking — it messages Bo ONLY
when stuck (BLOCKED.md, red tests, dirty tree), and a Telegram reply to that
message resumes the same worktree with guidance ('abort' cancels).

Why detached (start_new_session): shipping kickstarts the API itself — the
builder must outlive its parent. It writes Job rows (kind="builder") so /jobs
and the Telegram `status` command can show it; orphan recovery spares builder
rows whose pid is alive.

Safety model: only Bo's allow-listed chat reaches this; the build is confined
to its worktree until the suites pass in an INDEPENDENT verification run (we
never trust the build agent's claim); a failed post-ship health check rolls
main back. The generic forbidden-action gate is deliberately not applied to
build texts ("remove the favicon" is a code task, not a live deletion) — the
builder has no trade/calendar/send capability.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO = Path(os.getenv("BORINA_REPO", str(Path.home() / "borina-mesh")))
BUILDS = Path.home() / ".borina" / "builds"
CLAUDE_TIMEOUT_SECONDS = 2400  # 40 min per build attempt

BUILD_PROMPT = """You are the Borina Mesh builder, working in a git WORKTREE of the live repo
(main checkout and services are elsewhere — never touch anything outside this worktree).

Task from Bo (via Telegram): {task}
{guidance}
Rules:
- Implement surgically; match existing style; extend the existing pytest/vitest suites.
- Verify before finishing: `apps/api/.venv/bin/python -m pytest -q` from apps/api must pass
  (the venv is shared from the main checkout); if you touched apps/web also run
  `npx vitest run` and `npx tsc --noEmit` there.
- When everything is green: `git add` your changes and commit with a clear message.
  NEVER push. NEVER merge. NEVER restart services. The shipper does that after
  independently re-verifying.
- If you need a product decision, hit something ambiguous, or cannot get tests green:
  write BLOCKED.md at the worktree root with ONE specific question and stop.
"""


# ── control plane (called from routes/telegram.py) ───────────────────────────

DEFAULT_OWNER = os.getenv("BORINA_GH_OWNER", "bocodes1")


def _resolve_repo_spec(repo: Optional[str]) -> str:
    """None → this repo (self-build). 'name' → gh:OWNER/name. 'owner/name' →
    gh:owner/name. The 'gh:' prefix tells the runner to use the external flow."""
    if not repo:
        return str(REPO)
    repo = repo.strip().strip("/")
    if "/" in repo:
        return f"gh:{repo}"
    return f"gh:{DEFAULT_OWNER}/{repo}"


def start_build(task: str, chat_id: int, repo: Optional[str] = None) -> int:
    """Create the builder Job row and spawn the detached runner. Returns job id.
    `repo` None = build this mesh; otherwise an external GitHub project."""
    from db import session_scope
    from models import Job, JobStatus

    repo_path = _resolve_repo_spec(repo)
    with session_scope() as s:
        job = Job(
            agent_id="builder", prompt=task, status=JobStatus.RUNNING,
            kind="builder", repo_path=repo_path, base_branch="main",
            started_at=datetime.utcnow(), telegram_chat_id=chat_id,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        job.worker_branch = f"build/job{job.id}"
        s.add(job)
        s.commit()
        job_id = job.id
    _spawn(job_id)
    return job_id


def _spawn(job_id: int, resume: bool = False) -> None:
    """Detached runner process — survives API kickstarts (its own session)."""
    from db import session_scope
    from models import Job

    py = REPO / "apps" / "api" / ".venv" / "bin" / "python"
    script = REPO / "scripts" / "builder_run.py"
    log = REPO / "logs" / f"builder-job{job_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    args = [str(py), str(script), "--job-id", str(job_id)]
    if resume:
        args.append("--resume")
    with log.open("ab") as fh:
        proc = subprocess.Popen(
            args, stdout=fh, stderr=fh, start_new_session=True, cwd=str(REPO)
        )
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job:
            job.worker_pid = proc.pid
            job.log_path = str(log)
            s.add(job)
            s.commit()


def handle_builder_reply(thread, text: str, chat_id: int) -> dict:
    """Bo replied to a builder message: 'abort' cancels; anything else is
    guidance — written into the worktree and the runner respawned."""
    from db import session_scope
    from models import Job, JobStatus
    from dispatch import dispatcher
    from dispatch.telegram_format import format_telegram

    job_id = thread.job_id
    if (text or "").strip().lower() in {"abort", "cancel", "stop"}:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = "aborted by Bo"
                job.completed_at = datetime.utcnow()
                s.add(job)
                s.commit()
        cleanup_worktree(job_id)
        dispatcher.send_telegram_message(
            chat_id, format_telegram(f"Build {job_id} aborted. Worktree removed.")
        )
        return {"ok": True, "status": "build_aborted", "job_id": job_id}

    wt = BUILDS / f"job{job_id}"
    wt.mkdir(parents=True, exist_ok=True)
    guidance = wt / "GUIDANCE.md"
    prior = guidance.read_text() if guidance.exists() else ""
    guidance.write_text(prior + f"\n## Guidance from Bo\n{text}\n")
    blocked = wt / "BLOCKED.md"
    if blocked.exists():
        blocked.unlink()
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.RUNNING
            job.qa_verdict = None
            s.add(job)
            s.commit()
    _spawn(job_id, resume=True)
    dispatcher.send_telegram_message(
        chat_id, format_telegram(f"Build {job_id} resuming with your guidance.")
    )
    return {"ok": True, "status": "build_resumed", "job_id": job_id}


def cleanup_worktree(job_id: int, repo: Optional[Path] = None) -> None:
    repo = repo or REPO
    wt = BUILDS / f"job{job_id}"
    subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                   cwd=repo, capture_output=True)
    subprocess.run(["git", "branch", "-D", f"build/job{job_id}"],
                   cwd=repo, capture_output=True)


# ── worktree evaluation (used by the runner; pure-ish, unit-tested) ──────────

def _git(cwd, *args) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return (r.stdout or "").strip()


def evaluate_worktree(wt: Path, repo: Optional[Path] = None) -> tuple[str, str]:
    """('stuck', question) | ('nochange', '') | ('ready', '') for a finished
    build attempt. Uncommitted changes count as stuck — the agent was told to
    commit only when green."""
    repo = repo or REPO
    blocked = wt / "BLOCKED.md"
    if blocked.exists():
        return "stuck", blocked.read_text().strip()[:600]
    dirty = _git(wt, "status", "--porcelain")
    dirty = "\n".join(
        l for l in dirty.splitlines()
        if not l.endswith(("GUIDANCE.md", "BLOCKED.md"))
    )
    if dirty:
        return "stuck", f"uncommitted changes left in the worktree:\n{dirty[:400]}"
    head = _git(wt, "rev-parse", "HEAD")
    base = _git(repo, "rev-parse", "main")
    if head == base:
        return "nochange", ""
    return "ready", ""
