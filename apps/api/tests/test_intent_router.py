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
        ("what are the polymarket odds looking like today", "polymarket"),
        ("scout some winning ecommerce products", "scout"),
        ("triage my inbox please", "inbox"),
        ("how's the trading bot health", "trader"),
        ("research the new AI chip startups", "researcher"),
        ("review my adset campaign roas", "adset"),
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
        "create a calendar event for 3pm",
        "reply to that email for me",
    ],
)
def test_forbidden_actions_refused(text):
    intent = resolve_intent(text)
    assert intent.forbidden is True
    assert intent.dispatchable is False
    assert intent.forbidden_reason


def test_low_confidence_asks_to_rephrase(monkeypatch):
    # No alias match + LLM declines (offline) → clarify, not a wrong guess.
    intent = resolve_intent("zxcv qwerty asdf")
    assert intent.clarify is True
    assert intent.dispatchable is False


def test_llm_fallback_used_when_confident(monkeypatch):
    import dispatch.intent as I

    monkeypatch.setattr(
        I, "_classify_llm",
        lambda text: {"agent": "researcher", "task_type": "research", "params": {}, "confidence": 0.9},
    )
    intent = resolve_intent("ponder the meaning of quarterly filings somehow")
    assert intent.agent == "researcher" and intent.source == "llm" and intent.dispatchable
