"""Slash commands + structured Card channel + generalized callback routing."""
import pytest

from dispatch.cards import Card, Action, render_card
from dispatch import dispatcher
import routes.telegram as tg


@pytest.fixture(autouse=True)
def _roster_and_capture(monkeypatch):
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    sent = []

    def _fake_send(chat_id, text, reply_markup=None):
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return 1

    monkeypatch.setattr(dispatcher, "send_telegram_message", _fake_send)
    return sent


# ── Card model ───────────────────────────────────────────────────────────────
def test_render_card_html_and_keyboard():
    card = Card(headline="Day plan", lines=["move standup", "add focus block"],
                actions=[Action("Approve all", "op:approveall:2026-06-18"),
                         Action("Skip", "op:skip:2026-06-18")])
    text, markup = render_card(card)
    assert "<b>Day plan</b>" in text
    assert "• move standup" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == "op:approveall:2026-06-18"


def test_action_rejects_oversized_callback_data():
    with pytest.raises(ValueError):
        Action("x", "y" * 65)


# ── commands ───────────────────────────────────────────────────────────────────
def test_help_command(_roster_and_capture):
    tg._handle_command("help", "", 99)
    assert _roster_and_capture and "Borina" in _roster_and_capture[0]["text"]
    assert "/jobs" in _roster_and_capture[0]["text"]


def test_fleet_command_lists_states(_roster_and_capture):
    tg._handle_command("fleet", "", 99)
    text = _roster_and_capture[0]["text"]
    assert "trader" in text
    # parked agents show a reactivate button
    kb = _roster_and_capture[0]["reply_markup"]["inline_keyboard"]
    datas = [b["callback_data"] for row in kb for b in row]
    assert any(d.startswith("unpark:") for d in datas)


def test_jobs_command_renders_card(_roster_and_capture):
    tg._handle_command("jobs", "", 99)
    assert "running" in _roster_and_capture[0]["text"]


def test_cancel_command_usage(_roster_and_capture):
    tg._handle_command("cancel", "", 99)
    assert "Usage" in _roster_and_capture[0]["text"]


def test_cancel_command_cancels_running_job(_roster_and_capture):
    from db import engine
    from models import Job, JobStatus
    from sqlmodel import Session
    with Session(engine) as s:
        job = Job(agent_id="trader", prompt="x", status=JobStatus.RUNNING)
        s.add(job)
        s.commit()
        s.refresh(job)
        jid = job.id
    tg._handle_command("cancel", str(jid), 99)
    with Session(engine) as s:
        assert s.get(Job, jid).status == JobStatus.CANCELLED


# ── callback routing ─────────────────────────────────────────────────────────
def test_callback_cancel_routes(_roster_and_capture):
    from db import engine
    from models import Job, JobStatus
    from sqlmodel import Session
    with Session(engine) as s:
        job = Job(agent_id="trader", prompt="x", status=JobStatus.RUNNING)
        s.add(job)
        s.commit()
        s.refresh(job)
        jid = job.id
    res = tg._handle_callback(f"cancel:{jid}", 99)
    assert res["status"] == "cancel"
    with Session(engine) as s:
        assert s.get(Job, jid).status == JobStatus.CANCELLED


def test_callback_unpark_reactivates(_roster_and_capture):
    import fleet_roster as fr
    fr.set_state("ecommerce-scout", fr.PARKED)
    res = tg._handle_callback("unpark:ecommerce-scout", 99)
    assert res["status"] == "unpark"
    assert fr.get_state("ecommerce-scout") == fr.ACTIVE
    fr.set_state("ecommerce-scout", fr.PARKED)  # restore


def test_command_via_process_update_allowlisted(monkeypatch, _roster_and_capture):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "777")
    out = tg.process_update({"update_id": 1, "message": {"chat": {"id": 777}, "text": "/help"}})
    assert out["status"] == "help"


def test_setmycommands_noop_without_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert tg.set_my_commands() is False
