"""Intent router (spec §8b.3 / §10b)."""
import pytest

from dispatch.intent import resolve_intent


def test_worked_example_resolves_to_researcher_finance_deepdive():
    text = ("please verify the daily report of my stocks and tell me if there's any "
            "new news surrounding my investments")
    intent = resolve_intent(text)
    assert intent.agent == "researcher"
    assert intent.task_type == "finance_deep_dive"
    assert intent.params.get("use_watchlist") is True
    assert intent.params.get("cross_check_daily_brief") is True
    assert intent.params.get("want_news") is True
    assert intent.dispatchable is True


@pytest.mark.parametrize(
    "text,expected_agent",
    [
        # Active agents route by keyword. (Parked scout/adset now fall
        # through to researcher — see test_fleet_roster.)
        ("triage my inbox please", "inbox"),
        ("how's the trading bot health", "trader"),
        ("research the new AI chip startups", "researcher"),
    ],
)
def test_alias_table(text, expected_agent):
    intent = resolve_intent(text)
    assert intent.agent == expected_agent
    assert intent.dispatchable is True


@pytest.mark.parametrize(
    "text",
    [
        "buy 100 shares of NVDA",
        "sell all my ETH now",
        "transfer $500 to my other wallet",
        "withdraw my funds",
        "delete yesterday's report",
        "reply to that email for me",
    ],
)
def test_forbidden_actions_refused(text):
    intent = resolve_intent(text)
    assert intent.forbidden is True
    assert intent.dispatchable is False
    assert intent.forbidden_reason


@pytest.mark.parametrize(
    "text",
    [
        "create a calendar event for 3pm",
        "add it to my calendar",
        "schedule a dentist appointment tomorrow",
        "put the photo shoot on my calendar",
    ],
)
def test_calendar_requests_are_not_forbidden(text):
    # Calendar adds now route to a propose-then-approve Card (the tap is the
    # user-initiated write), so they must NOT be refused outright.
    intent = resolve_intent(text)
    assert intent.forbidden is False


@pytest.mark.parametrize(
    "text",
    [
        "what's the sell-off in tech about?",
        "what happened when TSLA dropped 4% yesterday",
        "should I buy NVDA here?",
        "summarize the buy-side flow today",
        "any news on the wire transfer system outage",
        "research whether I should sell covered calls",
    ],
)
def test_readonly_questions_are_not_forbidden(text):
    # The scoped gate must stop refusing read-only questions that merely contain
    # an action word — these are the false positives Bo complained about.
    intent = resolve_intent(text)
    assert intent.forbidden is False
    assert intent.dispatchable is True


@pytest.mark.parametrize(
    "text",
    [
        "please buy 100 NVDA",
        "can you sell all my ETH",
        "go ahead and delete that event",
    ],
)
def test_polite_imperatives_still_refused(text):
    intent = resolve_intent(text)
    assert intent.forbidden is True
    assert intent.dispatchable is False


def test_unmatched_text_falls_back_to_researcher(monkeypatch):
    # No alias match + LLM declines (offline) → general-question fallback to the
    # read-only researcher, never a "rephrase" bounce (Bo's voice notes hit this).
    intent = resolve_intent("what do you think happens to yields after tomorrow")
    assert intent.agent == "researcher"
    assert intent.source == "fallback"
    assert intent.dispatchable is True


def test_forbidden_still_refused_before_fallback(monkeypatch):
    # The fallback must never swallow the forbidden gate.
    intent = resolve_intent("buy 10 NVDA for me")
    assert intent.forbidden is True
    assert intent.dispatchable is False


def test_llm_fallback_used_when_confident(monkeypatch):
    import dispatch.intent as I

    monkeypatch.setattr(
        I, "_classify_llm",
        lambda text: {"agent": "researcher", "task_type": "research", "params": {}, "confidence": 0.9},
    )
    intent = resolve_intent("ponder the meaning of quarterly filings somehow")
    assert intent.agent == "researcher" and intent.source == "llm" and intent.dispatchable
