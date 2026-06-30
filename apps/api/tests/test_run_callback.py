"""Task 4 — write-node approval gate + the no-autonomous-write regression.

A `write`-kind node NEVER self-executes: when it becomes ready the driver flips
it to `awaiting_approval`, emits an approval Card, and pauses that branch. The
real calendar write happens ONLY in the Telegram approval callback, with
`user_initiated=True` — the exact gate at `integrations/google_calendar.py:101`.
The engine has no path to that flag.
"""
import asyncio
from unittest.mock import patch

from sqlmodel import Session, select

from db import engine
from models import Run, RunTask, TaskEdge
from dispatch.orchestrator import dag


async def _empty(prompt):  # injected node runner that returns nothing
    return ""


def _run_with_write(extra_read=False):
    with Session(engine) as s:
        run = Run(text="t", mode="mission", status="running", chat_id=1)
        s.add(run)
        s.commit()
        s.refresh(run)
        s.add(RunTask(run_id=run.id, key="w", agent="planner", kind="write", prompt="create event"))
        if extra_read:
            s.add(RunTask(run_id=run.id, key="r", agent="researcher", kind="read", prompt="do r"))
        s.commit()
        return run.id


def test_write_node_pauses_and_never_self_executes():
    rid = _run_with_write()
    with patch("integrations.google_calendar.create_event") as mock_write, \
            patch("dispatch.cards.send_card"):
        asyncio.run(dag.drive_run(rid, _empty, max_steps=5))
        assert mock_write.call_count == 0  # NEVER self-executes
    with Session(engine) as s:
        t = list(s.exec(select(RunTask).where(RunTask.run_id == rid)))[0]
        assert t.status == "awaiting_approval"


def test_no_autonomous_write_regression():
    # A DAG with an independent read branch: the run finishes the other branch,
    # the write node sits untapped in awaiting_approval, the helper is never hit.
    rid = _run_with_write(extra_read=True)
    with patch("integrations.google_calendar.create_event") as mock_write, \
            patch("dispatch.cards.send_card"):
        asyncio.run(dag.drive_run(rid, _empty, max_steps=5))
        assert mock_write.call_count == 0
    with Session(engine) as s:
        tasks = {t.key: t.status for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    assert tasks["w"] == "awaiting_approval"
    assert tasks["r"] == "done"


def test_approve_executes_write_user_initiated():
    from routes.telegram import _handle_run_callback

    rid = _run_with_write()
    with patch("dispatch.cards.send_card"):
        asyncio.run(dag.drive_run(rid, _empty, max_steps=5))
    with Session(engine) as s:
        tid = list(s.exec(select(RunTask).where(RunTask.run_id == rid)))[0].id

    with patch("integrations.google_calendar.create_event") as mock_write, \
            patch("dispatch.dispatcher.send_telegram_message"):
        mock_write.return_value = None
        _handle_run_callback(f"run:approve:{tid}", 1)

    assert mock_write.call_count == 1  # executed exactly once
    assert mock_write.call_args.kwargs.get("user_initiated") is True  # via the hard gate
    with Session(engine) as s:
        assert s.get(RunTask, tid).status == "done"


def test_reject_skips_and_blocks_dependents():
    from routes.telegram import _handle_run_callback

    with Session(engine) as s:
        run = Run(text="t", mode="mission", status="running", chat_id=1)
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id
        s.add(RunTask(run_id=rid, key="w", agent="planner", kind="write", prompt="create event"))
        s.add(RunTask(run_id=rid, key="d", agent="researcher", kind="read", prompt="downstream"))
        s.add(TaskEdge(run_id=rid, src="w", dst="d"))
        s.commit()
        tid = s.exec(select(RunTask).where(RunTask.run_id == rid, RunTask.key == "w")).first().id

    with patch("integrations.google_calendar.create_event") as mock_write, \
            patch("dispatch.dispatcher.send_telegram_message"):
        _handle_run_callback(f"run:reject:{tid}", 1)
        assert mock_write.call_count == 0

    with Session(engine) as s:
        tasks = {t.key: t.status for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    assert tasks["w"] == "skipped"
    assert tasks["d"] == "blocked"
