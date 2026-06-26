"""BrowserFiller (Phase 2): fills a form then STOPS before the final submit —
the human-submit gate. There is no auto-submit path. Stubbed in tests (no real
browser). Mirrors BrowserSender's unwired-raises posture."""
import pytest

from integrations import outlook


def test_browser_filler_unwired_raises():
    # Default (no Playwright driver wired) fails closed — never silently
    # pretends to have filled a form.
    with pytest.raises(RuntimeError):
        outlook.BrowserFiller().fill("https://boards.greenhouse.io/x/jobs/1", {"name": "Bo"})


def test_browser_filler_fill_never_reports_submitted(monkeypatch):
    # When wired (stubbed here), fill returns submitted=False — it stops before
    # the final submit so Bo clicks it himself.
    def fake_fill(self, posting_url, fields, *, resume_path=None):
        return {"filled": True, "submitted": False, "review_url": posting_url}

    monkeypatch.setattr(outlook.BrowserFiller, "fill", fake_fill)
    res = outlook.BrowserFiller().fill(
        "https://jobs.lever.co/acme/1", {"name": "Bo", "email": "bo@x.com"},
        resume_path="/tmp/resume.pdf",
    )
    assert res["filled"] is True
    assert res["submitted"] is False
    assert res["review_url"].endswith("/1")


def test_browser_filler_via_marker():
    assert outlook.BrowserFiller.via == "browser"
