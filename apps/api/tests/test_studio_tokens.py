"""Launch Studio button tokens: short, single use, never over 64 bytes."""
import pytest
from sqlalchemy import delete

from db import session_scope
from dispatch import studio_tokens as tokens
from models import StudioToken


@pytest.fixture(autouse=True)
def _clean():
    yield
    with session_scope() as s:
        s.exec(delete(StudioToken))
        s.commit()


def test_a_token_fits_telegram_callback_data():
    data = tokens.mint("build", {"briefsFile": "radar/briefs/2026-10-09-3.json", "briefId": "2026-10-09-3#1"})
    assert data.startswith("st:") and len(data) == 11 and len(data.encode()) <= 64


def test_peek_reads_the_payload_without_using_it():
    data = tokens.mint("answer", {"slug": "sample-desk", "stopId": "spec-1", "option": "approve"},
                       slug="sample-desk", stop_id="spec-1")
    tok = tokens.peek(data)
    assert tok["kind"] == "answer" and tok["payload"]["option"] == "approve" and tok["used"] is False


def test_a_claim_works_once():
    data = tokens.mint("skip", {"ticker": "SAMPLE"})
    assert tokens.claim(data)["payload"] == {"ticker": "SAMPLE"}
    assert tokens.claim(data) is None
    assert tokens.peek(data)["used"] is True


def test_release_lets_bo_tap_again():
    data = tokens.mint("build", {"ticker": "SAMPLE"})
    tokens.claim(data)
    tokens.release(data)
    assert tokens.claim(data) is not None


def test_retire_stop_uses_up_every_button_of_that_stop():
    a = tokens.mint("answer", {"option": "yes"}, slug="sample-desk", stop_id="cost-1")
    b = tokens.mint("confirm", {"option": "yes"}, slug="sample-desk", stop_id="cost-1")
    other = tokens.mint("answer", {"option": "a"}, slug="sample-desk", stop_id="look-1")
    assert tokens.retire_stop("sample-desk", "cost-1") == 2
    assert tokens.claim(a) is None and tokens.claim(b) is None
    assert tokens.claim(other) is not None


@pytest.mark.parametrize("data", ["", "st:", "st:zzzzzzzz", "st:0123456", "cancel:12", "st:../../x"])
def test_malformed_or_unknown_tokens_are_ignored(data):
    assert tokens.peek(data) is None and tokens.claim(data) is None


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        tokens.mint("spend", {})
