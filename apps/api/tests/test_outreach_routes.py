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
