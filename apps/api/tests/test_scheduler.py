"""Tests for scheduler QA gatekeeper integration."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from agents.qa_director import ReviewVerdict, ReviewResult, _parse_verdict


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
async def test_qa_approve_path():
    """Happy path: QA approves -> AgentRun saved with approve verdict."""
    from scheduler import SchedulerService
    svc = SchedulerService()

    fake_agent = MagicMock()
    fake_agent.name = "FakeAgent"
    fake_agent.stream = _make_stream_fn([{"type": "text", "content": "good output"}])

    approve_review = ReviewResult(ReviewVerdict.APPROVE, "")
    fake_job = MagicMock()
    fake_job.id = 1

    mock_qa = MagicMock()
    mock_qa.review = AsyncMock(return_value=approve_review)

    with (
        patch("sqlmodel.Session", return_value=_make_session_ctx(fake_job)),
        patch("db.engine", MagicMock()),
        patch("models.Job", MagicMock(return_value=fake_job)),
        patch("models.AgentRun") as mock_agent_run_cls,
        patch("models.JobStatus", _make_status()),
        patch("agents.base.registry") as mock_registry,
        patch("agents.qa_director.QADirector", return_value=mock_qa),
        patch("scheduler.bus") as mock_bus,
        patch("scheduler.asyncio.get_event_loop") as mock_loop,
        patch("artifacts.save_run_output", MagicMock()),
    ):
        mock_bus.publish = AsyncMock()
        mock_loop.return_value.time.return_value = 0.0
        mock_registry.get.return_value = fake_agent
        await svc._run_agent("fake-agent")

    assert fake_job.status == "completed"
    assert fake_job.qa_verdict == ReviewVerdict.APPROVE.value
    mock_agent_run_cls.assert_called_once()
    _, kwargs = mock_agent_run_cls.call_args
    assert kwargs.get("qa_verdict") == ReviewVerdict.APPROVE.value


@pytest.mark.asyncio
async def test_qa_request_rerun_retries_once():
    """REQUEST_RERUN triggers exactly one retry; second review verdict is stored."""
    from scheduler import SchedulerService
    svc = SchedulerService()

    fake_agent = MagicMock()
    fake_agent.name = "FakeAgent"
    fake_agent.stream = _make_stream_fn([{"type": "text", "content": "output"}])

    call_count = 0

    async def fake_review(artifact, original_request=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ReviewResult(ReviewVerdict.REQUEST_RERUN, "add more detail")
        return ReviewResult(ReviewVerdict.APPROVE, "")

    fake_job = MagicMock()
    fake_job.id = 1

    mock_qa = MagicMock()
    mock_qa.review = fake_review

    with (
        patch("sqlmodel.Session", return_value=_make_session_ctx(fake_job)),
        patch("db.engine", MagicMock()),
        patch("models.Job", MagicMock(return_value=fake_job)),
        patch("models.AgentRun"),
        patch("models.JobStatus", _make_status()),
        patch("agents.base.registry") as mock_registry,
        patch("agents.qa_director.QADirector", return_value=mock_qa),
        patch("scheduler.bus") as mock_bus,
        patch("scheduler.asyncio.get_event_loop") as mock_loop,
        patch("artifacts.save_run_output", MagicMock()),
    ):
        mock_bus.publish = AsyncMock()
        mock_loop.return_value.time.return_value = 0.0
        mock_registry.get.return_value = fake_agent
        await svc._run_agent("fake-agent")

    assert call_count == 2
    assert fake_job.qa_verdict == ReviewVerdict.APPROVE.value


@pytest.mark.asyncio
async def test_qa_review_exception_does_not_fail_job():
    """If QA review raises, the job still completes and qa_notes records the error."""
    from scheduler import SchedulerService
    svc = SchedulerService()

    fake_agent = MagicMock()
    fake_agent.name = "FakeAgent"
    fake_agent.stream = _make_stream_fn([{"type": "text", "content": "output"}])

    fake_job = MagicMock()
    fake_job.id = 1

    mock_qa = MagicMock()
    mock_qa.review = AsyncMock(side_effect=RuntimeError("network timeout"))

    with (
        patch("sqlmodel.Session", return_value=_make_session_ctx(fake_job)),
        patch("db.engine", MagicMock()),
        patch("models.Job", MagicMock(return_value=fake_job)),
        patch("models.AgentRun"),
        patch("models.JobStatus", _make_status()),
        patch("agents.base.registry") as mock_registry,
        patch("agents.qa_director.QADirector", return_value=mock_qa),
        patch("scheduler.bus") as mock_bus,
        patch("scheduler.asyncio.get_event_loop") as mock_loop,
        patch("artifacts.save_run_output", MagicMock()),
    ):
        mock_bus.publish = AsyncMock()
        mock_loop.return_value.time.return_value = 0.0
        mock_registry.get.return_value = fake_agent
        await svc._run_agent("fake-agent")

    assert fake_job.status == "completed"
    assert fake_job.qa_notes is not None
    assert "QA review failed" in fake_job.qa_notes
