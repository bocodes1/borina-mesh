#!/usr/bin/env python
"""Detached builder runner — model in apps/api/dispatch/builder.py.

Spawned by the API with start_new_session so it SURVIVES the kickstarts it
performs when shipping. Flow: worktree → headless `claude -p` → evaluate →
independent suite verification → ship (merge → rebuild → kickstart → health →
push, with rollback) — or message Bo on Telegram and wait for his reply
(which respawns this script with --resume).
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "apps" / "api"
sys.path.insert(0, str(API))
os.chdir(API)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(API / ".env")

from db import session_scope  # noqa: E402
from models import Job, JobStatus  # noqa: E402
from dispatch import builder, dispatcher  # noqa: E402
from dispatch.telegram_format import format_telegram  # noqa: E402


def log(msg: str) -> None:
    print(f"[builder] {datetime.utcnow().isoformat()} {msg}", flush=True)


def run(cmd, cwd, timeout=None):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def notify(chat_id, text, job_id=None, record_thread=False):
    """Send to Bo; optionally record as a builder thread so his reply resumes us."""
    mid = dispatcher.send_telegram_message(chat_id, format_telegram(text, max_lines=8))
    if record_thread and mid and job_id:
        dispatcher._record_thread(chat_id, mid, "builder", job_id, "build")
    return mid


def mark(job_id, status=None, error=None, qa_verdict=None, qa_notes=None, done=False):
    with session_scope() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        if status is not None:
            job.status = status
        if error is not None:
            job.error = error[:500]
        job.qa_verdict = qa_verdict
        if qa_notes is not None:
            job.qa_notes = qa_notes[:500]
        if done:
            job.completed_at = datetime.utcnow()
        s.add(job)
        s.commit()


def stuck(job_id, chat_id, question):
    """Ask Bo and wait (process exits; his reply respawns with --resume)."""
    log(f"stuck: {question[:200]}")
    mark(job_id, qa_verdict="stuck", qa_notes=question)
    notify(
        chat_id,
        f"Build {job_id} is stuck: {question[:400]}\n"
        f"Reply to THIS message with guidance, or 'abort'.",
        job_id=job_id,
        record_thread=True,
    )


def web_changed(wt) -> bool:
    diff = run(["git", "diff", "--name-only", "main...HEAD"], cwd=wt).stdout
    return any(l.startswith("apps/web/") for l in diff.splitlines())


def verify(wt) -> tuple[bool, str]:
    """Independent verification — never trust the build agent's claims."""
    log("verifying backend suite in worktree...")
    r = run([str(API / ".venv" / "bin" / "python"), "-m", "pytest", "-q"],
            cwd=Path(wt) / "apps" / "api", timeout=1200)
    tail = (r.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
    if r.returncode != 0:
        return False, f"backend: {tail[0]}"
    summary = f"backend {tail[0]}"
    if web_changed(wt):
        log("web changed — verifying vitest + tsc...")
        nm = Path(wt) / "apps" / "web" / "node_modules"
        if not nm.exists():
            nm.symlink_to(REPO / "apps" / "web" / "node_modules")
        r2 = run(["npx", "vitest", "run"], cwd=Path(wt) / "apps" / "web", timeout=900)
        if r2.returncode != 0:
            return False, "frontend vitest red: " + (r2.stdout or "")[-200:]
        r3 = run(["npx", "tsc", "--noEmit"], cwd=Path(wt) / "apps" / "web", timeout=900)
        if r3.returncode != 0:
            return False, "tsc errors: " + (r3.stdout or "")[-200:]
        summary += ", frontend vitest + tsc green"
    return True, summary


def kickstart(service: str) -> None:
    uid = os.getuid()
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.borina.mesh-{service}"],
                   capture_output=True)


def ship(job_id, chat_id, task, branch, wt, test_summary) -> None:
    pre = run(["git", "rev-parse", "main"], cwd=REPO).stdout.strip()
    log(f"shipping {branch} onto main (pre={pre[:8]})...")
    m = run(["git", "merge", "--no-ff", branch, "-m",
             f"builder: {task[:60]} (job {job_id})"], cwd=REPO)
    if m.returncode != 0:
        run(["git", "merge", "--abort"], cwd=REPO)
        stuck(job_id, chat_id, f"merge conflict with main: {(m.stdout or m.stderr)[:300]}")
        return

    needs_web = web_changed(wt)
    if needs_web:
        log("building web...")
        b = run(["npm", "run", "build"], cwd=REPO / "apps" / "web", timeout=1200)
        if b.returncode != 0:
            run(["git", "reset", "--hard", pre], cwd=REPO)
            stuck(job_id, chat_id, "next build failed post-merge; main rolled back: "
                  + (b.stdout or "")[-200:])
            return

    kickstart("api")
    if needs_web:
        kickstart("web")
    time.sleep(10)
    health = run(["curl", "-s", "-m", "5", "http://localhost:8000/health"], cwd=REPO).stdout
    if '"ok"' not in health:
        log("health check failed — rolling back")
        run(["git", "reset", "--hard", pre], cwd=REPO)
        kickstart("api")
        if needs_web:
            run(["npm", "run", "build"], cwd=REPO / "apps" / "web", timeout=1200)
            kickstart("web")
        stuck(job_id, chat_id, "post-ship health check failed; main rolled back to "
              f"{pre[:8]}. The branch {branch} is preserved for inspection.")
        return

    sha = run(["git", "rev-parse", "--short", "main"], cwd=REPO).stdout.strip()
    p = run(["git", "push", "origin", "main"], cwd=REPO)
    push_note = "" if p.returncode == 0 else " (push failed - local only)"
    mark(job_id, status=JobStatus.COMPLETED, done=True)
    builder.cleanup_worktree(job_id)
    notify(chat_id, f"Shipped build {job_id}: {task[:120]}\n"
                    f"Commit {sha}, {test_summary}{push_note}. Live and healthy.")
    log(f"shipped {sha}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", type=int, required=True)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()

    with session_scope() as s:
        job = s.get(Job, a.job_id)
        if not job:
            log(f"no job {a.job_id}")
            return
        task, chat_id, branch = job.prompt, job.telegram_chat_id, job.worker_branch

    wt = builder.BUILDS / f"job{a.job_id}"
    if not wt.exists():
        wt.parent.mkdir(parents=True, exist_ok=True)
        r = run(["git", "worktree", "add", "-b", branch, str(wt), "main"], cwd=REPO)
        if r.returncode != 0:  # branch left over from a previous attempt
            r = run(["git", "worktree", "add", str(wt), branch], cwd=REPO)
        if r.returncode != 0:
            mark(a.job_id, status=JobStatus.FAILED, error="worktree creation failed", done=True)
            notify(chat_id, f"Build {a.job_id} failed to start: could not create a worktree.")
            return

    guidance = ""
    gfile = wt / "GUIDANCE.md"
    if gfile.exists():
        guidance = f"\nGuidance from Bo (follow it):\n{gfile.read_text()}\n"
    prompt = builder.BUILD_PROMPT.format(task=task, guidance=guidance)

    from agents.tmux_supervisor import _resolve_claude
    claude = _resolve_claude()
    log(f"running headless claude on job {a.job_id} (resume={a.resume})...")
    try:
        r = run([claude, "-p", prompt, "--dangerously-skip-permissions"],
                cwd=wt, timeout=builder.CLAUDE_TIMEOUT_SECONDS)
        log(f"claude exited {r.returncode}")
        log((r.stdout or "")[-3000:])
    except subprocess.TimeoutExpired:
        stuck(a.job_id, chat_id, "the build attempt timed out after 40 minutes")
        return

    state, detail = builder.evaluate_worktree(wt, REPO)
    if state == "stuck":
        stuck(a.job_id, chat_id, detail)
        return
    if state == "nochange":
        stuck(a.job_id, chat_id, "the build produced no commits - clarify the task or 'abort'")
        return

    ok, summary = verify(wt)
    if not ok:
        stuck(a.job_id, chat_id, f"suites red after the build: {summary}")
        return

    ship(a.job_id, chat_id, task, branch, wt, summary)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        log(f"runner crashed: {exc!r}")
        raise
