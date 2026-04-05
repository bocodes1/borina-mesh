import pytest
from unittest.mock import AsyncMock, patch
from shared.telegram import send_summary


@pytest.mark.asyncio
async def test_send_summary_calls_bot_api(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")

    with patch("shared.telegram.Bot") as MockBot:
        mock_bot = AsyncMock()
        MockBot.return_value = mock_bot
        await send_summary("Test message")
        mock_bot.send_message.assert_called_once_with(
            chat_id="123456",
            text="Test message",
            parse_mode="Markdown",
        )


@pytest.mark.asyncio
async def test_send_summary_skips_when_no_token(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    await send_summary("Test message")
    captured = capsys.readouterr()
    assert "telegram" in captured.out.lower() or "skip" in captured.out.lower()
