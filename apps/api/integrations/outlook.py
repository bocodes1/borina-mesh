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
    http_get_json,
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


class BrowserFiller:
    """Playwright-driven application-form filler (Phase 2 — form postings).

    SAFETY: this fills name/email/resume-upload/cover/answers in Bo's logged-in
    browser and then STOPS before the final submit — Bo reviews and clicks submit
    himself (the human-submit gate). There is deliberately NO auto-submit code
    path here. Stubbed in tests; the real Playwright driver is wired in only if
    Phase 0 chose the browser transport. Unwired it fails closed (raises) so a
    misconfig never silently claims a form was filled."""

    via = "browser"

    def fill(self, posting_url: str, fields: dict, *,
             resume_path: Optional[str] = None) -> dict:
        raise RuntimeError(
            "browser form-fill not wired — set up the Playwright driver "
            "(OUTLOOK_SEND_TRANSPORT=browser) on the Mini"
        )


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
