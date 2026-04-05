"""Ecommerce Scout Agent — KaloData trending products + Meta Ad Library cross-reference.

Discovers high-potential dropshipping products by scraping KaloData for trending
items, cross-referencing with Meta Ad Library for competition/creative signals,
scoring and ranking them, then delivering a PDF report + Telegram summary.
"""

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import date

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_product(p: Product) -> float:
    """Weighted composite score (0-100).

    Weights:
        GMV growth       40%  (capped at 300%)
        Meta ad activity 30%  (capped at 50 creatives)
        Margin           20%  (capped at 60%)
        Competition      10%  (inverse — fewer advertisers = better, capped at 50)
    """
    # GMV growth: 0-300% → 0-100
    growth_score = min(p.gmv_growth_pct, 300.0) / 300.0 * 100.0

    # Ad activity: 0-50 creatives → 0-100
    creative_score = min(p.active_creatives, 50) / 50.0 * 100.0

    # Margin: 0-60% → 0-100
    margin_score = min(p.margin_pct, 60.0) / 60.0 * 100.0

    # Competition (inverse): fewer advertisers = higher score
    # 0 advertisers → 100, 50+ advertisers → 0
    competition_score = max(0.0, (50 - min(p.active_advertisers, 50)) / 50.0 * 100.0)

    total = (
        growth_score * 0.40
        + creative_score * 0.30
        + margin_score * 0.20
        + competition_score * 0.10
    )
    return round(total, 2)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def rank_products(products: list[Product]) -> list[Product]:
    """Return products sorted by composite score, descending."""
    return sorted(products, key=lambda p: score_product(p), reverse=True)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _viability(score: float) -> str:
    if score >= 70:
        return "HIGH"
    elif score >= 45:
        return "MEDIUM"
    return "LOW"


def format_report(products: list[Product]) -> str:
    """Full markdown report with all product details."""
    today = date.today().isoformat()
    lines = [f"# Product Discovery Report — {today}\n"]

    ranked = rank_products(products)
    for i, p in enumerate(ranked, 1):
        score = score_product(p)
        viability = _viability(score)
        lines.append(f"## {i}. {p.name}")
        lines.append(f"- **Category:** {p.category}")
        lines.append(f"- **7-day GMV:** ${p.gmv_7d:,.0f}")
        lines.append(f"- **GMV Growth:** {p.gmv_growth_pct:.1f}%")
        lines.append(f"- **Supplier Price:** ${p.supplier_price_low:.2f} – ${p.supplier_price_high:.2f}")
        lines.append(f"- **Retail Price:** ${p.retail_price_low:.2f} – ${p.retail_price_high:.2f}")
        lines.append(f"- **Margin:** {p.margin_pct:.1f}%")
        lines.append(f"- **Active Advertisers:** {p.active_advertisers}")
        lines.append(f"- **Active Creatives:** {p.active_creatives}")
        lines.append(f"- **Competition Level:** {p.competition_level}")
        if p.top_ad_description:
            lines.append(f"- **Top Ad:** {p.top_ad_description}")
        if p.supplier_links:
            links = ", ".join(p.supplier_links)
            lines.append(f"- **Suppliers:** {links}")
        lines.append(f"- **Score:** {score}/100 — **Viability: {viability}**")
        lines.append("")

    return "\n".join(lines)


def format_telegram(products: list[Product]) -> str:
    """Concise Telegram summary, top 5 products, under 1000 chars."""
    today = date.today().isoformat()
    ranked = rank_products(products)[:5]
    parts = [f"🛒 Scout Report {today}"]
    for i, p in enumerate(ranked, 1):
        score = score_product(p)
        viability = _viability(score)
        parts.append(
            f"{i}. {p.name} | {p.category} | "
            f"GMV ${p.gmv_7d / 1000:.0f}k ↑{p.gmv_growth_pct:.0f}% | "
            f"Margin {p.margin_pct:.0f}% | {viability}"
        )
    summary = "\n".join(parts)
    # Hard cap at 1000 chars
    if len(summary) > 997:
        summary = summary[:997] + "..."
    return summary


# ---------------------------------------------------------------------------
# KaloData scraping
# ---------------------------------------------------------------------------

def _parse_number(text: str) -> float:
    """Extract a numeric value from text like '$45,000' or '120%'."""
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


async def scrape_kalodata() -> list[Product]:
    """Login to kalodata.com and scrape trending products."""
    from shared.browser import create_browser, close_browser

    email = os.getenv("KALODATA_EMAIL", "")
    password = os.getenv("KALODATA_PASSWORD", "")

    if not email or not password:
        print("KaloData credentials not configured, skipping scrape")
        return []

    browser, page = await create_browser(headless=True)
    products: list[Product] = []

    try:
        # Login
        await page.goto("https://kalodata.com/login", wait_until="networkidle")
        await page.fill('input[type="email"], input[name="email"]', email)
        await page.fill('input[type="password"], input[name="password"]', password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Navigate to trending products
        await page.goto("https://kalodata.com/products/trending", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Extract product rows/cards
        rows = await page.query_selector_all(
            "table tbody tr, .product-card, [data-testid='product-row']"
        )

        for row in rows:
            try:
                cells = await row.query_selector_all("td, .cell, .field")
                if len(cells) < 5:
                    # Try card-style layout
                    name_el = await row.query_selector(
                        ".product-name, .title, h3, h4"
                    )
                    name = (await name_el.inner_text()).strip() if name_el else "Unknown"

                    cat_el = await row.query_selector(".category, .tag")
                    category = (await cat_el.inner_text()).strip() if cat_el else "General"

                    gmv_el = await row.query_selector(".gmv, .revenue")
                    gmv_text = (await gmv_el.inner_text()).strip() if gmv_el else "0"
                    gmv_7d = _parse_number(gmv_text)

                    growth_el = await row.query_selector(".growth, .change")
                    growth_text = (await growth_el.inner_text()).strip() if growth_el else "0"
                    gmv_growth_pct = _parse_number(growth_text)

                    price_el = await row.query_selector(".price, .cost")
                    price_text = (await price_el.inner_text()).strip() if price_el else "0"
                    price_val = _parse_number(price_text)
                else:
                    texts = []
                    for cell in cells:
                        texts.append((await cell.inner_text()).strip())

                    name = texts[0] if len(texts) > 0 else "Unknown"
                    category = texts[1] if len(texts) > 1 else "General"
                    gmv_7d = _parse_number(texts[2]) if len(texts) > 2 else 0
                    gmv_growth_pct = _parse_number(texts[3]) if len(texts) > 3 else 0
                    price_val = _parse_number(texts[4]) if len(texts) > 4 else 0

                # Estimate pricing
                supplier_low = price_val * 0.3
                supplier_high = price_val * 0.45
                retail_low = price_val * 0.8
                retail_high = price_val * 1.2
                margin_pct = ((retail_low - supplier_high) / retail_low * 100) if retail_low > 0 else 0

                # Image
                img_el = await row.query_selector("img")
                image_url = (await img_el.get_attribute("src")) if img_el else ""

                products.append(Product(
                    name=name,
                    category=category,
                    gmv_7d=gmv_7d,
                    gmv_growth_pct=gmv_growth_pct,
                    supplier_price_low=round(supplier_low, 2),
                    supplier_price_high=round(supplier_high, 2),
                    retail_price_low=round(retail_low, 2),
                    retail_price_high=round(retail_high, 2),
                    margin_pct=round(margin_pct, 1),
                    supplier_links=[],
                    image_url=image_url or "",
                ))
            except Exception as e:
                print(f"Error parsing product row: {e}")
                continue

    except Exception as e:
        print(f"KaloData scraping error: {e}")
    finally:
        await close_browser(browser)

    return products


# ---------------------------------------------------------------------------
# Meta Ad Library cross-reference
# ---------------------------------------------------------------------------

async def cross_reference_meta_ads(products: list[Product]) -> list[Product]:
    """Search Meta Ad Library for each product, fill in ad competition fields."""
    from shared.browser import create_browser, close_browser

    if not products:
        return products

    browser, page = await create_browser(headless=True)

    try:
        for product in products:
            try:
                search_query = product.name.replace(" ", "+")
                url = (
                    f"https://www.facebook.com/ads/library/"
                    f"?active_status=active&ad_type=all&country=US"
                    f"&q={search_query}&media_type=all"
                )
                await page.goto(url, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Count ad cards
                ad_cards = await page.query_selector_all(
                    "[class*='_7jvw'], [data-testid='ad_card'], "
                    ".x1lliihq, div[role='article']"
                )
                num_ads = len(ad_cards)

                # Estimate unique advertisers (rough: assume 3 ads per advertiser)
                product.active_creatives = num_ads
                product.active_advertisers = max(1, num_ads // 3) if num_ads > 0 else 0

                # Competition level
                if product.active_advertisers >= 20:
                    product.competition_level = "High"
                elif product.active_advertisers >= 8:
                    product.competition_level = "Medium"
                elif product.active_advertisers >= 1:
                    product.competition_level = "Low"
                else:
                    product.competition_level = "None"

                # Extract first ad description
                if ad_cards:
                    first_card = ad_cards[0]
                    desc_el = await first_card.query_selector(
                        "div[class*='_7jyr'], span, p"
                    )
                    if desc_el:
                        product.top_ad_description = (
                            (await desc_el.inner_text()).strip()[:200]
                        )

            except Exception as e:
                print(f"Meta Ad Library error for '{product.name}': {e}")
                continue

    except Exception as e:
        print(f"Meta Ad Library scraping error: {e}")
    finally:
        await close_browser(browser)

    return products


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run() -> None:
    """Full pipeline: scrape → cross-reference → rank → PDF → obsidian → telegram."""
    from shared.report import generate_pdf, get_report_dir, copy_to_obsidian
    from shared.telegram import send_summary

    print("🔍 Scraping KaloData trending products...")
    products = await scrape_kalodata()
    if not products:
        print("No products found, aborting.")
        return

    print(f"📦 Found {len(products)} products. Cross-referencing Meta Ad Library...")
    products = await cross_reference_meta_ads(products)

    print("📊 Ranking products...")
    ranked = rank_products(products)

    # Generate report
    report_md = format_report(ranked)
    report_dir = get_report_dir()
    pdf_path = report_dir / "ecommerce_scout_report.pdf"
    generate_pdf(report_md, pdf_path)
    print(f"📄 Report saved: {pdf_path}")

    # Copy to Obsidian vault
    copy_to_obsidian(pdf_path)
    print("📋 Copied to Obsidian vault.")

    # Send Telegram summary
    telegram_msg = format_telegram(ranked)
    await send_summary(telegram_msg)
    print("📱 Telegram summary sent.")

    print(f"✅ Ecommerce Scout complete — {len(ranked)} products ranked.")


if __name__ == "__main__":
    asyncio.run(run())
