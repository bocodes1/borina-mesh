"""Tests for scheduler QA gatekeeper integration."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from agents.qa_director import ReviewVerdict, _parse_verdict


# ---------------------------------------------------------------------------
# _parse_verdict unit tests (pure function, no I/O)
# ---------------------------------------------------------------------------

def test_parse_verdict_approve():
    result = _parse_verdict("APPROVE")
    assert result.verdict == ReviewVerdict.APPROVE
    assert result.notes == ""


def test_parse_verdict_approve_with_notes():
    result = _parse_verdict("APPROVE_WITH_NOTES: minor typo on line 3")
    assert result.verdict == ReviewVerdict.APPROVE_WITH_NOTES
    assert result.notes == "minor typo on line 3"


def test_parse_verdict_request_rerun():
    result = _parse_verdict("REQUEST_RERUN: missing data section")
    assert result.verdict == ReviewVerdict.REQUEST_RERUN
    assert result.notes == "missing data section"


def test_parse_verdict_block():
    result = _parse_verdict("BLOCK: hallucinated tool output")
    assert result.verdict == ReviewVerdict.BLOCK
    assert result.notes == "hallucinated tool output"


def test_parse_verdict_unknown_defaults_to_approve_with_notes():
    result = _parse_verdict("some random text that is not a verdict")
    assert result.verdict == ReviewVerdict.APPROVE_WITH_NOTES
    assert "unparsed" in result.notes


def test_parse_verdict_empty_string():
    result = _parse_verdict("")
    assert result.verdict == ReviewVerdict.APPROVE_WITH_NOTES


# ---------------------------------------------------------------------------
# Helpers for async generator mocking
# ---------------------------------------------------------------------------

def _make_stream_fn(chunks):
    """Return an async generator function that yields the given dicts."""
    async def _stream(*args, **kwargs):
        for c in chunks:
            yield c
    return _stream


# ---------------------------------------------------------------------------
# QA gatekeeper integration inside _run_agent
#
# Session/engine/Job/AgentRun/JobStatus are imported locally inside _run_agent,
# so we patch them at their source modules rather than via scheduler.* names.
# ---------------------------------------------------------------------------

def _make_session_ctx(fake_job):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.get.return_value = fake_job
    return ctx


def _make_status():
    s = MagicMock()
    s.RUNNING = "running"
    s.COMPLETED = "completed"
    s.FAILED = "failed"
    return s


@pytest.mark.asyncio
async def test_scheduled_run_does_not_call_qa():
    """§A2: a scheduled/cron agent run must NOT trigger QADirector.review (the
    recurring-Opus cost). The job still completes and an AgentRun is saved, but
    with no QA verdict."""
    from scheduler import SchedulerService
    svc = SchedulerService()

    fake_agent = MagicMock()
    fake_agent.name = "FakeAgent"
    fake_agent.stream = _make_stream_fn([{"type": "text", "content": "good output"}])

    fake_job = MagicMock()
    fake_job.id = 1

    mock_qa = MagicMock()
    mock_qa.review = AsyncMock()
    qa_cls = MagicMock(return_value=mock_qa)

    with (
        patch("sqlmodel.Session", return_value=_make_session_ctx(fake_job)),
        patch("db.engine", MagicMock()),
        patch("models.Job", MagicMock(return_value=fake_job)),
        patch("models.AgentRun") as mock_agent_run_cls,
        patch("models.JobStatus", _make_status()),
        patch("agents.base.registry") as mock_registry,
        patch("agents.qa_director.QADirector", qa_cls),
        patch("scheduler.bus") as mock_bus,
        patch("scheduler.asyncio.get_event_loop") as mock_loop,
        patch("artifacts.save_run_output", MagicMock()),
    ):
        mock_bus.publish = AsyncMock()
        mock_loop.return_value.time.return_value = 0.0
        mock_registry.get.return_value = fake_agent
        await svc._run_agent("fake-agent")

    # QA must never be constructed or invoked on the cron path.
    qa_cls.assert_not_called()
    mock_qa.review.assert_not_called()
    # Job still completes; AgentRun persisted without a QA verdict.
    assert fake_job.status == "completed"
    assert fake_job.qa_verdict is None
    mock_agent_run_cls.assert_called_once()
    _, kwargs = mock_agent_run_cls.call_args
    assert kwargs.get("qa_verdict") is None


# ---------------------------------------------------------------------------
# §A1 — trader LLM cron removed; cheap non-LLM uptime ping replaces it
# ---------------------------------------------------------------------------

def test_register_defaults_drops_trader_ceo_researcher_crons():
    """§A1/§A3: no recurring LLM cron for trader, ceo, or researcher; the 2h
    inbox-triage digest survives."""
    import agents.inbox, agents.trader, agents.ceo, agents.researcher  # noqa: F401  populate registry
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    from scheduler import SchedulerService
    svc = SchedulerService()
    svc.register_defaults()
    sched = svc.list_schedules()
    assert "trader" not in sched
    assert "ceo" not in sched
    assert "researcher" not in sched
    assert "inbox-triage" in sched


@pytest.mark.asyncio
async def test_trader_health_silent_when_healthy(monkeypatch):
    """The non-LLM uptime ping stays silent when the bot is healthy (no cost,
    no noise)."""
    monkeypatch.setenv("TRADER_BOT_HEALTH_URL", "http://bot.local/health")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    import httpx
    from dispatch import dispatcher
    sent = []

    class _Resp:
        status_code = 200

    monkeypatch.setattr(httpx, "get", lambda url, timeout=10.0: _Resp())
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda c, t, **k: sent.append(t) or 1)
    from scheduler import SchedulerService
    await SchedulerService()._run_trader_health()
    assert sent == []


@pytest.mark.asyncio
async def test_trader_health_pings_bo_on_failure(monkeypatch):
    """The non-LLM uptime ping messages Bo only when the bot is unreachable."""
    monkeypatch.setenv("TRADER_BOT_HEALTH_URL", "http://bot.local/health")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    import httpx
    from dispatch import dispatcher
    sent = []

    def _boom(url, timeout=10.0):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda c, t, **k: sent.append(t) or 1)
    from scheduler import SchedulerService
    await SchedulerService()._run_trader_health()
    assert any("health check failed" in t for t in sent)


@pytest.mark.asyncio
async def test_trader_health_noop_without_url(monkeypatch):
    """No health URL configured → the ping is inert (safe in dev/CI)."""
    monkeypatch.delenv("TRADER_BOT_HEALTH_URL", raising=False)
    from scheduler import SchedulerService
    await SchedulerService()._run_trader_health()  # must not raise


# ---------------------------------------------------------------------------
# §A4 — dedicated register_* methods honor the fleet roster gate
# ---------------------------------------------------------------------------

def test_register_finance_brief_skips_retired_finance():
    """finance is RETIRED in the roster → finance-brief must not schedule."""
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    from scheduler import SchedulerService
    svc = SchedulerService()
    svc.register_finance_brief()
    assert "finance-brief" not in svc.list_schedules()


def test_register_planner_schedules_when_active():
    """planner is the consolidated morning brief (ACTIVE) → it schedules."""
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    from scheduler import SchedulerService
    svc = SchedulerService()
    svc.register_planner()
    assert "planner" in svc.list_schedules()


def test_register_planner_skips_when_retired():
    """§A4 guard: a retired planner does not schedule (gate honored)."""
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    fr.set_state("planner", fr.RETIRED)
    try:
        from scheduler import SchedulerService
        svc = SchedulerService()
        svc.register_planner()
        assert "planner" not in svc.list_schedules()
    finally:
        fr.set_state("planner", fr.ACTIVE)


def test_register_operator_schedules_midday_eod_not_morning():
    """§A3: operator-morning is gone; only midday + eod register."""
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    from scheduler import SchedulerService
    svc = SchedulerService()
    svc.register_operator()
    sched = svc.list_schedules()
    assert "operator-midday" in sched
    assert "operator-eod" in sched
    assert "operator-morning" not in sched


def test_register_operator_skips_when_retired():
    """§A4: retiring the operator stops it scheduling."""
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    fr.set_state("operator", fr.RETIRED)
    try:
        from scheduler import SchedulerService
        svc = SchedulerService()
        svc.register_operator()
        sched = svc.list_schedules()
        assert "operator-midday" not in sched
        assert "operator-eod" not in sched
    finally:
        fr.set_state("operator", fr.ACTIVE)
