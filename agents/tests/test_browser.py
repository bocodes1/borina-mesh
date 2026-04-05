import pytest
import asyncio
import socket
from shared.browser import create_browser, close_browser


def _has_network() -> bool:
    """Return True if external DNS is reachable."""
    try:
        socket.setdefaulttimeout(2)
        socket.getaddrinfo("example.com", 80)
        return True
    except OSError:
        return False


requires_network = pytest.mark.skipif(
    not _has_network(),
    reason="No external network access in this environment",
)


@pytest.mark.asyncio
async def test_create_browser_returns_page():
    browser, page = await create_browser(headless=True)
    assert browser is not None
    assert page is not None
    assert page.url == "about:blank"
    await close_browser(browser)


@pytest.mark.asyncio
@requires_network
async def test_browser_can_navigate():
    browser, page = await create_browser(headless=True)
    await page.goto("https://example.com")
    title = await page.title()
    assert "Example" in title
    await close_browser(browser)


@pytest.mark.asyncio
@requires_network
async def test_take_screenshot(tmp_path):
    browser, page = await create_browser(headless=True)
    await page.goto("https://example.com")
    screenshot_path = tmp_path / "test.png"
    await page.screenshot(path=str(screenshot_path))
    assert screenshot_path.exists()
    assert screenshot_path.stat().st_size > 0
    await close_browser(browser)
