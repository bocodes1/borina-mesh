> For agentic workers: use superpowers:subagent-driven-development or executing-plans

**Goal:** Build Phase 3 (tracking, reply detection, follow-ups, `/outreach` frontend tab + weekly digest) of the internship cold-applier. Reply detection reads Bo's Microsoft mailbox (additive `Mail.Read` scope), matches inbound mail to a Phase-1 `OutreachItem` by recipient, advances its status to `replied`, and FLAGS interview/rejection language for Bo's confirmation — never auto-finalizing. After 7 days with no reply, a one-per-contact follow-up is drafted, staged as an approval card, and sent ONLY via the Phase-1 `approve_send` path (respecting the daily cap + blocklist). A read-only `routes/outreach.py` + an `/outreach` Next.js tab surface the pipeline; a weekly digest card hangs off the existing Monday cron slot. Spec: `/Users/clawd/borina-mesh/docs/superpowers/specs/2026-06-26-internship-cold-applier-design.md`.

**Architecture:** Mirror the existing mesh exactly and BUILD ON Phase 1 — never redefine its interfaces. The mailbox reader extends `integrations/outlook.py` (Graph `GET /me/messages`, read-only, `@safe`, returns `IntegrationResult`); the `Mail.Read` scope is appended in `integrations/microsoft_oauth.py`'s existing `SCOPE` constant. Reply matching + follow-up drafting/staging live in `dispatch/apply.py` alongside Phase 1's `run_apply`/`approve_send` (text/data-only; follow-ups are new `OutreachItem` rows staged exactly like cold emails and sent through the SAME `approve_send` gate). A new `OutreachReply` SQLModel table records matched inbound mail (auto-creates via `init_db`'s `create_all` — no ALTER of Phase 1's `OutreachItem`). `routes/outreach.py` mirrors `routes/daily.py`'s read-only summary handler. The `/outreach` Next.js tab mirrors `/daily` (`app/outreach/page.tsx`, `nav-config.ts` link, `lib/api.ts` method + type, a vitest 3-state test). The weekly digest card reuses `dispatch/cards.Card`/`send_card` and is posted by a handler hung off the existing `apply-weekly` Monday 9am ET cron (mirrors `register_fleet_health`).

**Tech Stack:** Python 3.11 / FastAPI / SQLModel. Frontend: Next.js 15 (React 19) + vitest.

## Global Constraints

- **Python 3.11 / FastAPI / SQLModel.**
- **Backend tests run with:** `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest`
- **Frontend tests run with:** `cd /Users/clawd/borina-mesh/apps/web && npm test` (vitest; jsdom).
- **Hermetic conftest:** `apps/api/conftest.py` already redirects `DATABASE_URL`, `REPORTS_DIR`, and `GOOGLE_OAUTH_TOKEN_FILE` to throwaway temp paths and seeds the schema via `init_db()` (importing `models` first so every table is registered before `create_all`). Reply detection / mailbox reads MUST be stubbed in tests (no real Graph network). For any Microsoft token-file access in a test, use a per-test `monkeypatch.setenv("MICROSOFT_OAUTH_TOKEN_FILE", str(tmp_path / "ms_tok.json"))` — NEVER touch `~/.borina`.
- **Agents run via the claude CLI** through `agents.runner_v2.run_agent_task` — **NO API key** in code. Follow-up drafting reuses the registered `applier` agent's `system_prompt`; never hardcode a key.
- **SAFETY INVARIANT:** the only outbound paths (`outlook.send_mail` / form-submit) MUST require `user_initiated=True` and be reachable only from Bo's approval tap. **Reply detection is READ-ONLY and NEVER auto-replies.** Follow-ups are *staged* (text/data-only) and sent ONLY through Phase 1's `approve_send` (which passes `user_initiated=True`) on Bo's `apply:send:{id}` tap. The mailbox reader (`list_inbox`), the reply matcher (`match_replies`), the follow-up stager (`stage_followups`), the read-only route, and the weekly digest MUST NEVER call a send path. Interview/rejection classification is a *flag for Bo's confirmation*, never an automatic final status.
- **New tables auto-create** via `init_db`'s `SQLModel.metadata.create_all`. Define `OutreachReply` in `models.py`; conftest's `_init_test_db` imports `models` before `create_all`, so the table exists in tests with no manual migration. **Do NOT add columns to Phase 1's `OutreachItem`** (SQLite `create_all` does not ALTER an existing table) — reply/follow-up state lives in the new `OutreachReply` table + the existing `status` field (extended value `"replied"`) + follow-up rows that are themselves `OutreachItem`s linked by `dedup_key`.
- **Consume Phase 1 EXACTLY (do not redefine):** `models.OutreachItem`; `integrations.outlook.send_mail` / `GraphSender` / `_sender` / `SOURCE` / `GRAPH_BASE` / `_access_token` / `_oauth_configured`; `integrations.microsoft_oauth.{SCOPE, get_access_token, configured}`; `dispatch.apply.{run_apply, get_proposed, approve_send, skip_item, _dedup_key, discover, draft_email, DAILY_SEND_CAP, BATCH_CAP}`; `routes.telegram.{apply_card, send_apply_cards, _handle_apply_callback}`; `scheduler.SchedulerService.{register_apply_weekly, _run_apply_weekly}`. Phase 1 already wired `routes/outlook.py` into `main.py`, imported `agents.applier`, and called `register_apply_weekly()`.
- **DRY / YAGNI / TDD:** write the failing test first, run it (expect FAIL), implement the minimum real code, run it (expect PASS), commit. No placeholders.

---

## Task 3.1 — Additive `Mail.Read` scope + read-only mailbox reader (`integrations/outlook.py` + `microsoft_oauth.py`)

Add `Mail.Read` to the existing OAuth scope (additive — re-consent picks it up) and a read-only `list_inbox` to `integrations/outlook.py`. Graph `GET /me/messages` returns the latest inbound mail; the reader is `@safe`, returns an `IntegrationResult`, and NEVER sends. Mirrors Phase 1's `status()`/`GraphSender` (token + auth header) and the `http_get_json` injection seam used by `contacts.find_contact`.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/integrations/microsoft_oauth.py` (extend `SCOPE`)
- Modify: `/Users/clawd/borina-mesh/apps/api/integrations/outlook.py` (add `http_get_json` import + `list_inbox`)
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_outlook_inbox.py`

**Interfaces:**
- Consumes: `integrations.base.{IntegrationResult, http_get_json, not_connected, ok, safe}`, `integrations.outlook.{SOURCE, GRAPH_BASE, _access_token, _oauth_configured}`.
- Produces:
  - `microsoft_oauth.SCOPE` extended to `"offline_access Mail.Send Mail.Read User.Read"`.
  - `outlook.list_inbox(since_iso: Optional[str] = None, top: int = 25) -> IntegrationResult` — read-only; `.data` on success: `list[{"id": str, "from": str, "subject": str, "received": str, "preview": str}]`. `not_connected` when unauthorized. NEVER sends.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_outlook_inbox.py`:

```python
"""Mailbox read (Phase 3) — read-only Graph inbox fetch for reply detection.
Stubbed http_get_json (no real network). list_inbox NEVER sends. The scope now
carries Mail.Read (additive to Phase 0/1's Mail.Send). Mirrors test_contacts'
http_get_json injection + Phase 1's authorized/unauthorized branches."""
import pytest

from integrations import outlook
from integrations import microsoft_oauth as mso


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MICROSOFT_OAUTH_ACCESS_TOKEN", "tok")
    yield


def test_scope_includes_mail_read():
    assert "Mail.Read" in mso.SCOPE
    assert "Mail.Send" in mso.SCOPE  # additive — Phase 0/1 scope preserved


def test_list_inbox_not_connected_when_unauthorized(monkeypatch):
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(outlook, "_access_token", lambda: "")
    res = outlook.list_inbox()
    assert res.connected is False
    assert "not authorized" in (res.error or "").lower()


def test_list_inbox_maps_graph_messages(monkeypatch):
    seen = {}

    def fake_get(url, *, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        seen["auth"] = (headers or {}).get("Authorization")
        return {"value": [
            {"id": "m1", "subject": "Re: internship",
             "from": {"emailAddress": {"address": "Ada@Acme.AI", "name": "Ada Lee"}},
             "receivedDateTime": "2026-06-20T14:00:00Z", "bodyPreview": "Sure, let's chat."},
        ]}

    monkeypatch.setattr(outlook, "http_get_json", fake_get)
    res = outlook.list_inbox(since_iso="2026-06-13T00:00:00Z", top=10)
    assert res.connected is True
    assert seen["url"].endswith("/me/messages")
    assert seen["auth"] == "Bearer tok"
    msg = res.data[0]
    assert msg["from"] == "ada@acme.ai"           # lower-cased for matching
    assert msg["subject"] == "Re: internship"
    assert msg["preview"] == "Sure, let's chat."
    assert msg["received"] == "2026-06-20T14:00:00Z"


def test_list_inbox_handles_missing_from(monkeypatch):
    def fake_get(url, *, params=None, headers=None, timeout=None):
        return {"value": [{"id": "m2", "subject": "No sender", "receivedDateTime": "x"}]}

    monkeypatch.setattr(outlook, "http_get_json", fake_get)
    res = outlook.list_inbox()
    assert res.connected is True
    assert res.data[0]["from"] == ""             # graceful, never crashes
```

- [ ] Run it (expect FAIL — `list_inbox` and the imported `http_get_json` do not exist yet):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outlook_inbox.py -q`
  Expected: failures — `AttributeError: module 'integrations.outlook' has no attribute 'list_inbox'` and `assert "Mail.Read" in mso.SCOPE` fails.

- [ ] Extend the scope. In `/Users/clawd/borina-mesh/apps/api/integrations/microsoft_oauth.py`, change the `SCOPE` constant line:

```python
SCOPE = "offline_access Mail.Send Mail.Read User.Read"
```

- [ ] Add the reader. In `/Users/clawd/borina-mesh/apps/api/integrations/outlook.py`, add `http_get_json` to the existing `from .base import (...)` block (insert `http_get_json,` after `env,`):

```python
from .base import (
    IntegrationResult,
    env,
    http_get_json,
    http_post_json,
    not_connected,
    ok,
    safe,
)
```

  Then append `list_inbox` at the end of the module (after `send_mail`):

```python
@safe(SOURCE)
def list_inbox(since_iso: Optional[str] = None, top: int = 25) -> IntegrationResult:
    """Read-only inbox fetch for reply detection (spec §3). Graph GET
    /me/messages, newest first. NEVER sends — this is the additive Mail.Read
    path. Each message is flattened to {id, from (lower-cased), subject,
    received, preview} so the reply matcher can compare sender to a staged
    contact_email. not_connected when unauthorized (the matcher then no-ops)."""
    if not _oauth_configured() or not _access_token():
        return not_connected(SOURCE, "Outlook not authorized")
    params = {
        "$top": str(top),
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,bodyPreview",
    }
    if since_iso:
        params["$filter"] = f"receivedDateTime ge {since_iso}"
    raw = http_get_json(
        f"{GRAPH_BASE}/me/messages",
        params=params,
        headers={"Authorization": f"Bearer {_access_token()}"},
    )
    out = []
    for m in (raw or {}).get("value", []) or []:
        addr = (((m.get("from") or {}).get("emailAddress") or {}).get("address") or "")
        out.append({
            "id": m.get("id", ""),
            "from": addr.strip().lower(),
            "subject": m.get("subject", "") or "",
            "received": m.get("receivedDateTime", "") or "",
            "preview": m.get("bodyPreview", "") or "",
        })
    return ok(SOURCE, out)
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outlook_inbox.py -q`
  Expected: `4 passed`.

- [ ] Run the Phase 1 outlook + oauth tests to confirm the scope/import change is non-breaking:
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outlook.py tests/test_microsoft_oauth.py tests/test_outlook_routes.py -q`
  Expected: all prior Phase 1 outlook/oauth tests still pass (the scope assertions in `test_microsoft_oauth` only check `Mail.Send`/`offline_access`, both preserved).

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/integrations/outlook.py apps/api/integrations/microsoft_oauth.py apps/api/tests/test_outlook_inbox.py && git commit -m "Phase 3: additive Mail.Read scope + read-only outlook.list_inbox (never sends)"`

---

## Task 3.2 — `OutreachReply` table (records a matched inbound reply)

The new staging table for inbound matches. Auto-creates via `init_db`'s `create_all` — it does NOT alter Phase 1's `OutreachItem`. Records which `OutreachItem` an inbound email matched, the classification *flag* (`neutral` | `interview` | `rejection`), and a `confirmed` boolean that stays False until Bo confirms (never auto-finalized).

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/models.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_outreach_reply_model.py`

**Interfaces:**
- Consumes: `models.OutreachItem` (Phase 1) via the `outreach_item_id` FK.
- Produces `class OutreachReply(SQLModel, table=True)` with fields:
  `id: Optional[int]` (pk); `outreach_item_id: int` (FK `outreachitem.id`, indexed); `from_email: str` (indexed); `subject: str`; `preview: str = ""`; `graph_message_id: str = Field(index=True)` (dedup so the same inbound is matched once); `flag: str = "neutral"` (`neutral` | `interview` | `rejection` — a *suggestion* for Bo); `confirmed: bool = False` (Bo has NOT confirmed the flag; never auto-final); `received_at: Optional[str] = None`; `created_at: datetime` (indexed, default `utcnow`).

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_outreach_reply_model.py`:

```python
"""OutreachReply staging table (Phase 3). Auto-created by init_db's create_all —
no migration, no ALTER of Phase 1's OutreachItem. A reply is recorded with a
classification FLAG that stays unconfirmed (confirmed=False) until Bo glances —
never auto-finalized."""
from datetime import datetime

from sqlmodel import select

from db import session_scope
from models import OutreachItem, OutreachReply


def test_outreach_reply_defaults_and_persist():
    with session_scope() as s:
        item = OutreachItem(track="swe", company="Acme AI",
                            contact_email="ada@acme.ai", subject="S", body="B",
                            dedup_key="ada@acme.ai|acme.ai", status="sent")
        s.add(item)
        s.commit()
        s.refresh(item)
        reply = OutreachReply(
            outreach_item_id=item.id, from_email="ada@acme.ai",
            subject="Re: internship", graph_message_id="m1",
        )
        s.add(reply)
        s.commit()
        s.refresh(reply)
        assert reply.id is not None
        assert reply.flag == "neutral"
        assert reply.confirmed is False         # never auto-final
        assert isinstance(reply.created_at, datetime)


def test_outreach_reply_queryable_by_graph_message_id():
    with session_scope() as s:
        s.add(OutreachReply(outreach_item_id=1, from_email="r@finco.com",
                           subject="x", graph_message_id="g-77", flag="interview"))
        s.commit()
        rows = s.exec(
            select(OutreachReply).where(OutreachReply.graph_message_id == "g-77")
        ).all()
        assert len(rows) == 1 and rows[0].flag == "interview"
```

- [ ] Run it (expect FAIL — model does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outreach_reply_model.py -q`
  Expected: collection error `ImportError: cannot import name 'OutreachReply' from 'models'`.

- [ ] Minimal implementation. Append to `/Users/clawd/borina-mesh/apps/api/models.py` (after `OutreachItem`):

```python
class OutreachReply(SQLModel, table=True):
    """A matched inbound reply to a sent OutreachItem (Phase 3). Read-only
    detection records this; it NEVER auto-replies. `flag` is a *suggestion*
    (interview/rejection language) that stays `confirmed=False` until Bo glances
    — the pipeline never finalizes a status on its own. `graph_message_id` dedups
    so the same inbound is matched at most once. Auto-created by init_db's
    create_all (new table — no ALTER of OutreachItem)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    outreach_item_id: int = Field(foreign_key="outreachitem.id", index=True)
    from_email: str = Field(index=True)
    subject: str
    preview: str = ""
    graph_message_id: str = Field(index=True)
    flag: str = "neutral"                         # neutral | interview | rejection
    confirmed: bool = False                        # Bo has NOT confirmed; never auto-final
    received_at: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outreach_reply_model.py -q`
  Expected: `2 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/models.py apps/api/tests/test_outreach_reply_model.py && git commit -m "Phase 3: OutreachReply staging table (records matched inbound; never auto-final)"`

---

## Task 3.3 — Reply matcher in `dispatch/apply.py` (read-only; advances `replied`, flags interview/rejection)

Match inbound mail (via `outlook.list_inbox`) to a sent `OutreachItem` by recipient email. On a first match: record an `OutreachReply` (deduped by `graph_message_id`), advance the item's `status` to `"replied"`, and classify the body into a `flag` (`interview` | `rejection` | `neutral`) that stays *unconfirmed* — never auto-finalized. READ-ONLY: `match_replies` NEVER calls a send path. Mirrors `run_apply`'s `session_scope` + summary-dict style.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_reply_matcher.py`

**Interfaces:**
- Consumes: `db.session_scope`, `models.{OutreachItem, OutreachReply}`, `integrations.outlook.list_inbox`.
- Produces:
  - `INTERVIEW_PHRASES`, `REJECTION_PHRASES` (tuples of lower-case substrings).
  - `_classify_reply(subject: str, preview: str) -> str` — returns `"interview"` | `"rejection"` | `"neutral"`.
  - `match_replies(since_iso: Optional[str] = None) -> dict` — reads the inbox, matches to sent items, records replies, advances status; returns `{"matched": int, "replied_item_ids": list[int], "flags": dict[int, str], "reasons": list[str]}`. NEVER sends.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_reply_matcher.py`:

```python
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
```

- [ ] Run it (expect FAIL — functions missing):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_reply_matcher.py -q`
  Expected: `AttributeError: module 'dispatch.apply' has no attribute '_classify_reply'`.

- [ ] Minimal implementation. Append to `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py` (after `skip_item`). Add `OutreachReply` to the existing top-of-file model import (`from models import OutreachItem, OutreachReply`):

```python
INTERVIEW_PHRASES = (
    "interview", "schedule a call", "set up a call", "hop on a call",
    "are you free", "chat about", "next steps", "phone screen",
)
REJECTION_PHRASES = (
    "won't be moving forward", "wont be moving forward", "not moving forward",
    "decided not to", "unable to offer", "no longer considering",
    "filled the position", "unfortunately",
)


def _classify_reply(subject: str, preview: str) -> str:
    """Suggest a flag from reply language. interview/rejection are *suggestions*
    for Bo to confirm — the caller never finalizes a status automatically."""
    blob = f"{subject}\n{preview}".lower()
    if any(p in blob for p in INTERVIEW_PHRASES):
        return "interview"
    if any(p in blob for p in REJECTION_PHRASES):
        return "rejection"
    return "neutral"


def match_replies(since_iso: Optional[str] = None) -> dict:
    """READ-ONLY reply detection (spec §3). Read the inbox, match inbound mail to
    a sent OutreachItem by recipient email, record an OutreachReply (deduped by
    graph_message_id), and advance the item to 'replied'. The interview/rejection
    flag stays UNCONFIRMED — never auto-final. NEVER sends anything."""
    from integrations import outlook

    inbox = outlook.list_inbox(since_iso=since_iso)
    if not inbox.connected:
        return {"matched": 0, "replied_item_ids": [], "flags": {}, "reasons": [inbox.error or "inbox unavailable"]}

    matched = 0
    replied_item_ids: list[int] = []
    flags: dict[int, str] = {}
    reasons: list[str] = []

    with session_scope() as s:
        # sent (or already-replied) items, keyed by lower-cased recipient
        sent = s.exec(
            select(OutreachItem).where(OutreachItem.status.in_(("sent", "replied")))
        ).all()
        by_email = {(it.contact_email or "").strip().lower(): it for it in sent}
        seen_ids = {r.graph_message_id for r in s.exec(select(OutreachReply)).all()}

        for msg in inbox.data or []:
            gid = msg.get("id", "")
            sender = (msg.get("from") or "").strip().lower()
            item = by_email.get(sender)
            if not item or not gid or gid in seen_ids:
                continue
            flag = _classify_reply(msg.get("subject", ""), msg.get("preview", ""))
            s.add(OutreachReply(
                outreach_item_id=item.id, from_email=sender,
                subject=msg.get("subject", ""), preview=msg.get("preview", ""),
                graph_message_id=gid, flag=flag, received_at=msg.get("received"),
            ))
            if item.status != "replied":
                item.status = "replied"
                s.add(item)
            seen_ids.add(gid)
            matched += 1
            replied_item_ids.append(item.id)
            flags[item.id] = flag
        s.commit()

    return {"matched": matched, "replied_item_ids": replied_item_ids,
            "flags": flags, "reasons": reasons}
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_reply_matcher.py -q`
  Expected: `6 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/dispatch/apply.py apps/api/tests/test_reply_matcher.py && git commit -m "Phase 3: read-only reply matcher (advances replied, flags interview/rejection unconfirmed)"`

---

## Task 3.4 — Follow-up drafting + staging in `dispatch/apply.py` (no reply after 7 days → one-per-contact staged card)

Stage a follow-up `OutreachItem(status="proposed")` for each sent item with no reply after `FOLLOWUP_DAYS` (default 7). Caps: at most ONE follow-up per contact (skip if a follow-up already exists for that `dedup_key`); respect `DAILY_SEND_CAP`; honor the blocklist (`04-resources/applications/blocklist.md`). The follow-up draft reuses the `applier` agent via `draft_email`. Staging NEVER sends — the follow-up is sent through Phase 1's `approve_send` on Bo's `apply:send:{id}` tap.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_followups.py`

**Interfaces:**
- Consumes: `db.session_scope`, `models.OutreachItem`, `dispatch.apply.{draft_email, _dedup_key, DAILY_SEND_CAP}`, `integrations.outlook.send_mail` (only via the spy guard — never called).
- Produces:
  - `FOLLOWUP_DAYS = 7`
  - `FOLLOWUP_PREFIX = "[followup] "` (marks a follow-up row's `dedup_key` so it's distinct from the original + countable as one-per-contact).
  - `_load_blocklist() -> set[str]` — lower-cased emails from `04-resources/applications/blocklist.md` (empty when missing).
  - `async stage_followups(now: Optional[datetime] = None) -> dict` — stages follow-up `OutreachItem`s; returns `{"staged": int, "dropped": int, "item_ids": list[int], "reasons": list[str]}`. NEVER sends.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_followups.py`:

```python
"""Follow-up staging (Phase 3). No reply after 7 days → ONE staged follow-up per
contact, respecting the daily cap + blocklist. Staging NEVER sends — the
follow-up rides Phase 1's approve_send gate. draft_email is stubbed (no agent
CLI). Mirrors test_apply_pipeline's clean + no-send invariant."""
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from db import session_scope
from models import OutreachItem
from dispatch import apply as ap
from integrations import outlook
from integrations.base import ok


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    with session_scope() as s:
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    # No real agent CLI for the follow-up draft.
    async def fake_draft(candidate, contact):
        return {"subject": f"Following up — {candidate['company']}",
                "body": "Just bumping this — still keen on internships."}
    monkeypatch.setattr(ap, "draft_email", fake_draft)
    # Blocklist empty unless a test overrides it.
    monkeypatch.setattr(ap, "_load_blocklist", lambda: set())
    yield


def _seed(email, *, status="sent", days_ago=10, dedup=None):
    with session_scope() as s:
        it = OutreachItem(track="swe", company="Acme AI", contact_email=email,
                          subject="Internship", body="hi", company_domain="acme.ai",
                          dedup_key=dedup or ap._dedup_key(email, "acme.ai"), status=status)
        it.created_at = datetime.utcnow() - timedelta(days=days_ago)
        it.sent_at = datetime.utcnow() - timedelta(days=days_ago)
        s.add(it)
        s.commit()
        s.refresh(it)
        return it.id


def _spy_no_send(monkeypatch):
    calls = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: calls.append(1) or ok("outlook", {"id": "x", "via": "graph"}))
    return calls


@pytest.mark.asyncio
async def test_stages_followup_after_window_and_never_sends(monkeypatch):
    _seed("ada@acme.ai", days_ago=10)
    calls = _spy_no_send(monkeypatch)
    summary = await ap.stage_followups()
    assert summary["staged"] == 1
    assert calls == []                              # staging never sends
    with session_scope() as s:
        rows = s.exec(select(OutreachItem).where(OutreachItem.status == "proposed")).all()
        assert len(rows) == 1
        assert rows[0].dedup_key.startswith(ap.FOLLOWUP_PREFIX)


@pytest.mark.asyncio
async def test_recent_send_is_not_followed_up(monkeypatch):
    _seed("ada@acme.ai", days_ago=2)                # inside the 7-day window
    summary = await ap.stage_followups()
    assert summary["staged"] == 0
    assert any("too recent" in r.lower() for r in summary["reasons"])


@pytest.mark.asyncio
async def test_replied_item_is_not_followed_up(monkeypatch):
    _seed("ada@acme.ai", status="replied", days_ago=10)
    summary = await ap.stage_followups()
    assert summary["staged"] == 0


@pytest.mark.asyncio
async def test_one_followup_per_contact(monkeypatch):
    _seed("ada@acme.ai", days_ago=10)
    await ap.stage_followups()
    summary2 = await ap.stage_followups()           # follow-up already exists
    assert summary2["staged"] == 0
    assert any("already followed up" in r.lower() for r in summary2["reasons"])


@pytest.mark.asyncio
async def test_blocklist_is_honored(monkeypatch):
    _seed("ada@acme.ai", days_ago=10)
    monkeypatch.setattr(ap, "_load_blocklist", lambda: {"ada@acme.ai"})
    summary = await ap.stage_followups()
    assert summary["staged"] == 0
    assert any("blocklist" in r.lower() for r in summary["reasons"])


@pytest.mark.asyncio
async def test_daily_cap_limits_followups(monkeypatch):
    for i in range(ap.DAILY_SEND_CAP + 3):
        _seed(f"c{i}@acme.ai", days_ago=10, dedup=f"c{i}@acme.ai|acme.ai")
    summary = await ap.stage_followups()
    assert summary["staged"] == ap.DAILY_SEND_CAP
    assert summary["dropped"] >= 3
    assert any("daily cap" in r.lower() for r in summary["reasons"])
```

- [ ] Run it (expect FAIL — functions missing):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_followups.py -q`
  Expected: `AttributeError: module 'dispatch.apply' has no attribute 'stage_followups'`.

- [ ] Minimal implementation. Append to `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py` (after `match_replies`). Add the `os` + `timedelta` imports to the top of the file (`from datetime import datetime, timedelta` and `import os`):

```python
FOLLOWUP_DAYS = 7
FOLLOWUP_PREFIX = "[followup] "


def _load_blocklist() -> set[str]:
    """Lower-cased emails Bo never wants contacted/followed-up, from
    04-resources/applications/blocklist.md (one email per line; '#' comments
    ignored). Empty when the file is missing — fail-open on read, fail-closed on
    membership (a listed email is always dropped)."""
    root = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not root:
        return set()
    path = os.path.join(root, "04-resources", "applications", "blocklist.md")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return set()
    out = set()
    for ln in lines:
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.add(ln.lower())
    return out


async def stage_followups(now: Optional[datetime] = None) -> dict:
    """Stage a follow-up OutreachItem for each sent item with no reply after
    FOLLOWUP_DAYS. ONE follow-up per contact (a FOLLOWUP_PREFIX row already
    existing for the dedup_key blocks a second); respect DAILY_SEND_CAP; honor
    the blocklist. Staging NEVER sends — the follow-up is sent only via Phase 1's
    approve_send on Bo's tap. Drops are counted + reasoned (no silent caps)."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=FOLLOWUP_DAYS)
    blocklist = _load_blocklist()

    with session_scope() as s:
        sent = s.exec(
            select(OutreachItem).where(OutreachItem.status == "sent")
            .order_by(OutreachItem.created_at)
        ).all()
        existing_keys = {r.dedup_key for r in s.exec(select(OutreachItem)).all()}
        candidates = [
            {"id": it.id, "company": it.company, "track": it.track,
             "domain": it.company_domain, "contact_email": it.contact_email,
             "contact_name": it.contact_name, "dedup_key": it.dedup_key,
             "sent_at": it.sent_at or it.created_at}
            for it in sent
        ]

    item_ids: list[int] = []
    dropped = 0
    reasons: list[str] = []

    for cand in candidates:
        email = (cand["contact_email"] or "").strip().lower()
        fkey = FOLLOWUP_PREFIX + cand["dedup_key"]
        if (cand["sent_at"] or now) > cutoff:
            dropped += 1
            reasons.append(f"{cand['company']}: too recent (< {FOLLOWUP_DAYS}d)")
            continue
        if fkey in existing_keys:
            dropped += 1
            reasons.append(f"{cand['company']}: already followed up")
            continue
        if email in blocklist:
            dropped += 1
            reasons.append(f"{cand['company']}: blocklist")
            continue
        if len(item_ids) >= DAILY_SEND_CAP:
            dropped += 1
            reasons.append(f"{cand['company']}: over daily cap ({DAILY_SEND_CAP})")
            continue
        draft = await draft_email(
            {"company": cand["company"], "domain": cand["domain"],
             "why_fit": "a brief follow-up on my earlier note", "track": cand["track"]},
            {"name": cand["contact_name"], "email": cand["contact_email"]},
        )
        with session_scope() as s:
            row = OutreachItem(
                track=cand["track"], company=cand["company"],
                company_domain=cand["domain"], contact_name=cand["contact_name"],
                contact_email=cand["contact_email"], subject=draft["subject"],
                body=draft["body"], dedup_key=fkey,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            item_ids.append(row.id)
        existing_keys.add(fkey)

    return {"staged": len(item_ids), "dropped": dropped,
            "item_ids": item_ids, "reasons": reasons}
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_followups.py -q`
  Expected: `6 passed`.

- [ ] Run the full apply suite to confirm Phase 1 + reply matcher + follow-ups coexist:
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_pipeline.py tests/test_reply_matcher.py tests/test_followups.py -q`
  Expected: all pass (Phase 1's `run_apply`/`approve_send`/`skip_item` unchanged; the new functions are additive).

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/dispatch/apply.py apps/api/tests/test_followups.py && git commit -m "Phase 3: follow-up staging (7-day window, one-per-contact, daily cap + blocklist; never sends)"`

---

## Task 3.5 — Read-only `routes/outreach.py` + main wiring

A read-only API for the `/outreach` tab. Mirror `routes/daily.py`'s summary handler: pipeline counts by stage + per-company rows + this week's sends/replies. NO write routes (sends stay on the Telegram `apply:send` tap). Mounted at `/outreach`.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/routes/outreach.py`
- Modify: `/Users/clawd/borina-mesh/apps/api/main.py` (import + include router)
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_outreach_routes.py`

**Interfaces:**
- Consumes: `db.get_session`, `models.{OutreachItem, OutreachReply}`.
- Produces:
  - `router = APIRouter(prefix="/outreach", tags=["outreach"])`
  - `GET /outreach/summary` → `{"counts": dict[str,int], "rows": list[dict], "replies": list[dict], "week": {"sent": int, "replied": int, "awaiting_followup": int}}`. Read-only — no send path, no write.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_outreach_routes.py`:

```python
"""Outreach read-only API (Phase 3). The /outreach tab's data source: pipeline
counts by stage, per-company rows, the week's sends/replies. NO write/send route
exists here — sends stay on the Telegram approval tap. Mirrors test_daily_routes'
TestClient shape checks."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from main import app
from db import session_scope
from models import OutreachItem, OutreachReply

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for r in s.exec(select(OutreachReply)).all():
            s.delete(r)
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    yield


def _seed(company, status, *, email="x@acme.ai", days_ago=1):
    with session_scope() as s:
        it = OutreachItem(track="swe", company=company, contact_email=email,
                          subject="S", body="B", dedup_key=f"{email}|{company}",
                          status=status, company_domain="acme.ai")
        it.created_at = datetime.utcnow() - timedelta(days=days_ago)
        if status in ("sent", "replied"):
            it.sent_at = datetime.utcnow() - timedelta(days=days_ago)
        s.add(it)
        s.commit()
        s.refresh(it)
        return it.id


def test_summary_shape_when_empty():
    r = client.get("/outreach/summary")
    assert r.status_code == 200
    data = r.json()
    assert set(["counts", "rows", "replies", "week"]).issubset(data)
    assert data["rows"] == []
    assert data["week"]["sent"] == 0


def test_summary_counts_by_stage():
    _seed("Acme AI", "proposed")
    _seed("FinCo", "sent", email="r@finco.com")
    _seed("DeepLab", "replied", email="d@deeplab.ai")
    r = client.get("/outreach/summary")
    data = r.json()
    assert data["counts"]["proposed"] == 1
    assert data["counts"]["sent"] == 1
    assert data["counts"]["replied"] == 1
    companies = {row["company"] for row in data["rows"]}
    assert {"Acme AI", "FinCo", "DeepLab"} <= companies


def test_summary_surfaces_reply_flag():
    item_id = _seed("Acme AI", "replied", email="ada@acme.ai")
    with session_scope() as s:
        s.add(OutreachReply(outreach_item_id=item_id, from_email="ada@acme.ai",
                           subject="Re", graph_message_id="m1", flag="interview"))
        s.commit()
    r = client.get("/outreach/summary")
    data = r.json()
    assert any(rep["flag"] == "interview" for rep in data["replies"])


def test_no_write_or_send_route_exists():
    # The tab is read-only; only GET /outreach/summary is mounted.
    assert client.post("/outreach/summary").status_code in (404, 405)
    assert client.post("/outreach/send").status_code == 404
```

- [ ] Run it (expect FAIL — route not mounted):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outreach_routes.py -q`
  Expected: failures — `404` on `/outreach/summary` (and import error on `routes.outreach`).

- [ ] Minimal implementation. Create `/Users/clawd/borina-mesh/apps/api/routes/outreach.py`:

```python
"""Outreach read-only API (spec §3).

Mounted at `/outreach` (frontend: `/api/outreach/...`). The /outreach tab's data
source: pipeline counts by stage, per-company rows with status + next action, and
the week's sends/replies. STRICTLY read-only — there is NO send/write route here.
Every outbound action stays behind Bo's Telegram approval tap (apply:send). The
reply `flag` (interview/rejection) is surfaced as an unconfirmed suggestion for
Bo to glance at, never a final status. Mirrors routes/daily.py.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import OutreachItem, OutreachReply

router = APIRouter(prefix="/outreach", tags=["outreach"])

STAGES = ["proposed", "sent", "replied", "skipped", "failed"]


@router.get("/summary")
def outreach_summary(session: Session = Depends(get_session)):
    items = session.exec(select(OutreachItem).order_by(OutreachItem.created_at.desc())).all()
    replies = session.exec(select(OutreachReply).order_by(OutreachReply.created_at.desc())).all()

    counts = {stage: 0 for stage in STAGES}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1

    week_start = datetime.utcnow() - timedelta(days=7)
    sent_week = sum(1 for it in items if it.sent_at and it.sent_at >= week_start)
    replied_week = sum(1 for r in replies if r.created_at >= week_start)
    cutoff = datetime.utcnow() - timedelta(days=7)
    awaiting = sum(
        1 for it in items
        if it.status == "sent" and (it.sent_at or it.created_at) <= cutoff
        and not it.dedup_key.startswith("[followup] ")
    )

    rows = [
        {"id": it.id, "company": it.company, "track": it.track,
         "contact_email": it.contact_email, "status": it.status,
         "subject": it.subject,
         "is_followup": it.dedup_key.startswith("[followup] "),
         "created_at": it.created_at.isoformat() if it.created_at else None,
         "sent_at": it.sent_at.isoformat() if it.sent_at else None}
        for it in items
    ]
    reply_rows = [
        {"outreach_item_id": r.outreach_item_id, "from_email": r.from_email,
         "subject": r.subject, "flag": r.flag, "confirmed": r.confirmed,
         "received_at": r.received_at}
        for r in replies
    ]
    return {
        "counts": counts,
        "rows": rows,
        "replies": reply_rows,
        "week": {"sent": sent_week, "replied": replied_week, "awaiting_followup": awaiting},
    }
```

- [ ] Wire the router in `main.py`. Append `, outreach as outreach_routes` to the `from routes import ...` line (it already ends `... outlook as outlook_routes` after Phase 1):

```python
from routes import agents as agents_routes, chat as chat_routes, jobs as jobs_routes, activity as activity_routes, schedules as schedules_routes, analytics as analytics_routes, artifacts as artifacts_routes, logs as logs_routes, wiki as wiki_routes, briefs as briefs_routes, memory as memory_routes, workspace as workspace_routes, threads as threads_routes, tasks as tasks_routes, stats as stats_routes, finance as finance_routes, finance_lifeos as finance_lifeos_routes, daily as daily_routes, calendar as calendar_routes, telegram as telegram_routes, files as files_routes, outlook as outlook_routes, outreach as outreach_routes
```

  Then add the include after `app.include_router(outlook_routes.router)` (added in Phase 1):

```python
app.include_router(outlook_routes.router)
app.include_router(outreach_routes.router)
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outreach_routes.py -q`
  Expected: `4 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/routes/outreach.py apps/api/main.py apps/api/tests/test_outreach_routes.py && git commit -m "Phase 3: read-only /outreach summary route (counts, rows, week, reply flags)"`

---

## Task 3.6 — Weekly digest card + reply-detection sweep on the Monday cron (`scheduler.py`)

Extend Phase 1's `apply-weekly` Monday handler: before staging the new batch, run a reply-detection sweep (`match_replies`) and a follow-up staging pass (`stage_followups`), then post a weekly **digest card** ("N sent, M replies, K awaiting follow-up") to `TELEGRAM_CHAT_ID`. The digest reuses Phase 1's `send_apply_cards` for the follow-up approval cards. NEVER sends — every action is read-only or staged-for-approval. Mirrors `register_fleet_health`'s chat-id + Card pattern.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/scheduler.py` (extend `_run_apply_weekly`; add `_digest_card`)
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_apply_digest.py`

**Interfaces:**
- Consumes: `dispatch.apply.{run_apply, match_replies, stage_followups}`, `routes.telegram.send_apply_cards`, `dispatch.cards.{Card, send_card}`, `models.{OutreachItem, OutreachReply}`, `db.session_scope`.
- Produces:
  - `SchedulerService._digest_card(self) -> Card` — the weekly digest summary card (read-only counts).
  - extended `SchedulerService._run_apply_weekly(self) -> None` — sweeps replies + stages follow-ups + posts the digest card, then the existing weekly cold-email batch. NEVER sends.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_apply_digest.py`:

```python
"""Weekly digest + reply/follow-up sweep on the Monday cron (Phase 3). The cron
detects replies (read-only), stages follow-ups (no send), and posts a digest
card. NEVER sends. Mirrors test_apply_scheduler + register_fleet_health."""
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from db import session_scope
from models import OutreachItem, OutreachReply
from scheduler import SchedulerService
from dispatch.cards import Card


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for r in s.exec(select(OutreachReply)).all():
            s.delete(r)
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    yield


def _seed(company, status, *, days_ago=1):
    with session_scope() as s:
        it = OutreachItem(track="swe", company=company, contact_email=f"x@{company}.ai",
                          subject="S", body="B", dedup_key=f"x@{company}.ai|{company}",
                          status=status, company_domain=f"{company}.ai")
        it.sent_at = datetime.utcnow() - timedelta(days=days_ago)
        s.add(it)
        s.commit()


def test_digest_card_summarizes_counts():
    _seed("acme", "sent")
    _seed("finco", "replied")
    svc = SchedulerService()
    card = svc._digest_card()
    assert isinstance(card, Card)
    blob = card.headline + " ".join(card.lines)
    assert "1 sent" in blob or "sent" in blob.lower()
    assert "replied" in blob.lower() or "repl" in blob.lower()


@pytest.mark.asyncio
async def test_run_apply_weekly_sweeps_and_never_sends(monkeypatch):
    from dispatch import apply as ap
    from integrations import outlook
    from integrations.base import ok

    sent = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: sent.append(1) or ok("outlook", {"id": "x", "via": "graph"}))

    swept = {"replies": 0, "followups": 0, "batch": 0}

    def fake_match(since_iso=None):
        swept["replies"] += 1
        return {"matched": 0, "replied_item_ids": [], "flags": {}, "reasons": []}

    async def fake_followups(now=None):
        swept["followups"] += 1
        return {"staged": 0, "dropped": 0, "item_ids": [], "reasons": []}

    async def fake_run(criteria="", chat_id=None):
        swept["batch"] += 1
        return {"staged": 0, "dropped": 0, "item_ids": [], "reasons": []}

    monkeypatch.setattr(ap, "match_replies", fake_match)
    monkeypatch.setattr(ap, "stage_followups", fake_followups)
    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr("routes.telegram.send_apply_cards", lambda chat_id: 0)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    svc = SchedulerService()
    await svc._run_apply_weekly()
    assert swept == {"replies": 1, "followups": 1, "batch": 1}
    assert sent == []                               # the cron never sends
```

- [ ] Run it (expect FAIL — `_digest_card` missing; sweep not wired):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_digest.py -q`
  Expected: `AttributeError: 'SchedulerService' object has no attribute '_digest_card'` (and the sweep assertions fail).

- [ ] Minimal implementation. In `/Users/clawd/borina-mesh/apps/api/scheduler.py`, add `_digest_card` immediately before `_run_apply_weekly` (added in Phase 1):

```python
    def _digest_card(self):
        """Weekly outreach digest (read-only): N sent, M replies, K awaiting
        follow-up. Reuses the foundation Card channel. Computes counts straight
        from the staging tables — never sends."""
        from datetime import datetime, timedelta
        from sqlmodel import select
        from db import session_scope
        from models import OutreachItem, OutreachReply
        from dispatch.cards import Card

        week_start = datetime.utcnow() - timedelta(days=7)
        cutoff = datetime.utcnow() - timedelta(days=7)
        with session_scope() as s:
            items = s.exec(select(OutreachItem)).all()
            replies = s.exec(select(OutreachReply)).all()
            sent = sum(1 for it in items if it.sent_at and it.sent_at >= week_start)
            replied = sum(1 for r in replies if r.created_at >= week_start)
            awaiting = sum(
                1 for it in items
                if it.status == "sent" and (it.sent_at or it.created_at) <= cutoff
                and not it.dedup_key.startswith("[followup] ")
            )
            flags = [r.flag for r in replies if r.flag != "neutral" and not r.confirmed]
        lines = [
            f"{sent} sent this week",
            f"{replied} replied",
            f"{awaiting} awaiting follow-up",
        ]
        if flags:
            lines.append("Flagged for your glance: " + ", ".join(sorted(set(flags))))
        return Card(headline="Weekly outreach digest", lines=lines)
```

  Then replace the body of `_run_apply_weekly` so it sweeps replies + follow-ups and posts the digest before the cold-email batch. The new body:

```python
    async def _run_apply_weekly(self) -> None:
        """Weekly internship outreach (Phase 1 batch + Phase 3 sweep). Order:
        (1) read-only reply detection, (2) stage follow-ups (no send), (3) post
        the digest card, (4) stage the new cold-email batch + cards. NEVER sends —
        every send stays behind Bo's approval tap."""
        try:
            import os
            from dispatch import apply as apply_mod
            # Phase 3: read-only reply detection + follow-up staging (no send).
            reply_summary = apply_mod.match_replies()
            followup_summary = await apply_mod.stage_followups()
            # Phase 1: new cold-email batch (staged, never sent).
            batch_summary = await apply_mod.run_apply("")
            chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if chat:
                from routes.telegram import send_apply_cards
                from dispatch.cards import send_card
                from dispatch import dispatcher
                from dispatch.telegram_format import format_telegram
                send_card(int(chat), self._digest_card())
                n = send_apply_cards(int(chat))
                dispatcher.send_telegram_message(
                    int(chat),
                    format_telegram(
                        f"Weekly applier: {reply_summary.get('matched', 0)} new repl(ies), "
                        f"staged {followup_summary.get('staged', 0)} follow-up(s) + "
                        f"{batch_summary.get('staged', 0)} new draft(s). Approve each with Send."
                    ),
                )
                print(f"[scheduler] apply-weekly: {n} card(s), "
                      f"{reply_summary.get('matched', 0)} repl(ies)")
            else:
                print(f"[scheduler] apply-weekly: staged {batch_summary.get('staged', 0)}, "
                      f"{reply_summary.get('matched', 0)} repl(ies) (no chat configured)")
        except Exception as e:
            print(f"[scheduler] apply-weekly error: {e}")
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_digest.py -q`
  Expected: `2 passed`.

- [ ] Run the Phase 1 scheduler test to confirm the cron rewrite is non-breaking:
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_scheduler.py -q`
  Expected: `2 passed` — `register_apply_weekly` is unchanged (still `0 9 * * mon America/New_York`, idempotent); `_run_apply_weekly` still never sends and no-ops without a chat (the Phase 1 test stubs `run_apply`/`get_proposed`; the new `match_replies`/`stage_followups` calls hit the real read-only functions, which no-op on the empty isolated DB / unauthorized inbox).

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/scheduler.py apps/api/tests/test_apply_digest.py && git commit -m "Phase 3: weekly digest card + reply/follow-up sweep on the Monday cron (never sends)"`

---

## Task 3.7 — `/outreach` Next.js tab (mirror `/daily`) + api client + nav link + vitest

A read-only `/outreach` tab mirroring `/daily`: a stage-count strip, a per-company pipeline list, and the week's reply rows. Read-only over `/api/outreach/summary`; all actions still happen via Telegram. Add the `api.getOutreachSummary` method + `OutreachSummary` type, the nav link, and a 3-state vitest test (loading / data / error) mirroring `new-tabs.test.tsx`.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/web/app/outreach/page.tsx`
- Modify: `/Users/clawd/borina-mesh/apps/web/lib/api.ts` (add method + `OutreachSummary` type)
- Modify: `/Users/clawd/borina-mesh/apps/web/components/nav-config.ts` (add the `/outreach` link)
- Create: `/Users/clawd/borina-mesh/apps/web/test/outreach-tab.test.tsx`

**Interfaces:**
- Consumes: `@/lib/api` (`api.getOutreachSummary`), `@/lib/use-async`, `@/components/navbar`, `@/components/ui/{section-header,empty-state,error-state,loading-skeleton}`.
- Produces:
  - `api.getOutreachSummary() -> Promise<OutreachSummary>` (GET `/outreach/summary`).
  - `export interface OutreachSummary` (counts, rows, replies, week).
  - `NAV_LINKS` entry `{ href: "/outreach", label: "Outreach", icon: Mail }`.
  - default-export `OutreachPage` React component with loading/empty/error/data states.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/web/test/outreach-tab.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: { getOutreachSummary: vi.fn() },
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/outreach" }));

import { api } from "@/lib/api";
import OutreachPage from "@/app/outreach/page";

const pending = () => new Promise(() => {}); // never resolves → loading state
const hasSkeleton = (c: HTMLElement) => c.querySelector(".animate-pulse") !== null;

beforeEach(() => vi.clearAllMocks());

describe("/outreach tab — 3 states", () => {
  it("loading shows skeletons", () => {
    vi.mocked(api.getOutreachSummary).mockReturnValue(pending() as never);
    const { container } = render(<OutreachPage />);
    expect(hasSkeleton(container)).toBe(true);
  });

  it("data renders pipeline rows + counts, no raw undefined", async () => {
    vi.mocked(api.getOutreachSummary).mockResolvedValue({
      counts: { proposed: 1, sent: 2, replied: 1, skipped: 0, failed: 0 },
      rows: [
        { id: 1, company: "Acme AI", track: "swe", contact_email: "ada@acme.ai",
          status: "replied", subject: "Internship", is_followup: false,
          created_at: "2026-06-20", sent_at: "2026-06-20" },
      ],
      replies: [
        { outreach_item_id: 1, from_email: "ada@acme.ai", subject: "Re",
          flag: "interview", confirmed: false, received_at: "2026-06-21" },
      ],
      week: { sent: 2, replied: 1, awaiting_followup: 1 },
    } as never);
    const { container } = render(<OutreachPage />);
    expect(await screen.findByText("Acme AI")).toBeInTheDocument();
    expect(screen.getByText(/interview/i)).toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("empty shows no-outreach state", async () => {
    vi.mocked(api.getOutreachSummary).mockResolvedValue({
      counts: { proposed: 0, sent: 0, replied: 0, skipped: 0, failed: 0 },
      rows: [], replies: [],
      week: { sent: 0, replied: 0, awaiting_followup: 0 },
    } as never);
    render(<OutreachPage />);
    expect(await screen.findByText(/No outreach yet/i)).toBeInTheDocument();
  });

  it("error shows retry", async () => {
    vi.mocked(api.getOutreachSummary).mockRejectedValue(new Error("boom"));
    render(<OutreachPage />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
```

- [ ] Run it (expect FAIL — page + api method missing):
  `cd /Users/clawd/borina-mesh/apps/web && npm test -- outreach-tab`
  Expected: failure — `Failed to resolve import "@/app/outreach/page"` (module does not exist).

- [ ] Add the api method + type. In `/Users/clawd/borina-mesh/apps/web/lib/api.ts`, add the method inside the `api` object after the Daily block (`getDailyBrief`/`generateDailyBrief`), e.g. right after the `// ── Calendar ──` block's last entry — insert a new block before the closing `};` of `api` (after `createCalendarEvent`):

```ts
  // ── Outreach tab (read-only) ─────────────────────────────────────────────
  getOutreachSummary: () => fetchJSON<OutreachSummary>("/outreach/summary"),
```

  Then add the type near the other response interfaces (after `DailyPlan` / before `CalendarEvent`):

```ts
export interface OutreachRow {
  id: number;
  company: string;
  track: string;
  contact_email: string;
  status: string;
  subject: string;
  is_followup: boolean;
  created_at: string | null;
  sent_at: string | null;
}
export interface OutreachReplyRow {
  outreach_item_id: number;
  from_email: string;
  subject: string;
  flag: string;
  confirmed: boolean;
  received_at: string | null;
}
export interface OutreachSummary {
  counts: Record<string, number>;
  rows: OutreachRow[];
  replies: OutreachReplyRow[];
  week: { sent: number; replied: number; awaiting_followup: number };
}
```

- [ ] Add the nav link. In `/Users/clawd/borina-mesh/apps/web/components/nav-config.ts`, add `Mail` to the lucide import block and a `NAV_LINKS` entry after the `/jobs` entry:

```ts
import {
  LayoutGrid,
  Network,
  BarChart3,
  FileText,
  ListTodo,
  TrendingUp,
  LineChart,
  Sun,
  CalendarDays,
  Mail,
  type LucideIcon,
} from "lucide-react";
```

  and in the `NAV_LINKS` array, after `{ href: "/jobs", label: "Jobs", icon: ListTodo },`:

```ts
  { href: "/jobs", label: "Jobs", icon: ListTodo },
  { href: "/outreach", label: "Outreach", icon: Mail },
```

- [ ] Create the page. Create `/Users/clawd/borina-mesh/apps/web/app/outreach/page.tsx`:

```tsx
"use client";

import { Mail, Send, Inbox, Clock } from "lucide-react";
import { api, type OutreachSummary } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { Navbar } from "@/components/navbar";
import { SectionHeader } from "@/components/ui/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonKpiStrip, SkeletonCard } from "@/components/ui/loading-skeleton";

const STATUS_COLORS: Record<string, string> = {
  proposed: "bg-surface-2 text-muted-foreground",
  sent: "bg-blue-500/15 text-blue-300",
  replied: "bg-positive/15 text-positive",
  skipped: "bg-surface-2 text-muted-foreground",
  failed: "bg-negative/15 text-negative",
};

const FLAG_COLORS: Record<string, string> = {
  interview: "bg-positive/15 text-positive",
  rejection: "bg-negative/15 text-negative",
  neutral: "bg-surface-2 text-muted-foreground",
};

export default function OutreachPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />
      <OutreachBody />
    </main>
  );
}

function OutreachBody() {
  const { data, loading, error, reload } = useAsync<OutreachSummary>(() => api.getOutreachSummary(), []);

  if (loading) {
    return (
      <div className="space-y-6">
        <SkeletonKpiStrip count={3} />
        <SkeletonCard />
      </div>
    );
  }
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="No outreach data" />;

  const { counts, rows, replies, week } = data;
  const hasAny = rows.length > 0;

  return (
    <div className="space-y-6">
      {/* Week KPI strip */}
      <div className="grid grid-cols-3 gap-3">
        <div className="surface-card rounded-2xl p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Send className="h-4 w-4" /> Sent (7d)
          </div>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{week.sent}</p>
        </div>
        <div className="surface-card rounded-2xl p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Inbox className="h-4 w-4" /> Replies (7d)
          </div>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{week.replied}</p>
        </div>
        <div className="surface-card rounded-2xl p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-4 w-4" /> Awaiting follow-up
          </div>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{week.awaiting_followup}</p>
        </div>
      </div>

      {/* Stage counts */}
      <div className="flex flex-wrap gap-2">
        {Object.entries(counts).map(([stage, n]) => (
          <span key={stage} className={`rounded-md px-2.5 py-1 text-xs ${STATUS_COLORS[stage] ?? STATUS_COLORS.proposed}`}>
            {stage}: <span className="tabular-nums">{n}</span>
          </span>
        ))}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Pipeline rows */}
        <section>
          <SectionHeader title="Pipeline" icon={<Mail className="h-4 w-4" />} description="Per-company outreach" />
          {!hasAny ? (
            <EmptyState title="No outreach yet" description="Stage a batch from Telegram with apply:" />
          ) : (
            <div className="space-y-2">
              {rows.map((r) => (
                <div key={r.id} className="flex items-center gap-3 rounded-xl border border-border/40 bg-surface px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-foreground">
                      {r.company}
                      {r.is_followup ? <span className="ml-1 text-xs text-muted-foreground">(follow-up)</span> : null}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{r.contact_email}</p>
                  </div>
                  <span className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-muted-foreground">{r.track}</span>
                  <span className={`rounded-md px-2 py-0.5 text-xs ${STATUS_COLORS[r.status] ?? STATUS_COLORS.proposed}`}>
                    {r.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Replies */}
        <section>
          <SectionHeader title="Replies" icon={<Inbox className="h-4 w-4" />} description="Flagged for your glance — confirm in Telegram" />
          {replies.length === 0 ? (
            <EmptyState title="No replies yet" description="Detected automatically from your mailbox." />
          ) : (
            <div className="space-y-2">
              {replies.map((rep, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl border border-border/40 bg-surface px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-foreground">{rep.from_email}</p>
                    <p className="truncate text-xs text-muted-foreground">{rep.subject}</p>
                  </div>
                  <span className={`rounded-md px-2 py-0.5 text-xs ${FLAG_COLORS[rep.flag] ?? FLAG_COLORS.neutral}`}>
                    {rep.flag}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/web && npm test -- outreach-tab`
  Expected: 4 tests pass in `test/outreach-tab.test.tsx`.

- [ ] Run the existing-tabs + new-tabs frontend tests to confirm the nav-config + api additions are non-breaking:
  `cd /Users/clawd/borina-mesh/apps/web && npm test -- existing-tabs new-tabs bottom-nav`
  Expected: all pass — the new `NAV_LINKS` entry doesn't change `primary` membership (bottom-nav mobile bar unchanged), and the new api method is additive.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/web/app/outreach/page.tsx apps/web/lib/api.ts apps/web/components/nav-config.ts apps/web/test/outreach-tab.test.tsx && git commit -m "Phase 3: /outreach read-only tab (pipeline + replies) + nav link + api client"`

---

## Final self-review checklist

- [ ] **Reply detection is READ-ONLY and never auto-replies.** `list_inbox` only does a Graph GET and is `@safe` (test_outlook_inbox); `match_replies` reads a stubbed inbox and the no-send spy stays empty (test_reply_matcher: `test_match_advances_status_and_records_reply` asserts `calls == []`). The cron sweep also never sends (test_apply_digest: `test_run_apply_weekly_sweeps_and_never_sends` asserts `sent == []`).
- [ ] **Interview/rejection is a flag, never auto-final.** `OutreachReply.confirmed` defaults False and stays False (test_outreach_reply_model, test_reply_matcher); the route/digest surface the flag as an unconfirmed suggestion (`test_summary_surfaces_reply_flag`, digest "flagged for your glance"). Status only advances to `replied` — never `interview`/`rejected` automatically.
- [ ] **Only Bo's tap sends.** Follow-ups are staged `OutreachItem(status="proposed")` rows (test_followups: `test_stages_followup_after_window_and_never_sends` asserts `calls == []`) and are sent ONLY through Phase 1's unchanged `approve_send` on `apply:send:{id}`. No new send path was introduced.
- [ ] **Follow-up caps + window + blocklist.** 7-day window (`test_recent_send_is_not_followed_up`), one-per-contact via `FOLLOWUP_PREFIX` dedup (`test_one_followup_per_contact`), daily cap (`test_daily_cap_limits_followups`), blocklist (`test_blocklist_is_honored`); replied items are never followed up (`test_replied_item_is_not_followed_up`). No silent caps — every drop is counted + reasoned.
- [ ] **No ALTER of Phase 1's `OutreachItem`.** Reply state lives in the NEW `OutreachReply` table (auto-creates via `create_all`) + the existing `status` field (`"replied"`) + follow-up rows linked by a `[followup] `-prefixed `dedup_key`. Phase 1's model is untouched.
- [ ] **Additive scope, no breakage.** `Mail.Read` appended to `microsoft_oauth.SCOPE` while preserving `Mail.Send`/`offline_access` (test_outlook_inbox: `test_scope_includes_mail_read`); Phase 1's oauth/outlook tests still pass.
- [ ] **No secrets in repo.** Mailbox read reuses Phase 1's `_access_token` (env override / `~/.borina/ms_oauth_token.json` chmod-600); no new keys; tests stub `list_inbox`/`http_get_json` and never touch `~/.borina`.
- [ ] **No new API key for the agent.** Follow-up drafting reuses `applier`'s registered `system_prompt` via Phase 1's `draft_email` → `run_agent_task` (claude CLI).
- [ ] **Read-only route is genuinely read-only.** `routes/outreach.py` exposes only `GET /outreach/summary`; no POST/send route (test_outreach_routes: `test_no_write_or_send_route_exists`).
- [ ] **Frontend mirrors `/daily`.** `/outreach` is a `useAsync` tab with loading/empty/error/data states (test_outreach-tab — 4 states), a `nav-config` link, and an additive `api.getOutreachSummary`; existing/new-tabs tests still pass.
- [ ] **Patterns mirrored, not invented.** reader ≙ Phase 1 `GraphSender` + `contacts.http_get_json` seam; table ≙ `OutreachItem`/`PlanItem`; matcher/follow-up ≙ `run_apply` session/summary style; route ≙ `routes/daily.py`; digest ≙ `register_fleet_health` Card + chat-id; tab ≙ `/daily` page + `new-tabs.test.tsx`.

## Final full-suite verification

- [ ] Run the entire backend suite and confirm green (no regressions in Phase 0/1 or existing tests):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest -q`
  Expected: all tests pass. The new Phase 3 files add ~24 tests; Phase 0/1 and the prior suite are unchanged. If any pre-existing test fails, it must fail identically on the pre-Phase-3 tree before this branch — otherwise fix the regression before declaring done.

- [ ] Run the entire frontend suite and confirm green:
  `cd /Users/clawd/borina-mesh/apps/web && npm test`
  Expected: all vitest tests pass (the new `/outreach` tab adds 4 tests; existing tabs, nav, and mobile tests are unchanged).
