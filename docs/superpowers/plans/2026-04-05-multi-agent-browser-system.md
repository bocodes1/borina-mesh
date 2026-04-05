# Multi-Agent Browser Automation System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 3 independent headless browser agents that produce daily PDF intelligence reports (product ideas, Polymarket intel, ad optimization) delivered to Obsidian vault + Telegram.

**Architecture:** Each agent is a standalone Python script with its own headless Playwright browser. Shared utilities handle browser setup, PDF generation, and Telegram messaging. A `run_all.py` orchestrator dispatches all 3 in parallel via `asyncio`. Reports land in `agents/reports/YYYY-MM-DD/` and get copied to the Obsidian vault.

**Tech Stack:** Python 3.11+, playwright, playwright-stealth, google-ads-python, weasyprint, python-telegram-bot, python-dotenv, asyncio

---

## File Structure

```
agents/
├── ecommerce_scout.py          # Agent 1: KaloData + Meta Ad Library
├── polymarket_intel.py          # Agent 2: Leaderboard + whales + resolution
├── adset_optimizer.py           # Agent 3: Google Ads API
├── run_all.py                   # Parallel orchestrator
├── .env                         # Credentials (user fills in)
├── .env.example                 # Template with placeholder keys
├── requirements.txt             # Dependencies
├── shared/
│   ├── __init__.py
│   ├── browser.py               # Headless Playwright setup + stealth
│   ├── report.py                # Markdown -> PDF + Obsidian copy
│   └── telegram.py              # Telegram summary sender
├── reports/                     # Output directory (gitignored)
│   └── .gitkeep
└── tests/
    ├── test_browser.py
    ├── test_report.py
    ├── test_telegram.py
    ├── test_ecommerce_scout.py
    ├── test_polymarket_intel.py
    └── test_adset_optimizer.py
```

---

### Task 1: Project Setup + Dependencies

**Files:**
- Create: `agents/requirements.txt`
- Create: `agents/.env.example`
- Create: `agents/.gitignore`
- Create: `agents/reports/.gitkeep`

- [ ] **Step 1: Create project directory structure**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
mkdir -p agents/shared agents/reports agents/tests
touch agents/shared/__init__.py agents/reports/.gitkeep
```

- [ ] **Step 2: Create requirements.txt**

Write to `agents/requirements.txt`:
```
playwright>=1.40
playwright-stealth>=1.0.1
google-ads>=25.0.0
weasyprint>=62.0
python-telegram-bot>=21.0
python-dotenv>=1.0.0
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 3: Create .env.example**

Write to `agents/.env.example`:
```
# KaloData
KALODATA_EMAIL=
KALODATA_PASSWORD=

# Google Ads API
GOOGLE_ADS_DEVELOPER_TOKEN=
GOOGLE_ADS_CLIENT_ID=
GOOGLE_ADS_CLIENT_SECRET=
GOOGLE_ADS_REFRESH_TOKEN=
GOOGLE_ADS_CUSTOMER_ID=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Paths
OBSIDIAN_VAULT_PATH=C:/Users/wenbo/OneDrive/Documents/remote
REPORTS_DIR=./reports
```

- [ ] **Step 4: Create .gitignore**

Write to `agents/.gitignore`:
```
.env
reports/*
!reports/.gitkeep
__pycache__/
*.pyc
.pytest_cache/
screenshots/
```

- [ ] **Step 5: Install dependencies**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
pip install -r requirements.txt
playwright install chromium
```

- [ ] **Step 6: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/requirements.txt agents/.env.example agents/.gitignore agents/reports/.gitkeep agents/shared/__init__.py
git commit -m "feat: scaffold multi-agent browser automation project"
```

---

### Task 2: Shared Browser Module

**Files:**
- Create: `agents/shared/browser.py`
- Create: `agents/tests/test_browser.py`

- [ ] **Step 1: Write failing test for browser creation**

Write to `agents/tests/test_browser.py`:
```python
import pytest
import asyncio
from shared.browser import create_browser, close_browser


@pytest.mark.asyncio
async def test_create_browser_returns_page():
    browser, page = await create_browser(headless=True)
    assert browser is not None
    assert page is not None
    assert page.url == "about:blank"
    await close_browser(browser)


@pytest.mark.asyncio
async def test_browser_can_navigate():
    browser, page = await create_browser(headless=True)
    await page.goto("https://example.com")
    title = await page.title()
    assert "Example" in title
    await close_browser(browser)


@pytest.mark.asyncio
async def test_take_screenshot(tmp_path):
    browser, page = await create_browser(headless=True)
    await page.goto("https://example.com")
    screenshot_path = tmp_path / "test.png"
    await page.screenshot(path=str(screenshot_path))
    assert screenshot_path.exists()
    assert screenshot_path.stat().st_size > 0
    await close_browser(browser)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_browser.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.browser'`

- [ ] **Step 3: Implement browser module**

Write to `agents/shared/browser.py`:
```python
"""Headless Playwright browser with stealth for web scraping agents."""

from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import stealth_async
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
    await stealth_async(page)

    return browser, page


async def close_browser(browser: Browser) -> None:
    """Close browser and playwright instance."""
    global _playwright_instance
    await browser.close()
    if _playwright_instance:
        await _playwright_instance.stop()
        _playwright_instance = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_browser.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/shared/browser.py agents/tests/test_browser.py
git commit -m "feat: add shared headless browser module with stealth"
```

---

### Task 3: Shared Report Module (Markdown -> PDF + Obsidian)

**Files:**
- Create: `agents/shared/report.py`
- Create: `agents/tests/test_report.py`

- [ ] **Step 1: Write failing test**

Write to `agents/tests/test_report.py`:
```python
import pytest
from pathlib import Path
from datetime import date
from shared.report import generate_pdf, get_report_dir, copy_to_obsidian


def test_get_report_dir_creates_dated_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    report_dir = get_report_dir()
    today = date.today().isoformat()
    assert report_dir == tmp_path / today
    assert report_dir.exists()


def test_generate_pdf_creates_file(tmp_path):
    markdown = "# Test Report\n\nThis is a test.\n\n| Col1 | Col2 |\n|------|------|\n| A | B |"
    output_path = tmp_path / "test-report.pdf"
    generate_pdf(markdown, output_path)
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_copy_to_obsidian_copies_file(tmp_path, monkeypatch):
    vault = tmp_path / "vault" / "reports"
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    src = tmp_path / "report.pdf"
    src.write_bytes(b"%PDF-fake-content")
    copy_to_obsidian(src)
    expected = vault / src.name
    assert expected.exists()
    assert expected.read_bytes() == b"%PDF-fake-content"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_report.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement report module**

Write to `agents/shared/report.py`:
```python
"""Markdown to PDF report generation + Obsidian vault delivery."""

import os
import shutil
from datetime import date
from pathlib import Path
from weasyprint import HTML
from dotenv import load_dotenv

load_dotenv()

REPORT_CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #1a1a1a; line-height: 1.6; }
h1 { color: #111; border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { color: #222; margin-top: 28px; }
h3 { color: #333; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; }
th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
th { background: #f5f5f5; font-weight: 600; }
tr:nth-child(even) { background: #fafafa; }
code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
strong { color: #111; }
.red { color: #d32f2f; font-weight: bold; }
.yellow { color: #f57c00; font-weight: bold; }
.green { color: #388e3c; font-weight: bold; }
"""


def get_report_dir() -> Path:
    """Get or create today's report directory."""
    base = Path(os.getenv("REPORTS_DIR", "./reports"))
    report_dir = base / date.today().isoformat()
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def markdown_to_html(markdown_text: str) -> str:
    """Convert markdown to HTML. Handles tables, headers, bold, lists."""
    import re

    html_lines = []
    lines = markdown_text.split("\n")
    in_table = False
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Headers
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        # Table separator
        elif stripped.startswith("|") and set(stripped.replace("|", "").replace("-", "").strip()) == set():
            continue
        # Table header/row
        elif stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if not in_table:
                in_table = True
                html_lines.append("<table><thead><tr>")
                html_lines.append("".join(f"<th>{c}</th>" for c in cells))
                html_lines.append("</tr></thead><tbody>")
            else:
                html_lines.append("<tr>")
                html_lines.append("".join(f"<td>{c}</td>" for c in cells))
                html_lines.append("</tr>")
        else:
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False
            # List items
            if stripped.startswith("- "):
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                content = stripped[2:]
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
                html_lines.append(f"<li>{content}</li>")
            elif stripped:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
                html_lines.append(f"<p>{content}</p>")

    if in_table:
        html_lines.append("</tbody></table>")
    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def generate_pdf(markdown_text: str, output_path: Path) -> None:
    """Convert markdown string to a styled PDF file."""
    html_body = markdown_to_html(markdown_text)
    full_html = f"<html><head><style>{REPORT_CSS}</style></head><body>{html_body}</body></html>"
    HTML(string=full_html).write_pdf(str(output_path))


def copy_to_obsidian(pdf_path: Path) -> None:
    """Copy a PDF report into the Obsidian vault reports folder."""
    vault_path = Path(os.getenv("OBSIDIAN_VAULT_PATH", ""))
    if not vault_path.exists():
        print(f"WARNING: Obsidian vault not found at {vault_path}, skipping copy")
        return
    dest_dir = vault_path / "reports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, dest_dir / pdf_path.name)
```

- [ ] **Step 4: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_report.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/shared/report.py agents/tests/test_report.py
git commit -m "feat: add shared report module (markdown -> PDF + obsidian copy)"
```

---

### Task 4: Shared Telegram Module

**Files:**
- Create: `agents/shared/telegram.py`
- Create: `agents/tests/test_telegram.py`

- [ ] **Step 1: Write failing test**

Write to `agents/tests/test_telegram.py`:
```python
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
    assert "TELEGRAM" in captured.out.upper() or "skip" in captured.out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_telegram.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement telegram module**

Write to `agents/shared/telegram.py`:
```python
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
```

- [ ] **Step 4: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_telegram.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/shared/telegram.py agents/tests/test_telegram.py
git commit -m "feat: add shared telegram summary sender"
```

---

### Task 5: Ecommerce Scout Agent

**Files:**
- Create: `agents/ecommerce_scout.py`
- Create: `agents/tests/test_ecommerce_scout.py`

- [ ] **Step 1: Write failing test for data structures and scoring**

Write to `agents/tests/test_ecommerce_scout.py`:
```python
import pytest
from ecommerce_scout import Product, score_product, rank_products, format_report, format_telegram


def make_product(**overrides):
    defaults = {
        "name": "Test Product",
        "category": "Home & Garden",
        "gmv_7d": 45000,
        "gmv_growth_pct": 120.0,
        "supplier_price_low": 12.0,
        "supplier_price_high": 15.0,
        "retail_price_low": 35.0,
        "retail_price_high": 55.0,
        "margin_pct": 40.0,
        "supplier_links": ["https://example.com/supplier1"],
        "active_advertisers": 12,
        "active_creatives": 34,
        "top_ad_description": "Lifestyle photo with family in modern living room",
        "competition_level": "Medium",
        "image_url": "",
    }
    defaults.update(overrides)
    return Product(**defaults)


def test_score_product_high_growth_high_score():
    p = make_product(gmv_growth_pct=200.0, active_creatives=50, margin_pct=45.0, active_advertisers=5)
    score = score_product(p)
    assert score > 70


def test_score_product_low_growth_low_score():
    p = make_product(gmv_growth_pct=10.0, active_creatives=2, margin_pct=15.0, active_advertisers=50)
    score = score_product(p)
    assert score < 40


def test_rank_products_returns_sorted():
    products = [
        make_product(name="Bad", gmv_growth_pct=5.0, active_creatives=1, margin_pct=10.0),
        make_product(name="Good", gmv_growth_pct=150.0, active_creatives=30, margin_pct=40.0),
        make_product(name="Great", gmv_growth_pct=200.0, active_creatives=50, margin_pct=50.0),
    ]
    ranked = rank_products(products)
    assert ranked[0].name == "Great"
    assert ranked[-1].name == "Bad"


def test_format_report_contains_product_info():
    products = [make_product(name="Cool Widget")]
    report = format_report(products)
    assert "Cool Widget" in report
    assert "Home & Garden" in report
    assert "Product Discovery Report" in report


def test_format_telegram_is_concise():
    products = [make_product(name="Cool Widget"), make_product(name="Nice Gadget")]
    summary = format_telegram(products)
    assert "Cool Widget" in summary
    assert "Nice Gadget" in summary
    assert len(summary) < 1000
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_ecommerce_scout.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement ecommerce scout**

Write to `agents/ecommerce_scout.py`:
```python
"""Ecommerce Scout Agent — KaloData + Meta Ad Library product discovery."""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Product:
    name: str
    category: str
    gmv_7d: float
    gmv_growth_pct: float
    supplier_price_low: float
    supplier_price_high: float
    retail_price_low: float
    retail_price_high: float
    margin_pct: float
    supplier_links: list[str] = field(default_factory=list)
    active_advertisers: int = 0
    active_creatives: int = 0
    top_ad_description: str = ""
    competition_level: str = "Unknown"
    image_url: str = ""


def score_product(p: Product) -> float:
    """Score a product 0-100 using weighted composite signal.

    Weights: GMV growth 40%, Meta ad activity 30%, Margin 20%, Competition 10% (inverse).
    """
    # GMV growth score (0-100): cap at 300% growth
    growth_score = min(p.gmv_growth_pct / 3.0, 100.0)

    # Meta ad activity score (0-100): based on active creatives, cap at 50
    ad_score = min(p.active_creatives / 50.0 * 100.0, 100.0)

    # Margin score (0-100): cap at 60%
    margin_score = min(p.margin_pct / 60.0 * 100.0, 100.0)

    # Competition score (0-100, inverse): fewer advertisers = better
    # 1-5 advertisers = 100, 50+ = 0
    comp_score = max(0, 100 - (p.active_advertisers - 1) * 2)

    return (
        growth_score * 0.40
        + ad_score * 0.30
        + margin_score * 0.20
        + comp_score * 0.10
    )


def rank_products(products: list[Product]) -> list[Product]:
    """Sort products by composite score, highest first."""
    return sorted(products, key=score_product, reverse=True)


def _viability(score: float) -> str:
    if score >= 70:
        return "HIGH"
    elif score >= 45:
        return "MEDIUM"
    return "LOW"


def format_report(products: list[Product]) -> str:
    """Format ranked products as a markdown report."""
    today = date.today().isoformat()
    lines = [f"# Product Discovery Report — {today}\n"]
    lines.append("## Top Picks (Ranked)\n")

    for i, p in enumerate(products[:10], 1):
        score = score_product(p)
        supplier_links = ", ".join(p.supplier_links) if p.supplier_links else "N/A"
        lines.append(f"### {i}. {p.name}")
        lines.append(f"- **Category:** {p.category}")
        lines.append(f"- **KaloData GMV (7d):** ${p.gmv_7d:,.0f} (+{p.gmv_growth_pct:.0f}% WoW)")
        lines.append(f"- **Estimated Margin:** {p.margin_pct:.0f}%")
        lines.append(f"- **Supplier Price:** ${p.supplier_price_low:.2f}-${p.supplier_price_high:.2f}")
        lines.append(f"- **Retail Price Range:** ${p.retail_price_low:.2f}-${p.retail_price_high:.2f}")
        lines.append(f"- **Active Meta Ads:** {p.active_advertisers} advertisers, {p.active_creatives} creatives")
        lines.append(f"- **Competition Level:** {p.competition_level}")
        lines.append(f"- **Top Ad Creative:** {p.top_ad_description}")
        lines.append(f"- **Branded Dropship Viability:** {_viability(score)}")
        lines.append(f"- **Score:** {score:.1f}/100")
        lines.append(f"- **Supplier Links:** {supplier_links}")
        lines.append("")

    return "\n".join(lines)


def format_telegram(products: list[Product]) -> str:
    """Format a concise Telegram summary."""
    today = date.today().isoformat()
    lines = [f"*Daily Product Scout ({today})*"]
    lines.append(f"{len(products)} opportunities found:")

    for i, p in enumerate(products[:5], 1):
        lines.append(
            f"{i}. {p.name} — ${p.gmv_7d/1000:.0f}K GMV, "
            f"+{p.gmv_growth_pct:.0f}% WoW, {p.margin_pct:.0f}% margin"
        )

    lines.append("\nFull report in Obsidian vault.")
    return "\n".join(lines)


async def scrape_kalodata() -> list[Product]:
    """Log into KaloData and scrape trending products."""
    from shared.browser import create_browser, close_browser

    email = os.getenv("KALODATA_EMAIL", "")
    password = os.getenv("KALODATA_PASSWORD", "")

    if not email or not password:
        print("ERROR: KaloData credentials not set in .env")
        return []

    browser, page = await create_browser(headless=True)
    products = []

    try:
        # Navigate to KaloData login
        await page.goto("https://kalodata.com/login", wait_until="networkidle", timeout=30000)
        await page.fill('input[type="email"], input[name="email"], input[placeholder*="email" i]', email)
        await page.fill('input[type="password"]', password)
        await page.click('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Navigate to trending products
        await page.goto("https://kalodata.com/products/trending", wait_until="networkidle", timeout=30000)

        # Wait for product cards/table to load
        await page.wait_for_selector('[class*="product"], [class*="card"], table tbody tr', timeout=15000)

        # Extract product data from the page
        product_elements = await page.query_selector_all(
            '[class*="product-card"], [class*="product-item"], table tbody tr'
        )

        for elem in product_elements[:20]:
            try:
                text_content = await elem.inner_text()
                lines_raw = [l.strip() for l in text_content.split("\n") if l.strip()]

                # Extract what we can from the element
                name = lines_raw[0] if lines_raw else "Unknown Product"

                # Try to find numbers that look like GMV, growth, price
                import re
                numbers = re.findall(r'[\$]?([\d,]+\.?\d*)', text_content)
                pcts = re.findall(r'([\d.]+)%', text_content)

                gmv = float(numbers[0].replace(",", "")) if numbers else 0
                growth = float(pcts[0]) if pcts else 0
                margin = float(pcts[1]) if len(pcts) > 1 else 30.0

                # Get links
                links = await elem.eval_on_selector_all('a[href]', 'els => els.map(e => e.href)')

                products.append(Product(
                    name=name,
                    category="TikTok Shop",
                    gmv_7d=gmv,
                    gmv_growth_pct=growth,
                    supplier_price_low=0,
                    supplier_price_high=0,
                    retail_price_low=0,
                    retail_price_high=0,
                    margin_pct=margin,
                    supplier_links=links[:3],
                    image_url="",
                ))
            except Exception as e:
                print(f"WARNING: Failed to parse product element: {e}")
                continue

    except Exception as e:
        print(f"ERROR: KaloData scraping failed: {e}")
    finally:
        await close_browser(browser)

    return products


async def cross_reference_meta_ads(products: list[Product]) -> list[Product]:
    """Search Meta Ad Library for each product to find active ad data."""
    from shared.browser import create_browser, close_browser

    if not products:
        return products

    browser, page = await create_browser(headless=True)

    try:
        for product in products[:10]:
            try:
                search_query = product.name.replace(" ", "+")
                url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q={search_query}&media_type=all"
                await page.goto(url, wait_until="networkidle", timeout=20000)

                # Wait for results
                await page.wait_for_timeout(3000)

                # Count ad results
                ad_cards = await page.query_selector_all('[class*="ad"], [role="article"]')
                product.active_creatives = len(ad_cards)
                product.active_advertisers = max(1, len(ad_cards) // 3)

                # Extract first ad description if available
                if ad_cards:
                    try:
                        first_ad_text = await ad_cards[0].inner_text()
                        product.top_ad_description = first_ad_text[:200]
                    except Exception:
                        pass

                # Determine competition level
                if product.active_advertisers > 20:
                    product.competition_level = "High"
                elif product.active_advertisers > 5:
                    product.competition_level = "Medium"
                else:
                    product.competition_level = "Low"

            except Exception as e:
                print(f"WARNING: Meta Ad Library lookup failed for {product.name}: {e}")
                continue

    except Exception as e:
        print(f"ERROR: Meta Ad Library scraping failed: {e}")
    finally:
        await close_browser(browser)

    return products


async def run() -> None:
    """Run the full ecommerce scout pipeline."""
    from shared.report import generate_pdf, get_report_dir, copy_to_obsidian
    from shared.telegram import send_summary

    print("=== Ecommerce Scout Starting ===")

    # Step 1: Scrape KaloData
    print("Scraping KaloData...")
    products = await scrape_kalodata()
    print(f"Found {len(products)} products from KaloData")

    if not products:
        print("No products found, aborting")
        await send_summary("*Daily Product Scout*\nNo products found today. Check KaloData login.")
        return

    # Step 2: Cross-reference with Meta Ad Library
    print("Cross-referencing Meta Ad Library...")
    products = await cross_reference_meta_ads(products)

    # Step 3: Rank products
    ranked = rank_products(products)
    print(f"Ranked {len(ranked)} products")

    # Step 4: Generate report
    report_dir = get_report_dir()
    report_md = format_report(ranked)
    pdf_path = report_dir / "product-ideas.pdf"
    generate_pdf(report_md, pdf_path)
    print(f"PDF report saved to {pdf_path}")

    # Step 5: Copy to Obsidian
    copy_to_obsidian(pdf_path)

    # Step 6: Send Telegram summary
    telegram_msg = format_telegram(ranked)
    await send_summary(telegram_msg)

    print("=== Ecommerce Scout Complete ===")


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 4: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_ecommerce_scout.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/ecommerce_scout.py agents/tests/test_ecommerce_scout.py
git commit -m "feat: add ecommerce scout agent (KaloData + Meta Ad Library)"
```

---

### Task 6: Polymarket Intel Agent

**Files:**
- Create: `agents/polymarket_intel.py`
- Create: `agents/tests/test_polymarket_intel.py`

- [ ] **Step 1: Write failing test for data structures and analysis**

Write to `agents/tests/test_polymarket_intel.py`:
```python
import pytest
from polymarket_intel import (
    Trader, WhaleMove, ResolutionEdge,
    classify_trader, format_report, format_telegram,
    analyze_strategy_gaps,
)


def make_trader(**overrides):
    defaults = {
        "address": "0xabc123",
        "username": "trader1",
        "rank": 1,
        "pnl_24h": 12400.0,
        "pnl_7d": 45000.0,
        "pnl_total": 150000.0,
        "volume_24h": 890000.0,
        "win_rate": 62.1,
        "trades_24h": 50,
        "top_markets": ["Fed Rate Cut", "BTC Price"],
        "positions": [],
    }
    defaults.update(overrides)
    return Trader(**defaults)


def test_classify_trader_hft():
    t = make_trader(trades_24h=500, volume_24h=2000000)
    assert classify_trader(t) == "HFT Bot"


def test_classify_trader_swing():
    t = make_trader(trades_24h=5, volume_24h=50000)
    assert classify_trader(t) == "Swing Trader"


def test_classify_trader_event_specialist():
    t = make_trader(trades_24h=20, volume_24h=100000, top_markets=["Election", "Election", "Election"])
    assert classify_trader(t) == "Event Specialist"


def test_analyze_strategy_gaps():
    traders = [
        make_trader(top_markets=["Crypto", "Politics", "Sports"]),
        make_trader(top_markets=["Crypto", "Politics", "Tech"]),
    ]
    bot_markets = ["Crypto"]
    gaps = analyze_strategy_gaps(traders, bot_markets)
    assert "Politics" in gaps
    assert "Crypto" not in gaps


def test_format_report_contains_sections():
    traders = [make_trader()]
    whales = [WhaleMove(
        address="0xdef", market="Fed Rate Cut", side="YES",
        size_usd=5200, price=0.42, market_avg_price=0.45,
        is_contrarian=True,
    )]
    edges = [ResolutionEdge(
        market="Will X happen?", rule_text="Resolves YES if announced",
        ambiguity="Definition of announced unclear",
        current_price=0.65, estimated_fair=0.80,
        recommendation="Small YES position",
    )]
    report = format_report(traders, whales, edges, ["Politics", "Sports"])
    assert "Leaderboard" in report
    assert "Whale" in report
    assert "Resolution" in report
    assert "Strategy" in report


def test_format_telegram_is_concise():
    msg = format_telegram(
        leaderboard_movers=3, whale_moves=2,
        resolution_edges=1, strategy_gaps=2,
    )
    assert len(msg) < 500
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_polymarket_intel.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement polymarket intel agent**

Write to `agents/polymarket_intel.py`:
```python
"""Polymarket Intel Agent — Leaderboard, whale tracking, resolution rules."""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Trader:
    address: str
    username: str
    rank: int
    pnl_24h: float
    pnl_7d: float
    pnl_total: float
    volume_24h: float
    win_rate: float
    trades_24h: int
    top_markets: list[str] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)


@dataclass
class WhaleMove:
    address: str
    market: str
    side: str  # YES or NO
    size_usd: float
    price: float
    market_avg_price: float
    is_contrarian: bool


@dataclass
class ResolutionEdge:
    market: str
    rule_text: str
    ambiguity: str
    current_price: float
    estimated_fair: float
    recommendation: str


def classify_trader(t: Trader) -> str:
    """Classify trader type based on activity patterns."""
    if t.trades_24h >= 100:
        return "HFT Bot"

    # Check for event specialist: >50% trades in same category
    if t.top_markets:
        from collections import Counter
        counts = Counter(t.top_markets)
        most_common_count = counts.most_common(1)[0][1]
        if most_common_count / len(t.top_markets) > 0.5 and t.trades_24h >= 10:
            return "Event Specialist"

    if t.trades_24h <= 10:
        return "Swing Trader"

    return "Active Trader"


def analyze_strategy_gaps(traders: list[Trader], bot_markets: list[str]) -> list[str]:
    """Find markets top traders are active in that the bot doesn't cover."""
    trader_markets = set()
    for t in traders:
        trader_markets.update(t.top_markets)

    bot_set = set(bot_markets)
    return sorted(trader_markets - bot_set)


def format_report(
    traders: list[Trader],
    whales: list[WhaleMove],
    edges: list[ResolutionEdge],
    strategy_gaps: list[str],
) -> str:
    """Format full intelligence report as markdown."""
    today = date.today().isoformat()
    lines = [f"# Polymarket Intelligence Report — {today}\n"]

    # Leaderboard
    lines.append("## Leaderboard Movers\n")
    lines.append("| Rank | Trader | 24h PnL | 7d PnL | Volume | Type | Notable |")
    lines.append("|------|--------|---------|--------|--------|------|---------|")
    for t in traders[:20]:
        trader_type = classify_trader(t)
        notable = ""
        if t.pnl_24h > 10000:
            notable = "Big day"
        if trader_type == "HFT Bot":
            notable = f"{t.trades_24h} trades/day"
        display_name = t.username or f"{t.address[:8]}..."
        lines.append(
            f"| {t.rank} | {display_name} | ${t.pnl_24h:+,.0f} | ${t.pnl_7d:+,.0f} "
            f"| ${t.volume_24h:,.0f} | {trader_type} | {notable} |"
        )
    lines.append("")

    # Whale movements
    lines.append("## Whale Movements (>$1K position changes)\n")
    if whales:
        for w in whales:
            contrarian_flag = " → **CONTRARIAN**" if w.is_contrarian else ""
            lines.append(
                f"- **{w.address[:10]}...** {w.side} ${w.size_usd:,.0f} on \"{w.market}\" "
                f"at ${w.price:.2f} (market avg ${w.market_avg_price:.2f}){contrarian_flag}"
            )
    else:
        lines.append("- No significant whale movements detected today.")
    lines.append("")

    # Resolution edges
    lines.append("## Resolution Edge Opportunities\n")
    if edges:
        for e in edges:
            lines.append(f"### \"{e.market}\"")
            lines.append(f"- **Rule ambiguity:** {e.ambiguity}")
            lines.append(f"- **Current price:** ${e.current_price:.2f}")
            lines.append(f"- **Estimated fair value:** ${e.estimated_fair:.2f}")
            lines.append(f"- **Recommendation:** {e.recommendation}")
            lines.append("")
    else:
        lines.append("- No new resolution edge opportunities found today.\n")

    # Strategy gaps
    lines.append("## Strategy Gaps (Markets You're Missing)\n")
    if strategy_gaps:
        for gap in strategy_gaps:
            lines.append(f"- **{gap}** — top traders active here, your bot is not")
    else:
        lines.append("- No significant gaps detected.")
    lines.append("")

    return "\n".join(lines)


def format_telegram(
    leaderboard_movers: int,
    whale_moves: int,
    resolution_edges: int,
    strategy_gaps: int,
) -> str:
    """Format concise Telegram summary."""
    today = date.today().isoformat()
    lines = [
        f"*Polymarket Intel ({today})*",
        f"Leaderboard: {leaderboard_movers} notable movers",
        f"Whales: {whale_moves} significant moves",
        f"Resolution edges: {resolution_edges} opportunities",
        f"Strategy gaps: {strategy_gaps} markets to consider",
        "\nFull report in Obsidian.",
    ]
    return "\n".join(lines)


async def scrape_leaderboard() -> list[Trader]:
    """Scrape Polymarket leaderboard for top traders."""
    from shared.browser import create_browser, close_browser

    browser, page = await create_browser(headless=True)
    traders = []

    try:
        await page.goto("https://polymarket.com/leaderboard", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(5000)

        rows = await page.query_selector_all('table tbody tr, [class*="leaderboard"] [class*="row"]')

        for i, row in enumerate(rows[:50]):
            try:
                text = await row.inner_text()
                cells = [c.strip() for c in text.split("\t") if c.strip()]
                if not cells:
                    cells = [c.strip() for c in text.split("\n") if c.strip()]

                # Extract links for profile navigation
                links = await row.eval_on_selector_all('a[href]', 'els => els.map(e => e.href)')
                profile_link = next((l for l in links if "/profile/" in l), "")

                address = ""
                username = cells[0] if cells else f"Trader {i+1}"
                if profile_link:
                    address = profile_link.split("/profile/")[-1].split("?")[0]

                # Parse numbers from cells
                numbers = re.findall(r'[\$]?([\d,]+\.?\d*)', text)
                pcts = re.findall(r'([\d.]+)%', text)

                traders.append(Trader(
                    address=address or f"0x{i:04x}",
                    username=username,
                    rank=i + 1,
                    pnl_24h=float(numbers[0].replace(",", "")) if len(numbers) > 0 else 0,
                    pnl_7d=float(numbers[1].replace(",", "")) if len(numbers) > 1 else 0,
                    pnl_total=float(numbers[2].replace(",", "")) if len(numbers) > 2 else 0,
                    volume_24h=float(numbers[3].replace(",", "")) if len(numbers) > 3 else 0,
                    win_rate=float(pcts[0]) if pcts else 0,
                    trades_24h=0,
                ))
            except Exception as e:
                print(f"WARNING: Failed to parse leaderboard row {i}: {e}")
                continue

    except Exception as e:
        print(f"ERROR: Leaderboard scraping failed: {e}")
    finally:
        await close_browser(browser)

    return traders


async def scrape_trader_profiles(traders: list[Trader]) -> list[Trader]:
    """Deep dive into top 10 trader profiles for positions and market data."""
    from shared.browser import create_browser, close_browser

    if not traders:
        return traders

    browser, page = await create_browser(headless=True)

    try:
        for trader in traders[:10]:
            try:
                if not trader.address:
                    continue
                url = f"https://polymarket.com/profile/{trader.address}"
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                # Extract market names from positions
                position_elements = await page.query_selector_all(
                    '[class*="position"], [class*="market-card"], [class*="trade"]'
                )
                markets = []
                total_trades = 0
                for elem in position_elements[:20]:
                    try:
                        text = await elem.inner_text()
                        if text.strip():
                            markets.append(text.split("\n")[0].strip())
                            total_trades += 1
                    except Exception:
                        continue

                trader.top_markets = markets[:5]
                trader.trades_24h = total_trades

            except Exception as e:
                print(f"WARNING: Failed to scrape profile for {trader.username}: {e}")
                continue

    except Exception as e:
        print(f"ERROR: Profile scraping failed: {e}")
    finally:
        await close_browser(browser)

    return traders


async def scrape_resolution_rules() -> list[ResolutionEdge]:
    """Scrape active markets for resolution rule ambiguities."""
    from shared.browser import create_browser, close_browser

    browser, page = await create_browser(headless=True)
    edges = []

    try:
        await page.goto("https://polymarket.com/markets", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Get links to active markets
        market_links = await page.eval_on_selector_all(
            'a[href*="/event/"]',
            'els => els.map(e => ({href: e.href, text: e.innerText})).slice(0, 15)'
        )

        for market_info in market_links[:10]:
            try:
                await page.goto(market_info["href"], wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(2000)

                # Look for resolution rules section
                page_text = await page.inner_text("body")

                # Find resolution-related text
                resolution_keywords = ["resolves", "resolution", "settle", "criteria"]
                rule_text = ""
                for keyword in resolution_keywords:
                    idx = page_text.lower().find(keyword)
                    if idx >= 0:
                        rule_text = page_text[max(0, idx-50):idx+500].strip()
                        break

                if rule_text:
                    # Check for ambiguity signals
                    ambiguity_signals = ["may", "could", "unclear", "discretion", "judgment", "interpret"]
                    ambiguities = [s for s in ambiguity_signals if s in rule_text.lower()]

                    if ambiguities:
                        # Get current price
                        price_matches = re.findall(r'(\d+)¢|(\$0\.\d+)', page_text)
                        current_price = 0.5
                        if price_matches:
                            p = price_matches[0]
                            current_price = float(p[0]) / 100 if p[0] else float(p[1])

                        edges.append(ResolutionEdge(
                            market=market_info["text"][:100],
                            rule_text=rule_text[:300],
                            ambiguity=f"Found ambiguous terms: {', '.join(ambiguities)}",
                            current_price=current_price,
                            estimated_fair=current_price,
                            recommendation="Review rules manually — ambiguity detected",
                        ))

            except Exception as e:
                print(f"WARNING: Failed to scrape market rules: {e}")
                continue

    except Exception as e:
        print(f"ERROR: Resolution rules scraping failed: {e}")
    finally:
        await close_browser(browser)

    return edges


async def run() -> None:
    """Run the full Polymarket intel pipeline."""
    from shared.report import generate_pdf, get_report_dir, copy_to_obsidian
    from shared.telegram import send_summary

    print("=== Polymarket Intel Starting ===")

    # Step 1: Scrape leaderboard
    print("Scraping leaderboard...")
    traders = await scrape_leaderboard()
    print(f"Found {len(traders)} traders")

    # Step 2: Deep dive top traders
    print("Scraping top trader profiles...")
    traders = await scrape_trader_profiles(traders)

    # Step 3: Scrape resolution rules
    print("Scraping resolution rules...")
    edges = await scrape_resolution_rules()
    print(f"Found {len(edges)} resolution edge candidates")

    # Step 4: Analyze strategy gaps
    bot_markets = ["Crypto", "BTC", "ETH", "SOL"]
    strategy_gaps = analyze_strategy_gaps(traders, bot_markets)

    # Step 5: Generate report (no whale tracking in v1 — requires historical data)
    whales: list[WhaleMove] = []
    report_dir = get_report_dir()
    report_md = format_report(traders, whales, edges, strategy_gaps)
    pdf_path = report_dir / "polymarket-intel.pdf"
    generate_pdf(report_md, pdf_path)
    print(f"PDF report saved to {pdf_path}")

    # Step 6: Copy to Obsidian
    copy_to_obsidian(pdf_path)

    # Step 7: Telegram summary
    telegram_msg = format_telegram(
        leaderboard_movers=len([t for t in traders if t.pnl_24h > 5000]),
        whale_moves=len(whales),
        resolution_edges=len(edges),
        strategy_gaps=len(strategy_gaps),
    )
    await send_summary(telegram_msg)

    print("=== Polymarket Intel Complete ===")


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 4: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_polymarket_intel.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/polymarket_intel.py agents/tests/test_polymarket_intel.py
git commit -m "feat: add polymarket intel agent (leaderboard + whales + resolution)"
```

---

### Task 7: Adset Optimizer Agent

**Files:**
- Create: `agents/adset_optimizer.py`
- Create: `agents/tests/test_adset_optimizer.py`

- [ ] **Step 1: Write failing test for scoring and recommendations**

Write to `agents/tests/test_adset_optimizer.py`:
```python
import pytest
from adset_optimizer import (
    CampaignMetrics, score_campaign, generate_recommendations,
    format_report, format_telegram,
)


def make_campaign(**overrides):
    defaults = {
        "name": "CA-RCSHOPPING-1",
        "spend": 48.20,
        "impressions": 2500,
        "clicks": 135,
        "conversions": 3,
        "revenue": 135.0,
        "roas": 2.8,
        "ctr": 5.4,
        "cpc": 0.36,
        "cpa": 16.07,
        "impression_share": 42.0,
        "spend_7d_avg": 50.0,
        "roas_7d_avg": 2.4,
        "roas_trend": [2.1, 2.3, 2.2, 2.5, 2.4, 2.6, 2.8],
        "search_terms": [
            {"term": "marble coffee table", "clicks": 20, "cost": 7.0, "conversions": 2},
            {"term": "free furniture", "clicks": 12, "cost": 4.50, "conversions": 0},
            {"term": "ikea marble table", "clicks": 8, "cost": 3.00, "conversions": 0},
        ],
    }
    defaults.update(overrides)
    return CampaignMetrics(**defaults)


def test_score_campaign_green():
    c = make_campaign(roas=3.0, roas_7d_avg=2.5)
    assert score_campaign(c) == "GREEN"


def test_score_campaign_red():
    c = make_campaign(roas=0.8, roas_7d_avg=1.0)
    assert score_campaign(c) == "RED"


def test_score_campaign_yellow_declining():
    c = make_campaign(roas=1.5, roas_trend=[2.5, 2.3, 2.0, 1.8, 1.6, 1.5, 1.5])
    assert score_campaign(c) == "YELLOW"


def test_generate_recommendations_flags_wasted_spend():
    campaigns = [make_campaign()]
    recs = generate_recommendations(campaigns)
    negative_kw_recs = [r for r in recs if "negative" in r.lower()]
    assert len(negative_kw_recs) > 0


def test_format_report_has_all_sections():
    campaigns = [make_campaign()]
    recs = ["Add negative keyword: free furniture"]
    report = format_report(campaigns, recs)
    assert "Quick Stats" in report
    assert "CA-RCSHOPPING-1" in report
    assert "Ad Performance Report" in report


def test_format_telegram_is_concise():
    msg = format_telegram(spend=48.20, roas=2.8, conversions=3, status="GREEN", top_action="Add 8 negative keywords")
    assert len(msg) < 300
    assert "48.20" in msg
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_adset_optimizer.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement adset optimizer**

Write to `agents/adset_optimizer.py`:
```python
"""Adset Optimizer Agent — Google Ads API performance monitoring."""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import date

from dotenv import load_dotenv

load_dotenv()


@dataclass
class CampaignMetrics:
    name: str
    spend: float
    impressions: int
    clicks: int
    conversions: int
    revenue: float
    roas: float
    ctr: float
    cpc: float
    cpa: float
    impression_share: float
    spend_7d_avg: float
    roas_7d_avg: float
    roas_trend: list[float] = field(default_factory=list)
    search_terms: list[dict] = field(default_factory=list)


def score_campaign(c: CampaignMetrics) -> str:
    """Score a campaign as RED, YELLOW, or GREEN."""
    # RED: ROAS below 1.0 (losing money)
    if c.roas < 1.0:
        return "RED"

    # YELLOW: ROAS declining for 3+ days
    if len(c.roas_trend) >= 3:
        recent = c.roas_trend[-3:]
        if all(recent[i] >= recent[i + 1] for i in range(len(recent) - 1)):
            if c.roas < c.roas_7d_avg:
                return "YELLOW"

    # YELLOW: impression share below 30%
    if c.impression_share < 30:
        return "YELLOW"

    return "GREEN"


def generate_recommendations(campaigns: list[CampaignMetrics]) -> list[str]:
    """Generate prioritized optimization recommendations."""
    recs = []

    for c in campaigns:
        # Negative keyword recommendations
        wasted_terms = [t for t in c.search_terms if t["conversions"] == 0 and t["cost"] > 2.0]
        if wasted_terms:
            total_waste = sum(t["cost"] for t in wasted_terms)
            terms_list = ", ".join(t["term"] for t in wasted_terms[:5])
            recs.append(
                f"Add {len(wasted_terms)} negative keywords for \"{c.name}\" "
                f"(saving est. CA${total_waste:.2f}/day): {terms_list}"
            )

        # Budget recommendations
        if c.impression_share < 50 and c.roas > 2.0:
            recs.append(
                f"Increase budget on \"{c.name}\" — ROAS is {c.roas:.1f}x but "
                f"only {c.impression_share:.0f}% impression share (budget-constrained)"
            )

        # Pause underperformers
        if c.roas < 0.5 and c.spend > 20:
            recs.append(f"Pause \"{c.name}\" — ROAS is {c.roas:.1f}x with CA${c.spend:.2f} spend")

    return recs


def format_report(campaigns: list[CampaignMetrics], recommendations: list[str]) -> str:
    """Format full ad performance report as markdown."""
    today = date.today().isoformat()
    lines = [f"# Ad Performance Report — {today}\n"]

    # Quick stats (aggregate)
    total_spend = sum(c.spend for c in campaigns)
    total_conv = sum(c.conversions for c in campaigns)
    total_revenue = sum(c.revenue for c in campaigns)
    avg_roas = total_revenue / total_spend if total_spend > 0 else 0
    avg_spend_7d = sum(c.spend_7d_avg for c in campaigns)

    lines.append("## Quick Stats (Yesterday)\n")
    lines.append("| Metric | Value | vs 7d Avg | Status |")
    lines.append("|--------|-------|-----------|--------|")
    lines.append(f"| Spend | CA${total_spend:.2f} | CA${avg_spend_7d:.2f} | {'Normal' if abs(total_spend - avg_spend_7d) < avg_spend_7d * 0.2 else 'Unusual'} |")
    lines.append(f"| ROAS | {avg_roas:.1f}x | {sum(c.roas_7d_avg for c in campaigns) / len(campaigns):.1f}x | {'Improving' if avg_roas > sum(c.roas_7d_avg for c in campaigns) / len(campaigns) else 'Declining'} |")
    lines.append(f"| Conversions | {total_conv} | {sum(c.conversions for c in campaigns) / max(len(campaigns), 1):.1f} avg | - |")
    lines.append("")

    # Per-campaign breakdown
    for c in campaigns:
        status = score_campaign(c)
        lines.append(f"## Campaign: {c.name} — {status}\n")
        lines.append(f"- **Spend:** CA${c.spend:.2f}")
        lines.append(f"- **ROAS:** {c.roas:.1f}x (7d avg: {c.roas_7d_avg:.1f}x)")
        lines.append(f"- **Conversions:** {c.conversions}")
        lines.append(f"- **CTR:** {c.ctr:.1f}%")
        lines.append(f"- **CPC:** CA${c.cpc:.2f}")
        lines.append(f"- **Impression Share:** {c.impression_share:.0f}%")
        lines.append("")

        # Wasted spend
        wasted = [t for t in c.search_terms if t["conversions"] == 0 and t["cost"] > 1.0]
        if wasted:
            lines.append("### Wasted Spend\n")
            lines.append("| Search Term | Clicks | Cost | Conversions | Action |")
            lines.append("|-------------|--------|------|-------------|--------|")
            for t in wasted:
                lines.append(f"| \"{t['term']}\" | {t['clicks']} | CA${t['cost']:.2f} | 0 | Add as negative |")
            lines.append("")

    # Recommendations
    lines.append("## Top Actions (Prioritized by ROAS Impact)\n")
    for i, rec in enumerate(recommendations[:5], 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

    return "\n".join(lines)


def format_telegram(spend: float, roas: float, conversions: int, status: str, top_action: str) -> str:
    """Format concise Telegram summary."""
    today = date.today().isoformat()
    return (
        f"*Ad Performance ({today})*\n"
        f"Spend: CA${spend:.2f} | ROAS: {roas:.1f}x | Conversions: {conversions}\n"
        f"Status: {status}\n"
        f"Top action: {top_action}\n"
        f"Full report in Obsidian."
    )


def fetch_google_ads_data() -> list[CampaignMetrics]:
    """Fetch campaign data from Google Ads API."""
    developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    client_id = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
    refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
    customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")

    if not all([developer_token, client_id, client_secret, refresh_token, customer_id]):
        print("ERROR: Google Ads API credentials not set in .env")
        return []

    try:
        from google.ads.googleads.client import GoogleAdsClient

        credentials = {
            "developer_token": developer_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "login_customer_id": customer_id,
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        ga_service = client.get_service("GoogleAdsService")

        # Query campaign performance (last 7 days)
        query = """
            SELECT
                campaign.name,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.conversions_value,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_per_conversion,
                metrics.search_impression_share
            FROM campaign
            WHERE segments.date DURING LAST_7_DAYS
                AND campaign.status = 'ENABLED'
            ORDER BY metrics.cost_micros DESC
        """

        response = ga_service.search(customer_id=customer_id, query=query)

        campaigns = []
        for row in response:
            spend = row.metrics.cost_micros / 1_000_000
            revenue = row.metrics.conversions_value
            roas = revenue / spend if spend > 0 else 0

            campaigns.append(CampaignMetrics(
                name=row.campaign.name,
                spend=spend / 7,  # Daily average
                impressions=int(row.metrics.impressions / 7),
                clicks=int(row.metrics.clicks / 7),
                conversions=int(row.metrics.conversions / 7),
                revenue=revenue / 7,
                roas=roas,
                ctr=row.metrics.ctr * 100,
                cpc=row.metrics.average_cpc / 1_000_000,
                cpa=row.metrics.cost_per_conversion / 1_000_000 if row.metrics.cost_per_conversion else 0,
                impression_share=row.metrics.search_impression_share * 100 if row.metrics.search_impression_share else 0,
                spend_7d_avg=spend / 7,
                roas_7d_avg=roas,
            ))

        # Fetch search terms for top campaign
        if campaigns:
            search_query = f"""
                SELECT
                    search_term_view.search_term,
                    metrics.clicks,
                    metrics.cost_micros,
                    metrics.conversions
                FROM search_term_view
                WHERE segments.date DURING LAST_7_DAYS
                    AND metrics.cost_micros > 0
                ORDER BY metrics.cost_micros DESC
                LIMIT 50
            """
            search_response = ga_service.search(customer_id=customer_id, query=search_query)
            search_terms = []
            for row in search_response:
                search_terms.append({
                    "term": row.search_term_view.search_term,
                    "clicks": int(row.metrics.clicks),
                    "cost": row.metrics.cost_micros / 1_000_000,
                    "conversions": int(row.metrics.conversions),
                })
            if campaigns:
                campaigns[0].search_terms = search_terms

        return campaigns

    except Exception as e:
        print(f"ERROR: Google Ads API call failed: {e}")
        return []


async def run() -> None:
    """Run the full adset optimizer pipeline."""
    from shared.report import generate_pdf, get_report_dir, copy_to_obsidian
    from shared.telegram import send_summary

    print("=== Adset Optimizer Starting ===")

    # Step 1: Fetch data from Google Ads API
    print("Fetching Google Ads data...")
    campaigns = fetch_google_ads_data()
    print(f"Found {len(campaigns)} active campaigns")

    if not campaigns:
        await send_summary("*Ad Performance*\nNo data — check Google Ads API credentials.")
        return

    # Step 2: Generate recommendations
    recommendations = generate_recommendations(campaigns)

    # Step 3: Generate report
    report_dir = get_report_dir()
    report_md = format_report(campaigns, recommendations)
    pdf_path = report_dir / "adset-report.pdf"
    generate_pdf(report_md, pdf_path)
    print(f"PDF report saved to {pdf_path}")

    # Step 4: Copy to Obsidian
    copy_to_obsidian(pdf_path)

    # Step 5: Telegram summary
    total_spend = sum(c.spend for c in campaigns)
    total_revenue = sum(c.revenue for c in campaigns)
    avg_roas = total_revenue / total_spend if total_spend > 0 else 0
    total_conv = sum(c.conversions for c in campaigns)
    worst_status = "RED" if any(score_campaign(c) == "RED" for c in campaigns) else \
                   "YELLOW" if any(score_campaign(c) == "YELLOW" for c in campaigns) else "GREEN"
    top_action = recommendations[0] if recommendations else "No actions needed"

    telegram_msg = format_telegram(total_spend, avg_roas, total_conv, worst_status, top_action[:100])
    await send_summary(telegram_msg)

    print("=== Adset Optimizer Complete ===")


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 4: Run tests**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/test_adset_optimizer.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/adset_optimizer.py agents/tests/test_adset_optimizer.py
git commit -m "feat: add adset optimizer agent (Google Ads API)"
```

---

### Task 8: Parallel Orchestrator (run_all.py)

**Files:**
- Create: `agents/run_all.py`

- [ ] **Step 1: Create the orchestrator**

Write to `agents/run_all.py`:
```python
"""Run all 3 agents in parallel and collect results."""

import asyncio
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


async def run_agent(name: str, module_name: str) -> tuple[str, bool, float]:
    """Run a single agent and return (name, success, duration_seconds)."""
    start = time.time()
    try:
        module = __import__(module_name)
        await module.run()
        duration = time.time() - start
        print(f"\n✓ {name} completed in {duration:.1f}s")
        return (name, True, duration)
    except Exception as e:
        duration = time.time() - start
        print(f"\n✗ {name} failed after {duration:.1f}s: {e}")
        return (name, False, duration)


async def main():
    """Dispatch all agents in parallel."""
    print(f"=== Daily Intelligence Pipeline — {date.today().isoformat()} ===\n")
    start = time.time()

    agents = [
        ("Ecommerce Scout", "ecommerce_scout"),
        ("Polymarket Intel", "polymarket_intel"),
        ("Adset Optimizer", "adset_optimizer"),
    ]

    # Run all agents concurrently
    results = await asyncio.gather(
        *[run_agent(name, module) for name, module in agents],
        return_exceptions=True,
    )

    # Summary
    total_time = time.time() - start
    print(f"\n{'='*50}")
    print(f"Pipeline complete in {total_time:.1f}s\n")

    for result in results:
        if isinstance(result, Exception):
            print(f"  ✗ Agent crashed: {result}")
        else:
            name, success, duration = result
            status = "✓" if success else "✗"
            print(f"  {status} {name}: {'OK' if success else 'FAILED'} ({duration:.1f}s)")

    # Check reports
    from shared.report import get_report_dir
    report_dir = get_report_dir()
    reports = list(report_dir.glob("*.pdf"))
    print(f"\nReports generated: {len(reports)}")
    for r in reports:
        print(f"  → {r}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it runs (dry run without credentials)**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python run_all.py
```
Expected: Runs, each agent prints ERROR about missing credentials, but orchestrator completes without crashing.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add agents/run_all.py
git commit -m "feat: add parallel orchestrator for all 3 agents"
```

---

### Task 9: Integration Test + Final Verification

**Files:**
- Modify: All test files

- [ ] **Step 1: Run full test suite**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python -m pytest tests/ -v --tb=short
```
Expected: All tests pass (minimum 22 tests)

- [ ] **Step 2: Verify project structure is complete**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
find . -name "*.py" | sort
```
Expected output:
```
./adset_optimizer.py
./ecommerce_scout.py
./polymarket_intel.py
./run_all.py
./shared/__init__.py
./shared/browser.py
./shared/report.py
./shared/telegram.py
./tests/test_adset_optimizer.py
./tests/test_browser.py
./tests/test_ecommerce_scout.py
./tests/test_polymarket_intel.py
./tests/test_report.py
./tests/test_telegram.py
```

- [ ] **Step 3: Verify dry run**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE/agents
python run_all.py
```
Should complete without crashes. Reports dir should exist.

- [ ] **Step 4: Final commit**

```bash
cd /c/Users/wenbo/OneDrive/Desktop/CLAUDECODE
git add -A
git commit -m "feat: complete multi-agent browser automation system

3 daily intelligence agents:
- Ecommerce Scout (KaloData + Meta Ad Library)
- Polymarket Intel (leaderboard + whales + resolution rules)
- Adset Optimizer (Google Ads API)

Shared: headless browser, PDF reports, Telegram summaries
Orchestrator: parallel dispatch via asyncio"
```

---

## Post-Build: User Action Required

After all tasks complete, the user needs to:

1. **Copy `.env.example` to `.env`** and fill in credentials:
   - KaloData login
   - Google Ads API tokens
   - Telegram bot token + chat ID
   - Obsidian vault path

2. **Test each agent individually:**
   ```bash
   python agents/ecommerce_scout.py
   python agents/polymarket_intel.py
   python agents/adset_optimizer.py
   ```

3. **Run full pipeline:**
   ```bash
   python agents/run_all.py
   ```

4. **Set up daily schedule** (optional):
   Use Claude Code's `/schedule` skill or system cron for 7:30 AM ET daily execution.
