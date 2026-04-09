import pytest
from agents.qa_director import QADirector, ReviewVerdict, _parse_verdict

@pytest.mark.asyncio
async def test_dispatch_unknown_agent_raises():
    qa = QADirector()
    with pytest.raises(ValueError, match="Unknown agent"):
        await qa.dispatch("ghost", "x")

def test_parse_approve():
    assert _parse_verdict("APPROVE").verdict == ReviewVerdict.APPROVE

def test_parse_approve_with_notes():
    r = _parse_verdict("APPROVE_WITH_NOTES: minor typo on line 3")
    assert r.verdict == ReviewVerdict.APPROVE_WITH_NOTES
    assert "typo" in r.notes

def test_parse_rerun():
    r = _parse_verdict("REQUEST_RERUN: missing citations")
    assert r.verdict == ReviewVerdict.REQUEST_RERUN
    assert "citations" in r.notes

def test_parse_block():
    r = _parse_verdict("BLOCK: hallucinated API response")
    assert r.verdict == ReviewVerdict.BLOCK

def test_parse_garbage_default_safe():
    r = _parse_verdict("¯\\_(ツ)_/¯")
    assert r.verdict == ReviewVerdict.APPROVE_WITH_NOTES


# --- Chat route: raw param ---

def test_chat_raw_bypasses_qa():
    """?raw=true should be accepted by the route without a 422."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    # Will fail with 404 (agent not found) or 500 (SDK not installed),
    # but must NOT 422 — that would mean FastAPI rejected the query param.
    r = client.post("/chat/inbox-triage?raw=true", json={"prompt": "test"})
    assert r.status_code != 422, f"Route rejected raw param: {r.text}"


def test_chat_raw_false_is_default():
    """Omitting raw= should also be accepted (defaults to False)."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.post("/chat/inbox-triage", json={"prompt": "test"})
    assert r.status_code != 422, f"Route rejected missing raw param: {r.text}"
