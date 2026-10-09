"""Launch Studio cards: escaped plain text, Telegram-sized, Bo's chat only."""
import re

from dispatch import studio_cards as sc
from dispatch.cards import Card, render_card

BO = 6452258223
BRIEF = {"id": "2026-10-09-3#1", "rank": 1, "name": "Sample Desk", "ticker": "SAMPLE", "lane": "A",
         "pitch": "A trading desk you can watch live.", "moneyLoop": "Desk fees buy back $SAMPLE.",
         "attention": "A live PnL board anyone can watch.",
         "larpSource": "A fictional larp - larp - the site has no app.", "bigSwing": False}
STOP = {"id": "cost-1", "slug": "sample-desk", "kind": "cost", "title": "Buy logo credits",
        "body": "Three logo options need credits.", "images": [], "video": None,
        "options": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}], "costUsd": 12.5}


def _entities_intact(text: str) -> bool:
    return re.search(r"&(?!amp;|lt;|gt;)", text) is None


def test_plain_cards_never_render_markdown_or_links():
    text, _ = render_card(Card("h", ["[claim](https://evil.example) <b>x</b> **bold** `code`"], plain=True))
    assert "<a " not in text and "<code>" not in text and "<b>x</b>" not in text
    assert "&lt;b&gt;x&lt;/b&gt;" in text and "[claim](https://evil.example)" in text


def test_other_cards_still_render_markdown():
    text, _ = render_card(Card("h", ["**bold**"]))
    assert "<b>bold</b>" in text


def test_brief_card():
    text, markup = render_card(sc.brief_card(BRIEF, "st:0000000a", "st:0000000b"))
    assert "<b>#1 Sample Desk ($SAMPLE) · lane A</b>" in text
    assert "Money loop: Desk fees buy back $SAMPLE." in text and "Larp source:" in text
    assert [b["callback_data"] for b in markup["inline_keyboard"][0]] == ["st:0000000a", "st:0000000b"]


def test_a_cost_stop_card_shows_the_amount():
    text, markup = render_card(sc.stop_card(STOP, [("Yes", "st:00000001"), ("No", "st:00000002")]))
    assert "$12.50" in text and "confirm once more" in text
    assert [b["text"] for row in markup["inline_keyboard"] for b in row] == ["Yes", "No"]


def test_the_confirm_card():
    text, markup = render_card(sc.confirm_card(STOP, "Yes", "st:00000003", "st:00000004"))
    assert "Spend $12.50?" in text
    assert [b["text"] for b in markup["inline_keyboard"][0]] == ["Confirm $12.50", "Cancel"]


def test_a_huge_hostile_stop_still_fits_telegram():
    stop = {**STOP, "body": "&" * 3000, "title": "<" * 80}
    card = sc.stop_card(stop, [("&" * 40, f"st:0000000{i}") for i in range(6)])
    text, _ = render_card(card)
    assert len(text) <= 4096 and _entities_intact(text)


def test_the_status_card_counts_waiting_stops():
    projects = [{"slug": "sample-desk", "name": "Sample Desk", "ticker": "SAMPLE", "stage": "build"}]
    text, markup = render_card(sc.status_card(projects, [STOP], "Radar: no run yet."))
    assert "Sample Desk ($SAMPLE) · sample-desk · build · 1 stop waiting" in text and "Radar: no run yet." in text
    assert markup is None


def test_bo_chat_is_the_allow_listed_chat_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(BO))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    assert sc.bo_chat() == BO
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")
    assert sc.bo_chat() is None
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "not-a-number")
    assert sc.bo_chat() is None
