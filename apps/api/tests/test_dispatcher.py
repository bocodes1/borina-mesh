"""Dispatcher (spec §8b.4 / §10b): intent → agent(mock) → PDF artifact tagged
source:telegram → retrievable via the artifacts API."""
import asyncio
from pathlib import Path

from dispatch import dispatcher
from dispatch.intent import Intent
from artifacts import list_artifacts, get_artifact_path

BO = 6452258223


def _async_return(value):
    async def f(*a, **k):
        return value
    return f


def _intent():
    return Intent(
        raw_text="verify my stocks and any news",
        agent="researcher",
        task_type="finance_deep_dive",
        params={"use_watchlist": True, "want_news": True},
        confidence=0.92,
        source="alias",
    )


def test_dispatch_registers_telegram_artifact(monkeypatch):
    # Mock the agent + telegram sends; mock PDF render to keep it fast/hermetic.
    monkeypatch.setattr(dispatcher, "run_agent", _async_return("# Stocks\n\nAAPL steady; no thesis change."))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)
    monkeypatch.setattr(
        dispatcher, "render_markdown_pdf",
        lambda md, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"%PDF-1.4 fake"), out)[-1],
    )

    result = asyncio.run(dispatcher.dispatch_intent(_intent(), chat_id=BO, requested_at="2026-06-02T10:00:00"))

    art = result["artifact"]
    # appears in the artifacts API listing
    assert any(a.name == art["name"] for a in list_artifacts())
    # carries source:telegram metadata
    meta = dispatcher.read_artifact_meta(art["date"], art["name"])
    assert meta["source"] == "telegram"
    assert meta["agent"] == "researcher"
    assert meta["prompt"] == "verify my stocks and any news"
    assert meta["requested_at"] == "2026-06-02T10:00:00"
    # retrievable via the artifacts API path resolver
    p = get_artifact_path(art["date"], art["name"])
    assert Path(p).exists()
    # deep link points at the dashboard artifacts view
    assert "/artifacts?id=" in result["deep_link"]


def test_dispatch_creates_job_row(monkeypatch):
    monkeypatch.setattr(dispatcher, "run_agent", _async_return("# R\n\nok"))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)
    monkeypatch.setattr(
        dispatcher, "render_markdown_pdf",
        lambda md, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"%PDF"), out)[-1],
    )
    result = asyncio.run(dispatcher.dispatch_intent(_intent(), chat_id=BO))
    from db import session_scope
    from models import Job
    with session_scope() as s:
        job = s.get(Job, result["job_id"])
        assert job is not None and job.kind == "telegram_dispatch" and job.agent_id == "researcher"


def test_real_weasyprint_render(tmp_path):
    # Prove the md→PDF pipeline actually works (real WeasyPrint).
    out = tmp_path / "r.pdf"
    dispatcher.render_markdown_pdf("# Title\n\nHello **world**.", out)
    assert out.exists() and out.read_bytes()[:4] == b"%PDF"
