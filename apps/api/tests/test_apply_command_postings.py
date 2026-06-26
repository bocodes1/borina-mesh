"""The apply: command + weekly cron cover BOTH cold emails and postings (Phase 2),
each its own card. Neither path submits. Mirrors test_apply_telegram +
test_apply_scheduler."""
import pytest

import routes.telegram as tg
from dispatch import dispatcher
from dispatch import apply as ap


@pytest.fixture(autouse=True)
def _capture(monkeypatch):
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    sent = []

    def _fake_send(chat_id, text, reply_markup=None):
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return 1

    monkeypatch.setattr(dispatcher, "send_telegram_message", _fake_send)
    return sent


def test_apply_command_stages_emails_and_postings(monkeypatch, _capture):
    BO = 6452258223
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 0, "item_ids": [11], "reasons": []}

    async def fake_postings(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 1, "item_ids": [21],
                "reasons": ["BigCo AI Intern: dedup (already staged)"]}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "run_postings", fake_postings)
    monkeypatch.setattr(ap, "get_proposed", lambda: [
        {"id": 11, "track": "swe", "company": "Acme AI",
         "contact_email": "ada@acme.ai", "subject": "S", "body": "B"}])
    monkeypatch.setattr(ap, "get_proposed_postings", lambda: [
        {"id": 21, "track": "swe", "source": "wellfound", "company": "FinML",
         "role_title": "AI SWE Intern", "location": "Remote",
         "posting_url": "https://boards.greenhouse.io/finml/jobs/1",
         "submit_method": "form", "ats": "greenhouse", "cover_letter": "Dear ..."}])

    update = {"update_id": 1, "message": {"chat": {"id": BO}, "text": "apply: AI internships"}}
    res = tg.process_update(update)
    assert res["status"] == "apply_started"
    datas = [b["callback_data"] for m in _capture if m["reply_markup"]
             for row in m["reply_markup"]["inline_keyboard"] for b in row]
    assert "apply:send:11" in datas      # cold-email card
    assert "apply:submit:21" in datas    # posting card
    # drop counts surfaced (no silent caps)
    assert any("dropped" in m["text"].lower() for m in _capture)


@pytest.mark.asyncio
async def test_weekly_cron_stages_both_without_submitting(monkeypatch):
    from scheduler import SchedulerService
    from integrations import outlook
    from integrations.base import ok

    acted = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: acted.append("send") or ok("outlook", {"id": "x", "via": "graph"}))
    monkeypatch.setattr(outlook.BrowserFiller, "fill",
                        lambda self, *a, **k: acted.append("fill") or {"filled": True, "submitted": False, "review_url": "u"})

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 0, "item_ids": [1], "reasons": []}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "run_postings", fake_run)
    monkeypatch.setattr(ap, "get_proposed", lambda: [])
    monkeypatch.setattr(ap, "get_proposed_postings", lambda: [])
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    svc = SchedulerService()
    await svc._run_apply_weekly()
    assert acted == []  # the cron stages both kinds, submits nothing
