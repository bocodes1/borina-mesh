"""Posting approval surface (Phase 2): a posting card with Submit/Skip/Open; the
apply:submit tap is the user-initiated submit; apply:pskip skips; apply:open
surfaces the link. Mirrors test_apply_telegram."""
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


def _posting(**over):
    base = {"id": 5, "track": "swe", "source": "wellfound", "company": "Acme AI",
            "role_title": "AI SWE Intern", "location": "Toronto",
            "posting_url": "https://boards.greenhouse.io/acme/jobs/9",
            "submit_method": "form", "ats": "greenhouse",
            "cover_letter": "Dear Acme team, ..."}
    base.update(over)
    return base


def test_posting_card_has_submit_skip_open():
    card = tg.posting_card(_posting())
    datas = [a.data for a in card.actions]
    assert "apply:submit:5" in datas
    assert "apply:pskip:5" in datas
    assert "apply:open:5" in datas


def test_apply_submit_callback_invokes_submit_posting(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "submit_posting",
                        lambda i: calls.append(i) or {"status": "prepared", "method": "form",
                                                       "review_url": "https://x/9"})
    res = tg._handle_apply_callback("apply:submit:5", 99)
    assert res["status"] == "apply_submit"
    assert calls == [5]


def test_apply_submit_email_reports_submitted(monkeypatch, _capture):
    monkeypatch.setattr(ap, "submit_posting",
                        lambda i: {"status": "submitted", "method": "email", "company": "FinML"})
    res = tg._handle_apply_callback("apply:submit:7", 99)
    assert res["status"] == "apply_submit"
    assert any("FinML" in m["text"] for m in _capture)


def test_apply_pskip_callback_invokes_skip_posting(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "skip_posting", lambda i: calls.append(i) or {"status": "skipped"})
    res = tg._handle_apply_callback("apply:pskip:5", 99)
    assert res["status"] == "apply_pskip"
    assert calls == [5]


def test_apply_open_surfaces_link(monkeypatch, _capture):
    monkeypatch.setattr(ap, "get_proposed_postings", lambda: [_posting()])
    res = tg._handle_apply_callback("apply:open:5", 99)
    assert res["status"] == "apply_open"
    assert any("greenhouse.io" in m["text"] for m in _capture)


def test_handle_callback_routes_submit_prefix(monkeypatch, _capture):
    monkeypatch.setattr(ap, "submit_posting",
                        lambda i: {"status": "prepared", "method": "external",
                                   "handoff": {"posting_url": "u", "cover_letter": "c", "answers": {}}})
    res = tg._handle_callback("apply:submit:3", 99)
    assert res["status"] == "apply_submit"
