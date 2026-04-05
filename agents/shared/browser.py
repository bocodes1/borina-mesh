"""Headless Playwright browser with stealth for web scraping agents."""

from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import Stealth
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

_playwright_instance = None


async def create_browser(
    headless: bool = True,
    viewport: dict | None = None,
) -> tuple[Browser, Page]:
    """Launch a stealth headless browser and return (browser, page)."""
    global _playwright_instance
    _playwright_instance = await async_playwright().start()

    browser = await _playwright_instance.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )

    context = await browser.new_context(
        viewport=viewport or {"width": 1920, "height": 1080},
        user_agent=random.choice(USER_AGENTS),
        locale="en-US",
    )

    page = await context.new_page()
    await Stealth().apply_stealth_async(page)

    return browser, page


async def close_browser(browser: Browser) -> None:
    """Close browser and playwright instance."""
    global _playwright_instance
    await browser.close()
    if _playwright_instance:
        await _playwright_instance.stop()
        _playwright_instance = None
