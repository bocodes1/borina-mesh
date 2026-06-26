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
