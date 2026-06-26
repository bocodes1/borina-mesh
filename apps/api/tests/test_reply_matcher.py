"""Reply matcher (Phase 3). READ-ONLY: match_replies reads a STUBBED inbox and
NEVER sends. A matched inbound advances the sent OutreachItem to 'replied' and
records an OutreachReply with an UNCONFIRMED flag (interview/rejection are
suggestions, never auto-final). Deduped by graph_message_id. Mirrors
test_apply_pipeline's _clean + spy style."""
import pytest
from sqlmodel import select

from db import session_scope
from models import OutreachItem, OutreachReply
from dispatch import apply as ap
from integrations import outlook
from integrations.base import ok, not_connected


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for r in s.exec(select(OutreachReply)).all():
            s.delete(r)
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    yield


def _seed_sent(email: str, *, status: str = "sent") -> int:
    with session_scope() as s:
        it = OutreachItem(track="swe", company="Acme AI", contact_email=email,
                          subject="Internship", body="hi", company_domain="acme.ai",
                          dedup_key=ap._dedup_key(email, "acme.ai"), status=status)
        s.add(it)
        s.commit()
        s.refresh(it)
        return it.id


def _spy_no_send(monkeypatch):
    calls = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: calls.append(1) or ok("outlook", {"id": "x", "via": "graph"}))
    return calls


def test_classify_reply_buckets():
    assert ap._classify_reply("Re: chat", "Are you free for an interview call?") == "interview"
    assert ap._classify_reply("Update", "Unfortunately we won't be moving forward.") == "rejection"
    assert ap._classify_reply("hi", "Thanks for reaching out.") == "neutral"


def test_match_advances_status_and_records_reply(monkeypatch):
    item_id = _seed_sent("ada@acme.ai")
    calls = _spy_no_send(monkeypatch)
    monkeypatch.setattr(outlook, "list_inbox", lambda since_iso=None, top=25: ok("outlook", [
        {"id": "m1", "from": "ada@acme.ai", "subject": "Re: Internship",
         "received": "2026-06-20T14:00:00Z", "preview": "Want to set up an interview?"},
    ]))
    summary = ap.match_replies()
    assert summary["matched"] == 1
    assert item_id in summary["replied_item_ids"]
    assert summary["flags"][item_id] == "interview"
    assert calls == []                              # READ-ONLY: never sends
    with session_scope() as s:
        assert s.get(OutreachItem, item_id).status == "replied"
        reply = s.exec(select(OutreachReply)).one()
        assert reply.flag == "interview"
        assert reply.confirmed is False             # never auto-final


def test_match_is_idempotent_on_graph_message_id(monkeypatch):
    _seed_sent("ada@acme.ai")
    inbox = [{"id": "m1", "from": "ada@acme.ai", "subject": "Re", "received": "x", "preview": "ok"}]
    monkeypatch.setattr(outlook, "list_inbox", lambda since_iso=None, top=25: ok("outlook", inbox))
    ap.match_replies()
    summary2 = ap.match_replies()                   # same message → no double-record
    assert summary2["matched"] == 0
    with session_scope() as s:
        assert len(s.exec(select(OutreachReply)).all()) == 1


def test_unmatched_sender_is_ignored(monkeypatch):
    _seed_sent("ada@acme.ai")
    monkeypatch.setattr(outlook, "list_inbox", lambda since_iso=None, top=25: ok("outlook", [
        {"id": "m9", "from": "stranger@nowhere.com", "subject": "Spam", "received": "x", "preview": "hi"},
    ]))
    summary = ap.match_replies()
    assert summary["matched"] == 0
    with session_scope() as s:
        assert s.exec(select(OutreachReply)).all() == []


def test_inbox_unconnected_is_no_op(monkeypatch):
    _seed_sent("ada@acme.ai")
    monkeypatch.setattr(outlook, "list_inbox",
                        lambda since_iso=None, top=25: not_connected("outlook", "Outlook not authorized"))
    summary = ap.match_replies()
    assert summary["matched"] == 0
    assert any("not authorized" in r.lower() for r in summary["reasons"])
