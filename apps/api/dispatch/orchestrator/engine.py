"""The orchestration engine entry point (Task 9).

One async call — `run_orchestration(text, *, mode, chat_id)` — turns a `mission:`
or `goal:` prompt into a driven DAG Run:

  1. create a `Run` + backing `Job(kind="run")`;
  2. ask the CEO to decompose the work into a DAG JSON;
  3. `validate_dag`→`build_dag` the result, or `degrade` to today's
     mission/goal fallback on any garbage;
  4. `drive_run` it with the default per-node agent runner.

`mission` and `goal` are two modes of the one engine (spec §Entry points):
mission runs silently with a dispatch ping + the final synthesized report; goal
emits a check-in at phase boundaries. The per-node runner is the single injected
seam (`_run_node`) so tests drive the whole engine without spawning agents — the
goal runner's testability trick (`dispatch/goal.py:134`).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from db import session_scope
from models import Job, JobStatus, Run
from dispatch.mission import MISSION_AGENTS
from dispatch.orchestrator import dag, decompose
from dispatch.orchestrator.decompose import WRITE_AGENTS

# A unique token the CEO decompose prompt carries so the injected `_run_node`
# stub (and the real call) can tell a decompose request from a node execution.
DECOMPOSE_MARKER = "Decompose this work into a DAG"

DECOMPOSE_PROMPT = (
    DECOMPOSE_MARKER + " of sub-agent tasks.\n"
    "{mode_hint}\n"
    "Work: {text}\n\n"
    "Read agents (read-only intel): {read_agents}.\n"
    "Write agents (calendar proposals, ALWAYS gated behind approval): {write_agents}.\n"
    "synthesize/verify nodes are pinned to the ceo.\n\n"
    "Output ONLY a JSON object (no prose, no code fences):\n"
    '{{"nodes":[{{"key":"<id>","agent":"<agent>","kind":"read|write|synthesize|verify",'
    '"prompt":"<specific task>","depends_on":["<key>",...]}}]}}\n'
    "Rules: at most 8 nodes; exactly one synthesize and one verify, with verify "
    "depending on synthesize; every depends_on must name a declared key; no cycles."
)

_MODE_HINT = {
    "mission": "Ephemeral read-only intel run — fan out independent reads, then synthesize + verify.",
    "goal": "Durable goal — order dependent steps; independent steps may run in parallel.",
}


# ── the single injected per-node runner seam ────────────────────────────────────
async def _run_node(agent: str, prompt: str, job_id: int) -> str:
    """Run one node's agent through the read-only clean-answer pipeline. This is
    the ONLY place the engine reaches a real agent; tests monkeypatch it."""
    from dispatch.answer import run_agent_for_answer

    return await run_agent_for_answer(agent, prompt, job_id)


def create_run(text: str, mode: str, chat_id: Optional[int]) -> tuple[int, int]:
    """Create the backing `Job(kind="run")` and the `Run` row (status=running).
    Returns (run_id, job_id). Mirrors `goal.create_goal`'s job+container shape."""
    with session_scope() as s:
        job = Job(agent_id="ceo", prompt=text, status=JobStatus.RUNNING,
                  kind="run", started_at=datetime.utcnow(), telegram_chat_id=chat_id)
        s.add(job)
        s.commit()
        s.refresh(job)
        run = Run(job_id=job.id, text=text, mode=mode, status="running", chat_id=chat_id)
        s.add(run)
        s.commit()
        s.refresh(run)
        return run.id, job.id


async def _decompose(text: str, mode: str, job_id: int) -> Optional[list[dict]]:
    """Ask the CEO for a DAG, parse + validate it. None → caller degrades."""
    prompt = DECOMPOSE_PROMPT.format(
        text=text,
        mode_hint=_MODE_HINT.get(mode, ""),
        read_agents=", ".join(sorted(MISSION_AGENTS)),
        write_agents=", ".join(sorted(WRITE_AGENTS)),
    )
    try:
        raw = await _run_node("ceo", prompt, job_id)
    except Exception:  # noqa: BLE001 — a flaky decompose degrades, never raises
        return None
    return decompose.validate_dag(decompose.parse_dag(raw))


def _checkin_text(snap: dict) -> str:
    nodes = snap.get("nodes", [])
    done = sum(1 for n in nodes if n["status"] == "done")
    last = next((n for n in reversed(nodes) if n.get("result")), None)
    tail = f" — {last['result'][:200]}" if last else ""
    return f"Goal run {snap.get('id')} check-in: {done}/{len(nodes)} nodes done{tail}"


async def run_orchestration(
    text: str, *, mode: str, chat_id: Optional[int] = None, job_id: Optional[int] = None
) -> dict:
    """Create (unless `job_id`/run already exists), decompose, build-or-degrade,
    and drive a Run to completion. Returns a snapshot dict + the final report.

    `job_id` lets the caller (the dispatcher worker) reuse an already-created job
    row instead of spawning a second one."""
    run_id, jid = _make_run(text, mode, chat_id, job_id)
    return await _run(run_id, jid, mode, chat_id, text)


def _make_run(text, mode, chat_id, job_id) -> tuple[int, int]:
    if job_id is not None:
        with session_scope() as s:
            run = Run(job_id=job_id, text=text, mode=mode, status="running", chat_id=chat_id)
            s.add(run)
            s.commit()
            s.refresh(run)
            return run.id, job_id
    return create_run(text, mode, chat_id)


async def _run(run_id: int, job_id: int, mode: str, chat_id: Optional[int], text: str) -> dict:
    """Decompose → build/degrade → drive. Shared by the awaited and fire-and-forget
    entry points. Decompose runs ONCE: a resume/steer relaunch finds the DAG
    already built and goes straight to driving (the ready-set loop reruns only
    non-`done` nodes)."""
    if not _has_dag(run_id):
        nodes = await _decompose(text, mode, job_id)
        if nodes:
            decompose.build_dag(run_id, nodes)
        else:
            decompose.degrade(run_id, text, mode)

    async def runner(prompt: str, agent: str) -> str:
        return await _run_node(agent, prompt, job_id)

    on_checkin = None
    progress = None
    if chat_id:
        from dispatch import dispatcher
        from dispatch.telegram_format import format_telegram

        if mode == "goal":
            def on_checkin(snap: dict) -> None:  # noqa: ANN001
                dispatcher.send_telegram_message(chat_id, format_telegram(_checkin_text(snap)))
        else:
            def progress(msg: str) -> None:  # noqa: ANN001
                dispatcher.send_telegram_message(chat_id, format_telegram(msg))

    snap = await dag.drive_run(run_id, runner, on_checkin=on_checkin, progress=progress)
    _complete_job(job_id, mode)
    snap["run_id"] = run_id
    snap["job_id"] = job_id
    snap["report"] = _report(snap)
    return snap


def _has_dag(run_id: int) -> bool:
    from sqlmodel import select
    from models import RunTask

    with session_scope() as s:
        return s.exec(select(RunTask).where(RunTask.run_id == run_id)).first() is not None


def _report(snap: dict) -> str:
    """The final synthesized report (the synthesize node's result), else a join of
    the done leaves — same degrade shape the driver uses (`dag._final_report`)."""
    nodes = snap.get("nodes", [])
    synth = [n for n in nodes if n["kind"] == "synthesize" and n.get("result")]
    if synth:
        return synth[-1]["result"] or ""
    return "\n\n".join(n["result"] for n in nodes if n["status"] == "done" and n.get("result"))


def _complete_job(job_id: int, mode: str) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job and job.status == JobStatus.RUNNING:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            s.add(job)
            s.commit()


# ── fire-and-forget launch (mirrors goal.launch_goal) ───────────────────────────
def launch_orchestration(run_id: int, mode: str, chat_id: Optional[int], text: str) -> bool:
    """Schedule the decompose+drive on the running loop (fire-and-forget). The Run
    row already exists (created via `create_run`). Returns False with no loop
    (caller may await `run_orchestration` directly in tests)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    async def _go():
        with session_scope() as s:
            r = s.get(Run, run_id)
            job_id = (r.job_id or 0) if r else 0
        await _run(run_id, job_id, mode, chat_id, text)

    loop.create_task(_go())
    return True


def handle_run_reply(thread, text: str, chat_id: int) -> dict:
    """A reply to a goal-run check-in: 'abort' cancels cooperatively; anything else
    is steering guidance, applied then the run resumes. Mirrors
    `goal.handle_goal_reply` but over the Run/RunTask graph."""
    from dispatch import dispatcher
    from dispatch.telegram_format import format_telegram

    run_id = thread.job_id  # run threads are anchored by run id
    if (text or "").strip().lower() in {"abort", "cancel", "stop"}:
        dag.request_cancel(run_id)
        dispatcher.send_telegram_message(chat_id, format_telegram(f"Run {run_id} aborting at the next boundary."))
        return {"ok": True, "status": "run_aborted", "run_id": run_id}
    dag.add_guidance(run_id, text)
    with session_scope() as s:
        r = s.get(Run, run_id)
        mode = r.mode if r else "goal"
        run_text = r.text if r else text
    launch_orchestration(run_id, mode, chat_id, run_text)
    dispatcher.send_telegram_message(chat_id, format_telegram(f"Run {run_id} steering noted — resuming."))
    return {"ok": True, "status": "run_steered", "run_id": run_id}
