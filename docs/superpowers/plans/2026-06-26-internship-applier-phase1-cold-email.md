> For agentic workers: use superpowers:subagent-driven-development or executing-plans

**Goal:** Build Phase 0 (validate Microsoft send) + Phase 1 (cold-email pipeline) of the internship cold-applier. Phase 0 registers a Microsoft OAuth + Graph send path with a one-shot send-validation route. Phase 1 adds the `applier` fleet agent and a propose-only discover→enrich→draft→stage pipeline whose ONLY outbound path (`outlook.send_mail`) is `user_initiated`-gated and reachable solely from Bo's Telegram approval tap. Spec: `/Users/clawd/borina-mesh/docs/superpowers/specs/2026-06-26-internship-cold-applier-design.md`.

**Architecture:** Mirror the existing mesh exactly. Microsoft OAuth lifecycle mirrors `integrations/google_oauth.py`; `routes/outlook.py` mirrors `routes/calendar.py`; `outlook.send_mail` mirrors `google_calendar.create_event`'s `user_initiated` hard gate; the `applier` agent mirrors `agents/planner.py`; `dispatch/apply.py` mirrors `planner.py`'s stage-then-approve engine (`generate_plan`/`approve_item`); the approval Card + `apply:send`/`apply:skip` callbacks mirror the planner/operator callbacks in `routes/telegram.py`; the `apply:` command mirrors the `build:`/`goal:` routing branches; the weekly cron mirrors `scheduler.register_fleet_health`. The `OutreachItem` SQLModel auto-creates via `init_db`'s `create_all` — no migration.

**Tech Stack:** Python 3.11 / FastAPI / SQLModel.

## Global Constraints

- **Python 3.11 / FastAPI / SQLModel.**
- **Tests run with:** `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest`
- **Hermetic conftest:** `apps/api/conftest.py` already redirects `DATABASE_URL`, `REPORTS_DIR`, and `GOOGLE_OAUTH_TOKEN_FILE` to throwaway temp paths and seeds the schema via `init_db()`. Mirror this for the Microsoft token file using a per-test `monkeypatch.setenv("MICROSOFT_OAUTH_TOKEN_FILE", ...)` (NEVER touch `~/.borina`).
- **Agents run via the claude CLI** through `agents.runner_v2.run_agent_task` — **NO API key** in code. The `applier` agent's `system_prompt` is resolved from its registered class; never hardcode a key.
- **SAFETY INVARIANT:** the only outbound paths (`outlook.send_mail` / form-submit) MUST require `user_initiated=True` and be reachable only from Bo's approval tap. The pipeline (discover/enrich/draft/stage) and the agent are text/data-only and MUST NEVER call a send path. Every send function refuses (`not_connected`) when `user_initiated` is False.
- **New tables auto-create** via `init_db`'s `SQLModel.metadata.create_all`. Define `OutreachItem` in `models.py`; conftest's `_init_test_db` imports `models` before `create_all`, so the table exists in tests with no manual migration.
- **DRY / YAGNI / TDD:** write the failing test first, run it (expect FAIL), implement the minimum real code, run it (expect PASS), commit. No placeholders.

---

## Task 0.1 — Microsoft OAuth token lifecycle (`integrations/microsoft_oauth.py`)

Mirror `integrations/google_oauth.py` exactly: consent URL → code exchange → server-side chmod-600 token file → auto-refresh. Tenant endpoints, scopes `offline_access Mail.Send User.Read`.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/integrations/microsoft_oauth.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_microsoft_oauth.py`

**Interfaces:**
- Consumes: `integrations.base.env`, `httpx`.
- Produces:
  - `configured() -> bool`
  - `redirect_uri() -> str` (default `http://localhost:8000/outlook/oauth/callback`)
  - `auth_url(state: str) -> str`
  - `new_state() -> str` / `check_state(state: str) -> bool`
  - `exchange_code(code: str) -> dict`
  - `get_access_token() -> str`
  - module constants `AUTH_URI`, `TOKEN_URI`, `SCOPE`
  - env vars: `MICROSOFT_OAUTH_CLIENT_ID`, `MICROSOFT_OAUTH_CLIENT_SECRET`, `MICROSOFT_OAUTH_REDIRECT_URI`, `MICROSOFT_OAUTH_TOKEN_FILE`, `MICROSOFT_OAUTH_ACCESS_TOKEN`

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_microsoft_oauth.py`:

```python
"""Microsoft OAuth lifecycle (Phase 0): consent URL → code exchange → server-side
token file → auto-refresh. Mirrors test_google_oauth. Tokens never reach the
frontend or URLs; MICROSOFT_OAUTH_ACCESS_TOKEN wins when set (tests/override)."""
import json
import time

import pytest

from integrations import microsoft_oauth as mso


@pytest.fixture(autouse=True)
def _creds(monkeypatch, tmp_path):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("MICROSOFT_OAUTH_TOKEN_FILE", str(tmp_path / "ms_tok.json"))
    yield


def _fake_post(response: dict, calls: list):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return response

    def post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data})
        return R()

    return post


def test_configured_requires_both_creds(monkeypatch):
    assert mso.configured() is True
    monkeypatch.delenv("MICROSOFT_OAUTH_CLIENT_ID", raising=False)
    assert mso.configured() is False


def test_auth_url_requests_offline_consent():
    url = mso.auth_url(state="st4te")
    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url
    assert "state=st4te" in url
    assert "Mail.Send" in url and "offline_access" in url


def test_exchange_code_persists_tokens(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mso.httpx, "post",
        _fake_post({"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600}, calls),
    )
    mso.exchange_code("c0de")
    assert calls[0]["data"]["grant_type"] == "authorization_code"
    saved = json.loads(mso._token_file().read_text())
    assert saved["refresh_token"] == "rt1"
    assert saved["expires_at"] > time.time()
    assert mso.get_access_token() == "at1"


def test_refresh_when_expired_preserves_refresh_token(monkeypatch):
    mso._save({"access_token": "old", "refresh_token": "rt1", "expires_in": -120})
    calls = []
    monkeypatch.setattr(
        mso.httpx, "post",
        _fake_post({"access_token": "at2", "expires_in": 3600}, calls),
    )
    assert mso.get_access_token() == "at2"
    assert calls[0]["data"]["grant_type"] == "refresh_token"
    saved = json.loads(mso._token_file().read_text())
    assert saved["refresh_token"] == "rt1"


def test_no_tokens_means_empty(monkeypatch):
    assert mso.get_access_token() == ""


def test_env_access_token_still_wins(monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_ACCESS_TOKEN", "env-tok")
    assert mso.get_access_token() == "env-tok"


def test_check_state_round_trip():
    st = mso.new_state()
    assert mso.check_state(st) is True
    assert mso.check_state("wrong") is False
```

- [ ] Run it (expect FAIL — module does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_microsoft_oauth.py -q`
  Expected: `ModuleNotFoundError: No module named 'integrations.microsoft_oauth'` (collection error / errors).

- [ ] Minimal implementation. Create `/Users/clawd/borina-mesh/apps/api/integrations/microsoft_oauth.py`:

```python
"""Microsoft OAuth token lifecycle: consent URL → code exchange → auto-refresh.

Security model (spec §0): tokens live in a chmod-600 server-side JSON file
(default ``~/.borina/ms_oauth_token.json``) — never the frontend, never URLs,
never the repo. Access tokens expire hourly; ``get_access_token`` refreshes
transparently using the stored refresh_token. The env var
``MICROSOFT_OAUTH_ACCESS_TOKEN`` takes precedence when set (tests / manual
override). A random ``state`` is persisted at consent-start and validated at the
callback (CSRF guard). Mirrors integrations/google_oauth.py.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

from .base import env

AUTH_URI = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URI = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
SCOPE = "offline_access Mail.Send User.Read"


def configured() -> bool:
    return bool(env("MICROSOFT_OAUTH_CLIENT_ID") and env("MICROSOFT_OAUTH_CLIENT_SECRET"))


def _token_file() -> Path:
    return Path(
        os.getenv("MICROSOFT_OAUTH_TOKEN_FILE")
        or (Path.home() / ".borina" / "ms_oauth_token.json")
    )


def _state_file() -> Path:
    return _token_file().with_suffix(".state")


def redirect_uri() -> str:
    return env("MICROSOFT_OAUTH_REDIRECT_URI") or "http://localhost:8000/outlook/oauth/callback"


def auth_url(state: str) -> str:
    return AUTH_URI + "?" + urlencode({
        "client_id": env("MICROSOFT_OAUTH_CLIENT_ID"),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "select_account consent",
        "state": state,
    })


def new_state() -> str:
    state = secrets.token_urlsafe(24)
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(state)
    return state


def _load_state() -> str:
    f = _state_file()
    return f.read_text().strip() if f.exists() else ""


def check_state(state: str) -> bool:
    expected = _load_state()
    return bool(expected) and secrets.compare_digest(state or "", expected)


def _load() -> Optional[dict]:
    f = _token_file()
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


def _save(tokens: dict) -> None:
    existing = _load() or {}
    if not tokens.get("refresh_token") and existing.get("refresh_token"):
        tokens["refresh_token"] = existing["refresh_token"]
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600)) - 60
    f = _token_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(tokens))
    try:
        f.chmod(0o600)
    except OSError:
        pass


def exchange_code(code: str) -> dict:
    resp = httpx.post(TOKEN_URI, data={
        "code": code,
        "client_id": env("MICROSOFT_OAUTH_CLIENT_ID"),
        "client_secret": env("MICROSOFT_OAUTH_CLIENT_SECRET"),
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
        "scope": SCOPE,
    }, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()
    _save(tokens)
    return tokens


def _refresh(refresh_token: str) -> dict:
    resp = httpx.post(TOKEN_URI, data={
        "client_id": env("MICROSOFT_OAUTH_CLIENT_ID"),
        "client_secret": env("MICROSOFT_OAUTH_CLIENT_SECRET"),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": SCOPE,
    }, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()
    _save(tokens)
    return tokens


def get_access_token() -> str:
    """A currently-valid access token, refreshing if needed. "" when unauthorized."""
    override = env("MICROSOFT_OAUTH_ACCESS_TOKEN")
    if override:
        return override
    tokens = _load()
    if not tokens:
        return ""
    if tokens.get("access_token") and time.time() < tokens.get("expires_at", 0):
        return tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return ""
    try:
        return _refresh(refresh_token).get("access_token", "")
    except Exception as exc:  # noqa: BLE001
        print(f"[microsoft-oauth] refresh failed: {exc}")
        return ""
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_microsoft_oauth.py -q`
  Expected: `7 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/integrations/microsoft_oauth.py apps/api/tests/test_microsoft_oauth.py && git commit -m "Phase 0: Microsoft OAuth token lifecycle (mirrors google_oauth)"`

---

## Task 0.2 — `integrations/outlook.py` send_mail (Graph primary, user_initiated-gated)

The single outbound path. `send_mail` hard-refuses unless `user_initiated=True` (mirrors `google_calendar.create_event`). Graph transport `GraphSender` posts `/me/sendMail`. `BrowserSender` is the fallback stub. The wired sender is chosen by `_sender()`.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/integrations/outlook.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_outlook.py`

**Interfaces:**
- Consumes: `integrations.base.{IntegrationResult, env, http_post_json, not_connected, ok, safe}`, `integrations.microsoft_oauth.get_access_token`.
- Produces:
  - `SOURCE = "outlook"`
  - `send_mail(recipients: list[str], subject: str, body: str, *, attachments: Optional[list[str]] = None, user_initiated: bool = False, send_via: Optional[str] = None) -> IntegrationResult`
  - `status() -> IntegrationResult`
  - classes `GraphSender` (`.send(recipients, subject, body, attachments) -> dict`), `BrowserSender`
  - `_sender(send_via: Optional[str]) -> Sender`
  - env: `OUTLOOK_SEND_TRANSPORT` (`"graph"` default | `"browser"`)
  - `send_mail` data on success: `{"id": str, "via": "graph"|"browser"}`

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_outlook.py`:

```python
"""Outlook send transport (Phase 1). The single outbound path: send_mail HARD
refuses unless user_initiated=True. Graph/Browser backends are stubbed — no real
network in tests. Mirrors the google_calendar create_event gate."""
import pytest

from integrations import outlook
from integrations import microsoft_oauth as mso


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MICROSOFT_OAUTH_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("OUTLOOK_SEND_TRANSPORT", "graph")
    yield


def test_send_mail_refuses_without_user_initiated():
    res = outlook.send_mail(["a@b.com"], "Hi", "Body")
    assert res.connected is False
    assert "explicit user action" in (res.error or "")


def test_send_mail_refuses_even_when_authorized():
    # Authorized but no user action → still refuses (the invariant).
    res = outlook.send_mail(["a@b.com"], "Hi", "Body", user_initiated=False)
    assert res.connected is False


def test_send_mail_not_connected_when_unauthorized(monkeypatch):
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(mso, "get_access_token", lambda: "")
    res = outlook.send_mail(["a@b.com"], "Hi", "Body", user_initiated=True)
    assert res.connected is False
    assert "not authorized" in (res.error or "").lower()


def test_send_mail_graph_success_with_user_initiated(monkeypatch):
    sent = {}

    def fake_post(url, *, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["auth"] = (headers or {}).get("Authorization")
        return {}  # Graph sendMail returns 202 with empty body

    monkeypatch.setattr(outlook, "http_post_json", fake_post)
    res = outlook.send_mail(["a@b.com"], "Subj", "Hello", user_initiated=True)
    assert res.connected is True
    assert res.data["via"] == "graph"
    assert sent["url"].endswith("/me/sendMail")
    assert sent["json"]["message"]["subject"] == "Subj"
    assert sent["json"]["message"]["toRecipients"][0]["emailAddress"]["address"] == "a@b.com"
    assert sent["auth"] == "Bearer tok"


def test_browser_sender_used_when_transport_browser(monkeypatch):
    monkeypatch.setenv("OUTLOOK_SEND_TRANSPORT", "browser")
    captured = {}

    def fake_browser_send(self, recipients, subject, body, attachments):
        captured["recipients"] = recipients
        return {"id": "browser-1"}

    monkeypatch.setattr(outlook.BrowserSender, "send", fake_browser_send)
    res = outlook.send_mail(["x@y.com"], "S", "B", user_initiated=True)
    assert res.connected is True
    assert res.data["via"] == "browser"
    assert captured["recipients"] == ["x@y.com"]
```

- [ ] Run it (expect FAIL — module does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outlook.py -q`
  Expected: collection error `ModuleNotFoundError: No module named 'integrations.outlook'`.

- [ ] Minimal implementation. Create `/Users/clawd/borina-mesh/apps/api/integrations/outlook.py`:

```python
"""Outlook send — the ONLY outbound application path (spec §0/§1).

Safety invariant: `send_mail` HARD-refuses unless `user_initiated=True` is passed
by the route/callback in response to a real Bo approval tap — an agent/pipeline
path can NEVER reach the send branch (mirrors google_calendar.create_event). Two
backends behind one interface: GraphSender (Microsoft Graph /me/sendMail, primary)
and BrowserSender (Playwright on Bo's logged-in Outlook web, fallback). Reading is
out of scope for Phase 1; only the gated send exists here.
"""
from __future__ import annotations

from typing import Optional

from .base import (
    IntegrationResult,
    env,
    http_post_json,
    not_connected,
    ok,
    safe,
)

SOURCE = "outlook"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _access_token() -> str:
    from .microsoft_oauth import get_access_token

    return get_access_token()


def _oauth_configured() -> bool:
    return bool(env("MICROSOFT_OAUTH_CLIENT_ID") and env("MICROSOFT_OAUTH_CLIENT_SECRET"))


class GraphSender:
    """Microsoft Graph POST /me/sendMail (primary)."""

    via = "graph"

    def send(self, recipients: list[str], subject: str, body: str,
             attachments: Optional[list[str]]) -> dict:
        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": r}} for r in recipients],
        }
        http_post_json(
            f"{GRAPH_BASE}/me/sendMail",
            json={"message": message, "saveToSentItems": True},
            headers={"Authorization": f"Bearer {_access_token()}"},
        )
        return {"id": "graph-sent"}


class BrowserSender:
    """Playwright-driven Outlook web compose (fallback). Stubbed in tests; the
    real Playwright driver is wired in only if Phase 0 picks browser transport."""

    via = "browser"

    def send(self, recipients: list[str], subject: str, body: str,
             attachments: Optional[list[str]]) -> dict:
        raise RuntimeError("browser transport not wired — set OUTLOOK_SEND_TRANSPORT=graph")


def _sender(send_via: Optional[str]):
    choice = (send_via or env("OUTLOOK_SEND_TRANSPORT") or "graph").lower()
    return BrowserSender() if choice == "browser" else GraphSender()


def status() -> IntegrationResult:
    if not _oauth_configured():
        return not_connected(SOURCE, "MICROSOFT_OAUTH_CLIENT_ID/SECRET not set")
    if not _access_token():
        return not_connected(SOURCE, "not authorized — complete Microsoft OAuth consent")
    return ok(SOURCE, {"authorized": True})


@safe(SOURCE)
def send_mail(
    recipients: list[str],
    subject: str,
    body: str,
    *,
    attachments: Optional[list[str]] = None,
    user_initiated: bool = False,
    send_via: Optional[str] = None,
) -> IntegrationResult:
    """Send an email. HARD safety gate: refuses unless `user_initiated` is True.

    This is the only outbound path and is never reachable from an agent/auto
    path — the caller must pass user_initiated=True only for a real Bo approval
    tap. On any transport error the @safe decorator yields a retryable
    not-connected result (never a 500, never a silent loss)."""
    if not user_initiated:
        return not_connected(
            SOURCE,
            "refused: email sending requires an explicit user action",
        )
    if not _oauth_configured() or not _access_token():
        return not_connected(SOURCE, "Outlook not authorized")
    sender = _sender(send_via)
    result = sender.send(recipients, subject, body, attachments)
    return ok(SOURCE, {"id": result.get("id"), "via": sender.via})
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outlook.py -q`
  Expected: `5 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/integrations/outlook.py apps/api/tests/test_outlook.py && git commit -m "Phase 1: outlook.send_mail (Graph primary, browser fallback, user_initiated-gated)"`

---

## Task 0.3 — `routes/outlook.py` (OAuth consent + one-shot send-validation) + main wiring

Mirror `routes/calendar.py`: `/outlook/oauth/start` redirects to consent, `/outlook/oauth/callback` validates state + exchanges code, `POST /outlook/send` is the one-shot send-validation path (Phase 0 deliverable) that hard-gates `user_initiated`.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/routes/outlook.py`
- Modify: `/Users/clawd/borina-mesh/apps/api/main.py` (import + include router)
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_outlook_routes.py`

**Interfaces:**
- Consumes: `integrations.outlook.send_mail`, `integrations.microsoft_oauth`.
- Produces:
  - `router = APIRouter(prefix="/outlook", tags=["outlook"])`
  - `class EmailCreate(BaseModel)` fields: `recipients: list[str]`, `subject: str`, `body: str`, `user_initiated: bool = False`
  - routes: `POST /outlook/send` (201), `GET /outlook/oauth/start`, `GET /outlook/oauth/callback`

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_outlook_routes.py`:

```python
"""Outlook routes (Phase 0): OAuth consent flow + the one-shot send-validation
path. The POST hard-gates user_initiated so an agent/non-UI path can never send.
Mirrors test_google_oauth route tests + the calendar create gate."""
import pytest
from fastapi.testclient import TestClient

from main import app
from integrations import microsoft_oauth as mso
from integrations import outlook

client = TestClient(app)


@pytest.fixture(autouse=True)
def _creds(monkeypatch, tmp_path):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MICROSOFT_OAUTH_TOKEN_FILE", str(tmp_path / "ms_tok.json"))
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    yield


def test_send_rejects_without_user_initiated(monkeypatch):
    def must_not_send(*a, **k):
        pytest.fail("send_mail must not be called without user_initiated")

    monkeypatch.setattr(outlook, "send_mail", must_not_send)
    r = client.post("/outlook/send", json={
        "recipients": ["a@b.com"], "subject": "S", "body": "B",
    })
    assert r.status_code == 403


def test_send_passes_user_initiated_true(monkeypatch):
    calls = []

    def spy(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None):
        calls.append({"user_initiated": user_initiated, "recipients": recipients})
        from integrations.base import ok
        return ok("outlook", {"id": "x", "via": "graph"})

    monkeypatch.setattr(outlook, "send_mail", spy)
    r = client.post("/outlook/send", json={
        "recipients": ["a@b.com"], "subject": "S", "body": "B",
        "user_initiated": True,
    })
    assert r.status_code == 201
    assert len(calls) == 1 and calls[0]["user_initiated"] is True


def test_oauth_start_redirects_to_microsoft():
    r = client.get("/outlook/oauth/start", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://login.microsoftonline.com/")


def test_oauth_callback_exchanges_and_confirms(monkeypatch):
    client.get("/outlook/oauth/start", follow_redirects=False)
    state = mso._load_state()
    seen = {}
    monkeypatch.setattr(mso, "exchange_code", lambda code: seen.setdefault("code", code))
    r = client.get(f"/outlook/oauth/callback?code=abc&state={state}")
    assert r.status_code == 200 and "connected" in r.text.lower()
    assert seen["code"] == "abc"


def test_oauth_callback_rejects_bad_state(monkeypatch):
    client.get("/outlook/oauth/start", follow_redirects=False)
    monkeypatch.setattr(mso, "exchange_code", lambda code: pytest.fail("must not exchange"))
    r = client.get("/outlook/oauth/callback?code=abc&state=wrong")
    assert r.status_code == 400


def test_oauth_start_fails_without_creds(monkeypatch):
    monkeypatch.delenv("MICROSOFT_OAUTH_CLIENT_ID", raising=False)
    r = client.get("/outlook/oauth/start", follow_redirects=False)
    assert r.status_code == 400
```

- [ ] Run it (expect FAIL — route not mounted):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outlook_routes.py -q`
  Expected: failures with `404` (and import error on `routes.outlook`).

- [ ] Minimal implementation. Create `/Users/clawd/borina-mesh/apps/api/routes/outlook.py`:

```python
"""Outlook API (spec §0/§1).

Mounted at `/outlook` (frontend: `/api/outlook/...`). The POST /outlook/send is
the Phase-0 one-shot send-validation path AND the Phase-1 send endpoint — it
rejects anything not flagged `user_initiated=True`, so an agent/non-UI path can
never send. Microsoft OAuth consent is exchanged + stored server-side only
(integrations/microsoft_oauth); nothing sensitive transits the frontend. `state`
is generated at /start and validated at /callback (CSRF guard). Mirrors
routes/calendar.py.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from integrations import outlook

router = APIRouter(prefix="/outlook", tags=["outlook"])


class EmailCreate(BaseModel):
    recipients: list[str]
    subject: str
    body: str
    # Security gate: must be True, set by the UI in response to a real click.
    user_initiated: bool = False


@router.post("/send", status_code=201)
def send_email(body: EmailCreate):
    if not body.user_initiated:
        # Hard gate — never auto-send from an agent/non-UI path.
        raise HTTPException(403, "email sending requires an explicit user action")
    result = outlook.send_mail(
        recipients=body.recipients,
        subject=body.subject,
        body=body.body,
        user_initiated=True,
    )
    return result.to_dict()


# ── Microsoft OAuth consent flow ──────────────────────────────────────────────

@router.get("/oauth/start")
def oauth_start():
    """Redirect the browser to Microsoft's consent screen."""
    from fastapi.responses import RedirectResponse
    from integrations import microsoft_oauth

    if not microsoft_oauth.configured():
        raise HTTPException(400, "MICROSOFT_OAUTH_CLIENT_ID/SECRET not set")
    return RedirectResponse(microsoft_oauth.auth_url(state=microsoft_oauth.new_state()))


@router.get("/oauth/callback")
def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Exchange the consent code for tokens (stored server-side)."""
    import html as _html
    from fastapi.responses import HTMLResponse
    from integrations import microsoft_oauth

    if error:
        return HTMLResponse(
            f"<h3>Microsoft OAuth failed: {_html.escape(error)}</h3>", status_code=400
        )
    if not code:
        raise HTTPException(400, "missing code")
    if not microsoft_oauth.check_state(state or ""):
        raise HTTPException(400, "state mismatch — restart at /outlook/oauth/start")
    microsoft_oauth.exchange_code(code)
    return HTMLResponse("<h3>Outlook connected. You can close this tab.</h3>")
```

- [ ] Wire the router in `main.py`. Edit the imports line that ends `... telegram as telegram_routes, files as files_routes` to append `, outlook as outlook_routes`:

```python
from routes import agents as agents_routes, chat as chat_routes, jobs as jobs_routes, activity as activity_routes, schedules as schedules_routes, analytics as analytics_routes, artifacts as artifacts_routes, logs as logs_routes, wiki as wiki_routes, briefs as briefs_routes, memory as memory_routes, workspace as workspace_routes, threads as threads_routes, tasks as tasks_routes, stats as stats_routes, finance as finance_routes, finance_lifeos as finance_lifeos_routes, daily as daily_routes, calendar as calendar_routes, telegram as telegram_routes, files as files_routes, outlook as outlook_routes
```

  Then add the include after `app.include_router(files_routes.router)`:

```python
app.include_router(files_routes.router)
app.include_router(outlook_routes.router)
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outlook_routes.py -q`
  Expected: `6 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/routes/outlook.py apps/api/main.py apps/api/tests/test_outlook_routes.py && git commit -m "Phase 0: /outlook OAuth consent + one-shot send-validation route (gated)"`

---

## Task 1.1 — `OutreachItem` SQLModel table

The Phase 1 staging table. Auto-creates via `init_db`'s `create_all`; conftest imports `models` before `create_all` so the table exists in tests.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/models.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_outreach_model.py`

**Interfaces:**
- Produces `class OutreachItem(SQLModel, table=True)` with fields:
  `id: Optional[int]` (pk); `track: str`; `company: str`; `company_domain: Optional[str] = None`; `contact_name: Optional[str] = None`; `contact_email: str`; `subject: str`; `body: str`; `status: str = "proposed"` (indexed); `dedup_key: str` (indexed); `send_via: Optional[str] = None`; `error: Optional[str] = None`; `created_at: datetime` (indexed, default `utcnow`); `sent_at: Optional[datetime] = None`.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_outreach_model.py`:

```python
"""OutreachItem staging table (Phase 1). Auto-created by init_db's create_all —
no migration. Defaults: status='proposed', timestamps."""
from datetime import datetime

from sqlmodel import select

from db import session_scope
from models import OutreachItem


def test_outreach_item_defaults_and_persist():
    with session_scope() as s:
        item = OutreachItem(
            track="swe", company="Acme AI", contact_email="founder@acme.ai",
            subject="Internship interest", body="Hi there",
            dedup_key="founder@acme.ai|acme.ai",
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        assert item.id is not None
        assert item.status == "proposed"
        assert item.send_via is None and item.sent_at is None
        assert isinstance(item.created_at, datetime)


def test_outreach_item_queryable_by_dedup_key():
    with session_scope() as s:
        s.add(OutreachItem(track="finance", company="FinCo",
                           contact_email="r@finco.com", subject="x", body="y",
                           dedup_key="r@finco.com|finco.com"))
        s.commit()
        rows = s.exec(
            select(OutreachItem).where(OutreachItem.dedup_key == "r@finco.com|finco.com")
        ).all()
        assert len(rows) == 1 and rows[0].company == "FinCo"
```

- [ ] Run it (expect FAIL — model does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outreach_model.py -q`
  Expected: collection error `ImportError: cannot import name 'OutreachItem' from 'models'`.

- [ ] Minimal implementation. Append to `/Users/clawd/borina-mesh/apps/api/models.py` (after `ConversationLog`):

```python
class OutreachItem(SQLModel, table=True):
    """A staged cold-email outreach (Phase 1). NEVER auto-sent — a send only
    happens when Bo approves this item via Telegram (the user-initiated action).
    status: proposed | sent | skipped | failed. Mirrors PlanItem's stage-then-
    approve lifecycle. Auto-created by init_db's create_all."""
    id: Optional[int] = Field(default=None, primary_key=True)
    track: str                                    # "swe" | "finance"
    company: str
    company_domain: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: str
    subject: str
    body: str
    status: str = Field(default="proposed", index=True)
    dedup_key: str = Field(index=True)            # normalized contact_email + domain
    send_via: Optional[str] = None                # "graph" | "browser"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    sent_at: Optional[datetime] = None
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_outreach_model.py -q`
  Expected: `2 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/models.py apps/api/tests/test_outreach_model.py && git commit -m "Phase 1: OutreachItem staging table"`

---

## Task 1.2 — `applier` fleet agent (class + registration + roster + AGENT_REGISTRY)

Register the propose-only `applier` agent. Mirror `agents/planner.py` for the class; add roster + registry entries per the fleet-agent grounding.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/agents/applier.py`
- Modify: `/Users/clawd/borina-mesh/apps/api/agents/runner_v2.py` (AGENT_REGISTRY)
- Modify: `/Users/clawd/borina-mesh/apps/api/fleet_roster.py` (SHORT_TO_LONG + ROSTER_SEED)
- Modify: `/Users/clawd/borina-mesh/apps/api/main.py` (import to trigger registration)
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_applier_agent.py`

**Interfaces:**
- Produces:
  - `class ApplierAgent(Agent)` with `id = "applier"`, `name = "Applier"`, `emoji`, `tagline`, `system_prompt`, `tools = ["read_file", "write_file"]`; `registry.register(ApplierAgent)` at import.
  - `AGENT_REGISTRY["applier"] = {"long_id": "applier"}`
  - `SHORT_TO_LONG["applier"] = "applier"`; `ROSTER_SEED["applier"] = ACTIVE`

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_applier_agent.py`:

```python
"""Applier fleet agent (Phase 1): registered, routable, in AGENT_REGISTRY."""
import agents.applier  # noqa: F401 — registers the agent
import fleet_roster as fr
from agents.base import registry
from agents.runner_v2 import AGENT_REGISTRY


def test_applier_registered_in_base_registry():
    agent = registry.get("applier")
    assert agent is not None
    assert agent.id == "applier"
    assert agent.system_prompt  # has a real persona, not empty


def test_applier_in_agent_registry():
    assert AGENT_REGISTRY["applier"]["long_id"] == "applier"


def test_applier_short_to_long_and_active(tmp_path, monkeypatch):
    from db import engine
    fr.seed_roster(engine)
    assert fr.SHORT_TO_LONG["applier"] == "applier"
    assert fr.get_state("applier") == fr.ACTIVE
    assert fr.is_routable("applier") is True
```

- [ ] Run it (expect FAIL — agent module/registry entries missing):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_applier_agent.py -q`
  Expected: collection error `ModuleNotFoundError: No module named 'agents.applier'`.

- [ ] Create `/Users/clawd/borina-mesh/apps/api/agents/applier.py`:

```python
"""Applier agent (Phase 1) — the propose-only internship cold-applier persona.

Drafts a short, specific cold email per target company, tying the company's
actual AI work to Bo's profile. It PREPARES text only — it never sends. The
single send path (integrations/outlook.send_mail) is reachable only from Bo's
Telegram approval tap. The pipeline lives in dispatch/apply.py; this just
registers the agent in the roster (mirrors agents/planner.py)."""

from agents.base import Agent, registry


class ApplierAgent(Agent):
    id = "applier"
    name = "Applier"
    emoji = "\U0001F4E8"  # 📨
    tagline = "Drafts tailored internship cold emails for your approval"
    system_prompt = (
        "You are the Applier agent of Borina Mesh. Bo is a business major hunting "
        "AI-focused internships on two tracks: AI SWE and AI finance, startup-leaning, "
        "near Toronto or remote. For each target company you are given (name, domain, "
        "why_fit, track, contact), draft ONE short, specific cold email: reference the "
        "company's actual AI work, tie it to Bo's profile, name the track, and ask about "
        "internships. Per-track tone — SWE: concrete on shipping/building; finance: "
        "concrete on markets/quant. Output ONLY the email subject and body. You PROPOSE "
        "drafts; you never send anything yourself — Bo approves each one."
    )
    tools = ["read_file", "write_file"]


registry.register(ApplierAgent)
```

- [ ] Add the AGENT_REGISTRY entry. In `/Users/clawd/borina-mesh/apps/api/agents/runner_v2.py`, edit the `AGENT_REGISTRY` dict — add the `"applier"` line after `"planner"`:

```python
    "planner":    {"long_id": "planner"},
    "applier":    {"long_id": "applier"},
```

- [ ] Add the roster mappings. In `/Users/clawd/borina-mesh/apps/api/fleet_roster.py`, add to `SHORT_TO_LONG` (after `"planner": "planner",`):

```python
    "planner": "planner",
    "applier": "applier",
```

  And add to `ROSTER_SEED` (after `"researcher": ACTIVE,`):

```python
    "researcher": ACTIVE,
    "applier": ACTIVE,
```

- [ ] Wire the import in `main.py` so registration fires on startup. After `import agents.builder  # noqa`:

```python
import agents.builder  # noqa
import agents.applier  # noqa
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_applier_agent.py -q`
  Expected: `3 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/agents/applier.py apps/api/agents/runner_v2.py apps/api/fleet_roster.py apps/api/main.py apps/api/tests/test_applier_agent.py && git commit -m "Phase 1: applier fleet agent (registered, active, routable)"`

---

## Task 1.3 — `integrations/contacts.py` (Hunter enrichment, IntegrationResult, stubbed in tests)

Resolve the best hiring contact + verified email per company. Hunter behind the `IntegrationResult` envelope; key from `HUNTER_API_KEY`. No confident email → drop (logged via the caller, never silent).

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/integrations/contacts.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_contacts.py`

**Interfaces:**
- Consumes: `integrations.base.{IntegrationResult, env, http_get_json, not_connected, ok, safe}`.
- Produces:
  - `SOURCE = "contacts"`
  - `find_contact(company: str, domain: str) -> IntegrationResult` — `.data` on success: `{"name": Optional[str], "email": str, "confidence": int, "domain": str}`.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_contacts.py`:

```python
"""Contact enrichment (Phase 1). Hunter behind IntegrationResult — stubbed, no
real network. No key → not_connected; no confident email → not_connected."""
import pytest

from integrations import contacts


def test_no_key_is_not_connected(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    res = contacts.find_contact("Acme AI", "acme.ai")
    assert res.connected is False
    assert "HUNTER_API_KEY" in (res.error or "")


def test_find_contact_returns_best_email(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "k")

    def fake_get(url, *, params=None, headers=None, timeout=None):
        return {"data": {"emails": [
            {"value": "intern@acme.ai", "first_name": "I", "last_name": "X",
             "confidence": 40, "position": "intern"},
            {"value": "founder@acme.ai", "first_name": "Ada", "last_name": "Lee",
             "confidence": 92, "position": "Founder"},
        ]}}

    monkeypatch.setattr(contacts, "http_get_json", fake_get)
    res = contacts.find_contact("Acme AI", "acme.ai")
    assert res.connected is True
    assert res.data["email"] == "founder@acme.ai"
    assert res.data["confidence"] == 92
    assert res.data["name"] == "Ada Lee"
    assert res.data["domain"] == "acme.ai"


def test_no_confident_email_is_not_connected(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "k")

    def fake_get(url, *, params=None, headers=None, timeout=None):
        return {"data": {"emails": [
            {"value": "info@acme.ai", "confidence": 10, "position": "general"},
        ]}}

    monkeypatch.setattr(contacts, "http_get_json", fake_get)
    res = contacts.find_contact("Acme AI", "acme.ai")
    assert res.connected is False
    assert "confident" in (res.error or "").lower()
```

- [ ] Run it (expect FAIL — module does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_contacts.py -q`
  Expected: collection error `ModuleNotFoundError: No module named 'integrations.contacts'`.

- [ ] Minimal implementation. Create `/Users/clawd/borina-mesh/apps/api/integrations/contacts.py`:

```python
"""Contact enrichment (spec §1) — resolve the best hiring contact + a verified
email per company. Hunter by default (key from HUNTER_API_KEY), isolated behind
find_contact so Apollo could swap in later. Pure data: returns an
IntegrationResult, never sends anything. A company with no confident email yields
not_connected so the pipeline drops it (logged by the caller, never silent).
"""
from __future__ import annotations

from .base import IntegrationResult, env, http_get_json, not_connected, ok, safe

SOURCE = "contacts"
HUNTER_BASE = "https://api.hunter.io/v2/domain-search"
MIN_CONFIDENCE = 50  # below this we don't trust the email enough to cold-mail


@safe(SOURCE)
def find_contact(company: str, domain: str) -> IntegrationResult:
    """Best hiring contact + verified email for a domain. not_connected when no
    key, or when no email clears the confidence bar."""
    key = env("HUNTER_API_KEY")
    if not key:
        return not_connected(SOURCE, "HUNTER_API_KEY not set")
    raw = http_get_json(HUNTER_BASE, params={"domain": domain, "api_key": key})
    emails = ((raw or {}).get("data") or {}).get("emails") or []
    if not emails:
        return not_connected(SOURCE, f"no contacts found for {domain}")
    best = max(emails, key=lambda e: e.get("confidence", 0))
    if best.get("confidence", 0) < MIN_CONFIDENCE:
        return not_connected(SOURCE, f"no confident email for {domain}")
    name = " ".join(p for p in (best.get("first_name"), best.get("last_name")) if p) or None
    return ok(SOURCE, {
        "name": name,
        "email": best["value"],
        "confidence": best.get("confidence", 0),
        "domain": domain,
    })
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_contacts.py -q`
  Expected: `3 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/integrations/contacts.py apps/api/tests/test_contacts.py && git commit -m "Phase 1: contacts.find_contact (Hunter enrichment, IntegrationResult)"`

---

## Task 1.4 — `dispatch/apply.py` pipeline (discover→enrich→draft→stage), staging NEVER sends

The propose-only orchestrator. `run_apply` discovers candidates, enriches via `contacts.find_contact`, drafts via the applier agent, and stages `OutreachItem(status="proposed")`. It NEVER calls `outlook.send_mail`. `approve_send` is the ONLY path that sends, gated `user_initiated=True`. Mirrors `planner.generate_plan`/`approve_item`.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_apply_pipeline.py`

**Interfaces:**
- Consumes: `db.session_scope`, `models.OutreachItem`, `integrations.contacts.find_contact`, `integrations.outlook.send_mail`, `agents.runner_v2.run_agent_task`.
- Produces:
  - `BATCH_CAP = 8`, `DAILY_SEND_CAP = 10`, `DEFAULT_TRACKS = ("swe", "finance")`
  - `_dedup_key(email: str, domain: Optional[str]) -> str`
  - `discover(criteria: str = "") -> list[dict]` — `[{company, domain, why_fit, track}]`
  - `async draft_email(candidate: dict, contact: dict) -> dict` — `{subject, body}`
  - `async run_apply(criteria: str = "", chat_id: Optional[int] = None) -> dict` — stages items; returns `{"staged": int, "dropped": int, "item_ids": list[int], "reasons": list[str]}`. NEVER sends.
  - `get_proposed() -> list[dict]`
  - `approve_send(item_id: int) -> dict` — the ONLY send path (`user_initiated=True`); flips `sent`/`failed`.
  - `skip_item(item_id: int) -> dict` — flips `skipped`; sends nothing.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_apply_pipeline.py`:

```python
"""Cold-email pipeline (Phase 1). CORE INVARIANT: staging NEVER sends. Only
approve_send calls outlook.send_mail, and only with user_initiated=True. skip
sends nothing. Externals (discover/enrich/draft/send) are stubbed — no real
network, browser, or agent CLI. Mirrors test_planner's spy + lifecycle tests."""
import pytest
from sqlmodel import select

from db import session_scope
from models import OutreachItem
from dispatch import apply as ap
from integrations import contacts, outlook
from integrations.base import ok, not_connected


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    yield


def _stub_pipeline(monkeypatch, *, contact=None):
    # Deterministic discover: two candidates, one per track.
    monkeypatch.setattr(ap, "discover", lambda criteria="": [
        {"company": "Acme AI", "domain": "acme.ai", "why_fit": "LLM infra", "track": "swe"},
        {"company": "FinML", "domain": "finml.com", "why_fit": "quant AI", "track": "finance"},
    ])
    # Enrich: confident contact for both unless overridden.
    good = contact or {"name": "Ada Lee", "email": "ada@acme.ai", "confidence": 90, "domain": "acme.ai"}

    def fake_find(company, domain):
        return ok("contacts", {**good, "email": f"hire@{domain}", "domain": domain})

    monkeypatch.setattr(contacts, "find_contact", fake_find)

    # Draft: no real agent CLI.
    async def fake_draft(candidate, contact):
        return {"subject": f"Internship — {candidate['company']}",
                "body": f"Hi, re your {candidate['why_fit']} work."}

    monkeypatch.setattr(ap, "draft_email", fake_draft)


def _spy_send(monkeypatch):
    calls = []

    def fake_send(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None):
        calls.append({"recipients": recipients, "user_initiated": user_initiated})
        return ok("outlook", {"id": "sent-1", "via": "graph"})

    monkeypatch.setattr(outlook, "send_mail", fake_send)
    return calls


@pytest.mark.asyncio
async def test_run_apply_stages_and_never_sends(monkeypatch):
    _stub_pipeline(monkeypatch)
    calls = _spy_send(monkeypatch)
    summary = await ap.run_apply("AI internships")
    assert summary["staged"] == 2
    # CORE INVARIANT: staging sent nothing.
    assert calls == []
    with session_scope() as s:
        rows = s.exec(select(OutreachItem)).all()
        assert len(rows) == 2
        assert all(r.status == "proposed" for r in rows)


@pytest.mark.asyncio
async def test_no_send_regression(monkeypatch):
    """Explicit guard: building/regenerating a batch must never call send_mail."""
    _stub_pipeline(monkeypatch)
    calls = _spy_send(monkeypatch)
    await ap.run_apply()
    await ap.run_apply()
    assert calls == [], "pipeline must never auto-send"


@pytest.mark.asyncio
async def test_enrichment_drop_is_reported(monkeypatch):
    _stub_pipeline(monkeypatch)

    def fake_find(company, domain):
        return not_connected("contacts", "no confident email")

    monkeypatch.setattr(contacts, "find_contact", fake_find)
    summary = await ap.run_apply()
    assert summary["staged"] == 0
    assert summary["dropped"] == 2
    assert any("no confident email" in r for r in summary["reasons"])


@pytest.mark.asyncio
async def test_dedup_skips_already_staged(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()
    summary2 = await ap.run_apply()  # same candidates → deduped
    assert summary2["staged"] == 0
    assert summary2["dropped"] == 2
    assert any("dedup" in r.lower() for r in summary2["reasons"])


@pytest.mark.asyncio
async def test_approve_send_is_the_only_user_initiated_path(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()
    calls = _spy_send(monkeypatch)
    item = ap.get_proposed()[0]
    res = ap.approve_send(item["id"])
    assert res["status"] == "sent"
    assert len(calls) == 1 and calls[0]["user_initiated"] is True
    # idempotent: approving again sends nothing more.
    res2 = ap.approve_send(item["id"])
    assert res2.get("already_decided") is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_send_stays_retryable(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()

    def fail_send(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None):
        return not_connected("outlook", "Outlook not authorized")

    monkeypatch.setattr(outlook, "send_mail", fail_send)
    item = ap.get_proposed()[0]
    res = ap.approve_send(item["id"])
    assert res["status"] == "failed"
    # still queryable as failed with an error, not lost.
    with session_scope() as s:
        row = s.get(OutreachItem, item["id"])
        assert row.status == "failed" and row.error


@pytest.mark.asyncio
async def test_skip_sends_nothing(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()
    calls = _spy_send(monkeypatch)
    item = ap.get_proposed()[0]
    res = ap.skip_item(item["id"])
    assert res["status"] == "skipped"
    assert calls == []
```

- [ ] Run it (expect FAIL — module does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_pipeline.py -q`
  Expected: collection error `ModuleNotFoundError: No module named 'dispatch.apply'`.

- [ ] Minimal implementation. Create `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py`:

```python
"""Cold-email pipeline (spec §1) — discover → enrich → draft → STAGE.

SAFETY — the whole point: `run_apply` NEVER sends. It only creates OutreachItem
rows (status='proposed'). The single send path is `approve_send`, which calls
integrations.outlook.send_mail(user_initiated=True) and is only ever invoked by
Bo's Telegram approval tap (mirrors planner.generate_plan / approve_item). `skip`
commits nothing. Dropped candidates (no confident email, over cap, deduped) are
counted + reasoned in the summary — never silently lost.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import select

from db import session_scope
from models import OutreachItem

BATCH_CAP = 8
DAILY_SEND_CAP = 10
DEFAULT_TRACKS = ("swe", "finance")


def _dedup_key(email: str, domain: Optional[str]) -> str:
    return f"{(email or '').strip().lower()}|{(domain or '').strip().lower()}"


def discover(criteria: str = "") -> list[dict]:
    """Candidate AI startups per track (Toronto/remote). Returns
    [{company, domain, why_fit, track}]. Deterministic seed list for now; the
    live web-research variant slots in here later without changing callers."""
    seed = [
        {"company": "Cohere", "domain": "cohere.com", "why_fit": "Toronto LLM lab", "track": "swe"},
        {"company": "Waabi", "domain": "waabi.ai", "why_fit": "Toronto self-driving AI", "track": "swe"},
        {"company": "Borealis AI", "domain": "borealisai.com", "why_fit": "AI in finance research", "track": "finance"},
        {"company": "Wealthsimple", "domain": "wealthsimple.com", "why_fit": "fintech, AI features", "track": "finance"},
    ]
    return seed[:BATCH_CAP]


async def draft_email(candidate: dict, contact: dict) -> dict:
    """Have the applier agent draft a subject + body for one target. Returns
    {subject, body}. Text-only — no send. Falls back to a deterministic draft if
    the agent CLI yields nothing (hermetic tests stub this entirely)."""
    from agents.runner_v2 import run_agent_task

    prompt = (
        f"Draft a cold internship email.\n"
        f"Company: {candidate['company']}\nDomain: {candidate.get('domain')}\n"
        f"Why it fits Bo: {candidate.get('why_fit')}\nTrack: {candidate['track']}\n"
        f"Contact: {contact.get('name') or 'hiring team'} <{contact['email']}>\n"
        f"Output the subject on the first line prefixed 'Subject: ', then the body."
    )
    result = await run_agent_task("applier", prompt)
    text = getattr(result, "output", "") or ""
    subject = f"Internship interest — {candidate['company']}"
    body = text.strip()
    for line in text.splitlines():
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip() or subject
            body = text.split(line, 1)[1].strip()
            break
    if not body:
        body = (f"Hi {contact.get('name') or 'there'}, I'm Bo — a business student "
                f"focused on {candidate['track']} + AI. I admire {candidate['company']}'s "
                f"work ({candidate.get('why_fit')}). Are you taking interns?")
    return {"subject": subject, "body": body}


async def run_apply(criteria: str = "", chat_id: Optional[int] = None) -> dict:
    """Discover → enrich → draft → STAGE. Never sends. Drops (no confident email,
    deduped) are counted + reasoned. Returns a batch summary."""
    from integrations import contacts

    candidates = discover(criteria)
    with session_scope() as s:
        existing = {r.dedup_key for r in s.exec(select(OutreachItem)).all()}

    item_ids: list[int] = []
    dropped = 0
    reasons: list[str] = []

    for cand in candidates:
        enr = contacts.find_contact(cand["company"], cand.get("domain", ""))
        if not enr.connected:
            dropped += 1
            reasons.append(f"{cand['company']}: {enr.error}")
            continue
        contact = enr.data
        key = _dedup_key(contact["email"], contact.get("domain"))
        if key in existing:
            dropped += 1
            reasons.append(f"{cand['company']}: dedup (already staged/sent)")
            continue
        draft = await draft_email(cand, contact)
        with session_scope() as s:
            item = OutreachItem(
                track=cand["track"], company=cand["company"],
                company_domain=cand.get("domain"), contact_name=contact.get("name"),
                contact_email=contact["email"], subject=draft["subject"],
                body=draft["body"], dedup_key=key,
            )
            s.add(item)
            s.commit()
            s.refresh(item)
            item_ids.append(item.id)
        existing.add(key)

    return {"staged": len(item_ids), "dropped": dropped,
            "item_ids": item_ids, "reasons": reasons}


def get_proposed() -> list[dict]:
    with session_scope() as s:
        rows = s.exec(
            select(OutreachItem).where(OutreachItem.status == "proposed")
            .order_by(OutreachItem.created_at)
        ).all()
        return [
            {"id": r.id, "track": r.track, "company": r.company,
             "contact_name": r.contact_name, "contact_email": r.contact_email,
             "subject": r.subject, "body": r.body}
            for r in rows
        ]


def approve_send(item_id: int) -> dict:
    """The ONLY send path. Calls outlook.send_mail(user_initiated=True) — this is
    invoked solely by Bo's Telegram approval tap. Idempotent: a non-proposed item
    is a no-op. A failed send stays 'failed' (retryable), never silently lost."""
    from integrations import outlook

    with session_scope() as s:
        item = s.get(OutreachItem, item_id)
        if not item:
            raise KeyError("outreach item not found")
        if item.status != "proposed":
            return {"status": item.status, "already_decided": True}

        res = outlook.send_mail(
            [item.contact_email], item.subject, item.body, user_initiated=True
        )
        if res.connected:
            item.status = "sent"
            item.send_via = (res.data or {}).get("via")
            item.sent_at = datetime.utcnow()
            item.error = None
        else:
            item.status = "failed"
            item.error = res.error
        s.add(item)
        s.commit()
        return {"status": item.status, "company": item.company, "error": item.error}


def skip_item(item_id: int) -> dict:
    """Mark a staged item skipped. Sends nothing."""
    with session_scope() as s:
        item = s.get(OutreachItem, item_id)
        if not item:
            raise KeyError("outreach item not found")
        if item.status == "proposed":
            item.status = "skipped"
            s.add(item)
            s.commit()
        return {"status": item.status}
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_pipeline.py -q`
  Expected: `7 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/dispatch/apply.py apps/api/tests/test_apply_pipeline.py && git commit -m "Phase 1: dispatch/apply pipeline (discover→enrich→draft→stage; staging never sends)"`

---

## Task 1.5 — Approval Card + `apply:send`/`apply:skip` callbacks + `apply:` command (`routes/telegram.py`)

The approval surface. A Card per staged item with `[Send, Skip]` buttons; `apply:send:{id}` is Bo's user-initiated tap that calls `approve_send`; `apply:skip:{id}` skips. The `apply:` command runs the pipeline in the background and posts cards. Mirrors the operator/goal callbacks + the `build:`/`goal:` command branches.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/routes/telegram.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_apply_telegram.py`

**Interfaces:**
- Consumes: `dispatch.apply.{run_apply, get_proposed, approve_send, skip_item}`, `dispatch.cards.{Card, Action, send_card}`.
- Produces:
  - `_APPLY_RE` regex matching `apply: <criteria>` and bare `apply:`.
  - `apply_card(item: dict) -> Card` (verbs `apply:send:{id}`, `apply:skip:{id}`).
  - `_handle_apply_callback(data: str, chat_id: int) -> dict`
  - routing of `action == "apply"` in `_handle_callback`.
  - the `apply:` branch in `process_update` returning `{"status": "apply_started"}`.
  - `send_apply_cards(chat_id: int) -> int` helper.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_apply_telegram.py`:

```python
"""Apply approval surface (Phase 1): the apply: command stages + cards; the
apply:send tap is the user-initiated send; apply:skip sends nothing. Mirrors
test_telegram_commands' capture fixture + the operator-callback tests."""
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


def test_apply_card_has_send_and_skip(monkeypatch):
    card = tg.apply_card({"id": 7, "track": "swe", "company": "Acme AI",
                          "contact_email": "ada@acme.ai", "subject": "S", "body": "B"})
    datas = [a.data for a in card.actions]
    assert "apply:send:7" in datas and "apply:skip:7" in datas


def test_apply_send_callback_invokes_approve_send(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "approve_send", lambda i: calls.append(i) or {"status": "sent", "company": "Acme AI"})
    res = tg._handle_apply_callback("apply:send:7", 99)
    assert res["status"] == "apply_send"
    assert calls == [7]


def test_apply_skip_callback_invokes_skip(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "skip_item", lambda i: calls.append(i) or {"status": "skipped"})
    res = tg._handle_apply_callback("apply:skip:7", 99)
    assert res["status"] == "apply_skip"
    assert calls == [7]


def test_handle_callback_routes_apply_prefix(monkeypatch, _capture):
    monkeypatch.setattr(ap, "skip_item", lambda i: {"status": "skipped"})
    res = tg._handle_callback("apply:skip:3", 99)
    assert res["status"] == "apply_skip"


def test_apply_command_stages_and_cards(monkeypatch, _capture):
    BO = 6452258223
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 1, "item_ids": [11],
                "reasons": ["X: no confident email"]}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "get_proposed", lambda: [
        {"id": 11, "track": "swe", "company": "Acme AI",
         "contact_email": "ada@acme.ai", "subject": "S", "body": "B"}])

    update = {"update_id": 1, "message": {"chat": {"id": BO}, "text": "apply: AI fintech remote"}}
    res = tg.process_update(update)
    assert res["status"] == "apply_started"
    # at least one card carried the Send button
    datas = [b["callback_data"] for m in _capture if m["reply_markup"]
             for row in m["reply_markup"]["inline_keyboard"] for b in row]
    assert "apply:send:11" in datas
    # the drop count is surfaced (no silent caps)
    assert any("1 dropped" in m["text"] or "dropped" in m["text"].lower() for m in _capture)
```

- [ ] Run it (expect FAIL — handlers/command/regex missing):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_telegram.py -q`
  Expected: `AttributeError: module 'routes.telegram' has no attribute 'apply_card'`.

- [ ] Add the regex. In `/Users/clawd/borina-mesh/apps/api/routes/telegram.py`, after the `_GOAL_RE` definition (line ~93):

```python
# "apply: <optional criteria>" → the internship cold-email pipeline (propose-only).
# Bare "apply:" uses defaults. Like build:/goal: it's exempt from the generic
# forbidden gate (it stages text; nothing is sent without Bo's approval tap).
_APPLY_RE = re.compile(r"^\s*apply\s*[:,]\s*(?P<criteria>.*)$", re.IGNORECASE | re.DOTALL)
```

- [ ] Add the card builder + callback handler + cards sender. Insert before `_run_converse` (around line 402):

```python
def apply_card(item: dict) -> "object":
    """Approval card for one staged OutreachItem: Send / Skip. apply:send:{id}
    is Bo's user-initiated send tap; apply:skip:{id} sends nothing."""
    from dispatch.cards import Card, Action

    preview = (item.get("body") or "")[:180]
    return Card(
        headline=f"{item['company']} ({item['track']})",
        lines=[
            f"To: {item.get('contact_name') or ''} <{item['contact_email']}>",
            f"Subject: {item['subject']}",
            preview,
        ],
        actions=[
            Action("Send", f"apply:send:{item['id']}"),
            Action("Skip", f"apply:skip:{item['id']}"),
        ],
        buttons_per_row=2,
    )


def send_apply_cards(chat_id: int) -> int:
    """Post one approval card per proposed OutreachItem. Returns the count."""
    from dispatch.cards import send_card
    from dispatch import apply as apply_mod

    items = apply_mod.get_proposed()
    for it in items:
        send_card(chat_id, apply_card(it))
    return len(items)


def _handle_apply_callback(data: str, chat_id: int) -> dict:
    """Apply action buttons: apply:send:{id} / apply:skip:{id}. The Send tap IS
    the user-initiated action that reaches outlook.send_mail (via approve_send).
    Only reachable for an allow-listed sender (checked in process_update)."""
    from dispatch import apply as apply_mod

    parts = data.split(":")
    verb = parts[1] if len(parts) > 1 else ""
    try:
        item_id = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return {"ok": True, "status": "apply_bad", "toast": ""}

    try:
        if verb == "send":
            res = apply_mod.approve_send(item_id)
            if res.get("already_decided"):
                return {"ok": True, "status": "apply_send", "item_id": item_id, "toast": "Already done"}
            if res.get("status") == "sent":
                msg, toast = f"Sent to {res.get('company')}.", "Sent ✓"
            else:
                msg, toast = (f"Send failed ({res.get('error')}) — kept it so you can retry."), "Failed"
            dispatcher.send_telegram_message(chat_id, format_telegram(msg))
            return {"ok": True, "status": "apply_send", "item_id": item_id, "toast": toast}
        if verb == "skip":
            res = apply_mod.skip_item(item_id)
            dispatcher.send_telegram_message(chat_id, format_telegram("Skipped."))
            return {"ok": True, "status": "apply_skip", "item_id": item_id, "toast": "Skipped"}
    except KeyError:
        return {"ok": True, "status": "apply_not_found", "toast": "Not found"}
    return {"ok": True, "status": "apply_unknown", "toast": ""}
```

- [ ] Route the `apply:` prefix in `_handle_callback`. In the verb router, add before the final `return {"ok": True, "status": "unknown_action"}`:

```python
    if action == "apply":
        return _handle_apply_callback(data, chat_id)
    return {"ok": True, "status": "unknown_action"}
```

- [ ] Add the `apply:` command branch in `process_update`. Insert after the `_GOAL_RE` branch (right after the goal `return {"ok": True, "status": "goal_started", ...}` block, before the brain commands at `# 2b3.`):

```python
    # 2b1c. Apply: internship cold-email pipeline (propose-only). Stage targets
    # and post one approval card each. Forbidden-gate exempt like build:/goal:
    # (it stages text; nothing is sent without Bo's approval tap). Runs the async
    # pipeline to completion here so the cards are posted before we return.
    am = _APPLY_RE.match(text)
    if am:
        import asyncio
        from dispatch import apply as apply_mod

        criteria = (am.group("criteria") or "").strip()
        summary = asyncio.run(apply_mod.run_apply(criteria, chat_id))
        n_cards = send_apply_cards(chat_id)
        dropped = summary.get("dropped", 0)
        tail = f" ({dropped} dropped)" if dropped else ""
        dispatcher.send_telegram_message(
            chat_id,
            format_telegram(
                f"{heard}Staged {summary.get('staged', 0)} outreach draft(s){tail}. "
                f"Approve each with Send below."
            ),
        )
        return {"ok": True, "status": "apply_started",
                "staged": summary.get("staged", 0), "cards": n_cards}
```

- [ ] Add the slash command entry to `COMMANDS` (so it autocompletes). After the `cancel` entry:

```python
    {"command": "cancel", "description": "Cancel a running job: /cancel <id>"},
    {"command": "apply", "description": "Stage internship cold emails: apply: <criteria>"},
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_telegram.py -q`
  Expected: `5 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/routes/telegram.py apps/api/tests/test_apply_telegram.py && git commit -m "Phase 1: apply: command + approval card + apply:send/apply:skip callbacks"`

---

## Task 1.6 — Weekly scheduler cron (`apply-weekly`, Mon 9:00 ET)

Register a weekly proactive batch. Mirror `register_fleet_health` exactly (Mon, ZoneInfo fallback, idempotent, in-memory tracking). The handler runs `run_apply` then posts cards to `TELEGRAM_CHAT_ID`.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/scheduler.py`
- Modify: `/Users/clawd/borina-mesh/apps/api/main.py` (call `register_apply_weekly`)
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_apply_scheduler.py`

**Interfaces:**
- Produces:
  - `async _run_apply_weekly(self) -> None`
  - `register_apply_weekly(self) -> None` — `job_id = "apply-weekly"`, cron `0 9 * * mon America/New_York`.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_apply_scheduler.py`:

```python
"""Weekly cold-email cron (Phase 1): registers apply-weekly @ Mon 9am ET,
idempotently. Mirrors register_fleet_health. The handler never sends — it stages
+ posts cards (send stays behind Bo's approval tap)."""
import pytest

from scheduler import SchedulerService


def test_register_apply_weekly_is_idempotent():
    svc = SchedulerService()
    svc.start()
    try:
        svc.register_apply_weekly()
        svc.register_apply_weekly()  # second call no-ops
        job = svc._scheduler.get_job("apply-weekly")
        assert job is not None
        assert svc.list_schedules().get("apply-weekly") == "0 9 * * mon America/New_York"
    finally:
        svc.stop()


@pytest.mark.asyncio
async def test_run_apply_weekly_stages_without_sending(monkeypatch):
    from dispatch import apply as ap
    from integrations import outlook
    from integrations.base import ok

    sent = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: sent.append(1) or ok("outlook", {"id": "x", "via": "graph"}))

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 2, "dropped": 0, "item_ids": [1, 2], "reasons": []}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "get_proposed", lambda: [])
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    svc = SchedulerService()
    await svc._run_apply_weekly()  # no chat configured → no cards, but no error
    assert sent == []  # the cron never sends
```

- [ ] Run it (expect FAIL — methods missing):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_scheduler.py -q`
  Expected: `AttributeError: 'SchedulerService' object has no attribute 'register_apply_weekly'`.

- [ ] Minimal implementation. In `/Users/clawd/borina-mesh/apps/api/scheduler.py`, add after `register_fleet_health` (after its closing block, before `_run_operator`):

```python
    async def _run_apply_weekly(self) -> None:
        """Weekly internship cold-email batch: stage drafts and post approval
        cards. NEVER sends — send stays behind Bo's approval tap."""
        try:
            import os
            from dispatch import apply as apply_mod
            summary = await apply_mod.run_apply("")
            chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if chat:
                from routes.telegram import send_apply_cards
                from dispatch import dispatcher
                from dispatch.telegram_format import format_telegram
                n = send_apply_cards(int(chat))
                dispatcher.send_telegram_message(
                    int(chat),
                    format_telegram(
                        f"Weekly applier: staged {summary.get('staged', 0)} draft(s), "
                        f"{summary.get('dropped', 0)} dropped. Approve each with Send."
                    ),
                )
                print(f"[scheduler] apply-weekly: {n} card(s)")
            else:
                print(f"[scheduler] apply-weekly: staged {summary.get('staged', 0)} (no chat configured)")
        except Exception as e:
            print(f"[scheduler] apply-weekly error: {e}")

    def register_apply_weekly(self) -> None:
        """Weekly internship cold-email batch — Mondays 09:00 ET."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        job_id = "apply-weekly"
        if self._scheduler.get_job(job_id):
            return
        try:
            trigger = CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=tz) if tz \
                else CronTrigger(day_of_week="mon", hour=14, minute=0)
            self._scheduler.add_job(self._run_apply_weekly, trigger=trigger, id=job_id, replace_existing=True)
            self._schedules["apply-weekly"] = "0 9 * * mon America/New_York"
            print("[scheduler] Registered default: apply-weekly @ Mon 9am ET")
        except Exception as e:
            print(f"[scheduler] Failed to register apply-weekly: {e}")
```

- [ ] Call it on startup. In `/Users/clawd/borina-mesh/apps/api/main.py`, after `scheduler_service.register_fleet_health()`:

```python
    scheduler_service.register_fleet_health()
    scheduler_service.register_apply_weekly()
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_scheduler.py -q`
  Expected: `2 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/scheduler.py apps/api/main.py apps/api/tests/test_apply_scheduler.py && git commit -m "Phase 1: weekly apply-weekly cron (Mon 9am ET; stages, never sends)"`

---

## Final self-review checklist

- [ ] **Safety invariant — no autonomous send.** `outlook.send_mail` refuses unless `user_initiated=True` (test_outlook: `test_send_mail_refuses_without_user_initiated`, `test_send_mail_refuses_even_when_authorized`). The pipeline never sends (test_apply_pipeline: `test_run_apply_stages_and_never_sends`, `test_no_send_regression`). The route hard-gates (test_outlook_routes: `test_send_rejects_without_user_initiated`). The weekly cron never sends (test_apply_scheduler: `test_run_apply_weekly_stages_without_sending`).
- [ ] **Only Bo's tap sends.** `apply:send:{id}` → `approve_send` → `send_mail(user_initiated=True)` exactly once, idempotent (test_apply_pipeline: `test_approve_send_is_the_only_user_initiated_path`; test_apply_telegram: `test_apply_send_callback_invokes_approve_send`). `apply:skip` sends nothing (test_apply_pipeline: `test_skip_sends_nothing`).
- [ ] **Fail-closed externals.** No Hunter key → `not_connected` (test_contacts); failed send → `failed` + retryable, never lost (test_apply_pipeline: `test_failed_send_stays_retryable`).
- [ ] **No silent caps.** Drops (no confident email, dedup) are counted + reasoned in the summary and surfaced in the command reply (test_apply_pipeline: `test_enrichment_drop_is_reported`, `test_dedup_skips_already_staged`; test_apply_telegram: `test_apply_command_stages_and_cards`).
- [ ] **No secrets in repo.** Keys via env (`HUNTER_API_KEY`, `MICROSOFT_OAUTH_*`); tokens under `~/.borina/ms_oauth_token.json` chmod-600; tests redirect the token file via `MICROSOFT_OAUTH_TOKEN_FILE` — `~/.borina` is never touched.
- [ ] **No new API key for the agent.** `applier` runs via `run_agent_task` (claude CLI); its system_prompt is resolved from the registered class.
- [ ] **No manual migration.** `OutreachItem` auto-creates via `init_db`'s `create_all`; conftest imports `models` first (test_outreach_model passes on the isolated DB).
- [ ] **Patterns mirrored, not invented.** OAuth ≙ `google_oauth.py`; route ≙ `calendar.py`; send gate ≙ `create_event`; agent ≙ `planner.py`; pipeline ≙ `planner.generate_plan`/`approve_item`; callbacks/command ≙ operator/goal + build:/goal:; cron ≙ `register_fleet_health`.
- [ ] **Wiring complete.** `routes/outlook.py` included in `main.py`; `agents.applier` imported in `main.py`; `register_apply_weekly()` called in lifespan; roster + AGENT_REGISTRY entries added.

## Final full-suite verification

- [ ] Run the entire suite and confirm green (no regressions in existing tests):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest -q`
  Expected: all tests pass (the new files add ~30 tests; the prior suite is unchanged). If any pre-existing test fails, it must fail identically on `main` before this branch — otherwise fix the regression before declaring done.
