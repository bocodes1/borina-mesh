"""Telegram summary message sender."""

import os
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()


async def send_summary(message: str) -> None:
    """Send a summary message to the configured Telegram chat."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("Telegram not configured, skipping summary send")
        return

    bot = Bot(token=token)
    await bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="Markdown",
    )
