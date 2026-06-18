"""L3 goal long-runner — decompose, durable driver, cancel/steer, resume, cards."""
import pytest

from dispatch import goal as G


@pytest.fixture(autouse=True)
def _db():
    from db import engine
    import models  # noqa: F401 — ensure tables
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(engine)
    yield


async def _runner_ok(prompt):
    return "Did the step. Result: looks good."


# ── decompose ──────────────────────────────────────────────────────────────────
def test_parse_milestones():
    assert G.parse_milestones('["a", "b", "c"]') == ["a", "b", "c"]
    assert G.parse_milestones("garbage no json") is None


@pytest.mark.asyncio
async def test_decompose_degrades_to_single():
    async def bad(prompt):
        return "not json at all"
    titles = await G.decompose_goal("ship the thing", bad)
    assert titles == ["ship the thing"]


@pytest.mark.asyncio
async def test_decompose_uses_agent_output():
    async def run(prompt):
        return 'Here you go: ["Research", "Draft", "Verify"]'
    assert await G.decompose_goal("x", run) == ["Research", "Draft", "Verify"]


# ── driver ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_driver_completes_all_milestones():
    gid = G.create_goal("write a report", chat_id=None)
    G.set_milestones(gid, ["one", "two", "three"])
    checkins = []
    final = await G.advance_goal(gid, _runner_ok, on_checkin=lambda g: checkins.append(g["cursor"]))
    assert final["status"] == "done"
    assert all(m["status"] == "done" for m in final["milestones"])
    assert checkins == [1, 2, 3]                 # a check-in after each milestone


@pytest.mark.asyncio
async def test_driver_stops_on_cancel():
    gid = G.create_goal("long thing", chat_id=None)
    G.set_milestones(gid, ["one", "two", "three"])
    G.request_cancel(gid)
    final = await G.advance_goal(gid, _runner_ok)
    assert final["status"] == "aborted"
    # nothing ran
    assert all(m["status"] == "pending" for m in final["milestones"])


@pytest.mark.asyncio
async def test_driver_blocks_on_milestone_failure():
    gid = G.create_goal("risky", chat_id=None)
    G.set_milestones(gid, ["one", "two"])

    async def boom(prompt):
        raise RuntimeError("nope")
    final = await G.advance_goal(gid, boom)
    assert final["status"] == "paused"
    assert final["milestones"][0]["status"] == "blocked"
    assert final["milestones"][1]["status"] == "pending"   # didn't continue past the block


@pytest.mark.asyncio
async def test_resume_does_not_redo_done_milestones():
    gid = G.create_goal("resumable", chat_id=None)
    G.set_milestones(gid, ["one", "two", "three"])
    calls = []

    async def once(prompt):
        calls.append(prompt)
        return "ok"
    # First pass: mark first milestone done by running a single step via cancel-after.
    await G.advance_goal(gid, once, max_steps=1)
    done_after_first = [m["status"] for m in G.get_goal(gid)["milestones"]]
    assert done_after_first.count("done") == 1
    # Resume: should only run the remaining two.
    calls.clear()
    final = await G.advance_goal(gid, once)
    assert final["status"] == "done"
    assert len(calls) == 2                        # only the 2 remaining ran


# ── steering ─────────────────────────────────────────────────────────────────
def test_add_guidance_resumes_and_annotates():
    gid = G.create_goal("steer me", chat_id=None)
    G.set_milestones(gid, ["alpha", "beta"])
    G.request_cancel(gid)
    G.add_guidance(gid, "focus on beta first")
    snap = G.get_goal(gid)
    assert snap["cancel_requested"] is False      # guidance clears the cancel
    assert snap["status"] == "running"
    assert "focus on beta first" in snap["milestones"][0]["title"]


# ── check-in card ──────────────────────────────────────────────────────────────
def test_checkin_card_actions():
    gid = G.create_goal("g", chat_id=123)
    G.set_milestones(gid, ["a", "b"])
    card = G.checkin_card(G.get_goal(gid))
    datas = [a.data for a in card.actions]
    assert datas == [f"goal:cont:{gid}", f"goal:steer:{gid}", f"goal:abort:{gid}"]


# ── recovery ─────────────────────────────────────────────────────────────────
def test_recover_goals_pauses_live():
    gid = G.create_goal("interrupted", chat_id=None)
    G.set_milestones(gid, ["a"])                  # status -> running
    n = G.recover_goals()
    assert n >= 1
    assert G.get_goal(gid)["status"] == "paused"


# ── callback routing ─────────────────────────────────────────────────────────
def test_goal_callback_abort_sets_flag(monkeypatch):
    import routes.telegram as tg
    from dispatch import dispatcher
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: 1)
    gid = G.create_goal("x", chat_id=None)
    G.set_milestones(gid, ["a"])
    res = tg._handle_callback(f"goal:abort:{gid}", 99)
    assert res["status"] == "goal_abort"
    assert G.get_goal(gid)["cancel_requested"] is True
