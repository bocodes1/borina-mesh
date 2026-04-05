"""
Adset Optimizer Agent — Google Ads campaign scoring, recommendations, and reporting.
"""

import asyncio
import os
from dataclasses import dataclass, field
from typing import Optional


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
    """Score a campaign as RED, YELLOW, or GREEN.

    RED:    ROAS < 1.0
    YELLOW: declining ROAS for 3+ consecutive days OR impression_share < 30
    GREEN:  everything else
    """
    if c.roas < 1.0:
        return "RED"

    # Check for declining trend: 3+ consecutive drops
    if len(c.roas_trend) >= 3:
        consecutive_drops = 0
        for i in range(1, len(c.roas_trend)):
            if c.roas_trend[i] <= c.roas_trend[i - 1]:
                consecutive_drops += 1
            else:
                consecutive_drops = 0
            if consecutive_drops >= 3:
                return "YELLOW"

    if c.impression_share < 30:
        return "YELLOW"

    return "GREEN"


def generate_recommendations(campaigns: list[CampaignMetrics]) -> list[str]:
    """Generate actionable recommendations from campaign data."""
    recs: list[str] = []

    for c in campaigns:
        # Flag wasted spend: search terms with 0 conversions and cost > $2
        wasted_terms = [
            t for t in c.search_terms
            if t.get("conversions", 0) == 0 and t.get("cost", 0) > 2.0
        ]
        for t in wasted_terms:
            recs.append(
                f"Add negative keyword: {t['term']} "
                f"(${t['cost']:.2f} spent, 0 conversions) [{c.name}]"
            )

        # Budget increase for high ROAS + low impression share
        if c.roas >= 2.0 and c.impression_share < 60:
            recs.append(
                f"Increase budget for {c.name} — ROAS {c.roas:.1f}x "
                f"but only {c.impression_share:.0f}% impression share"
            )

        # Pause underperformers
        status = score_campaign(c)
        if status == "RED":
            recs.append(f"Pause campaign {c.name} — ROAS {c.roas:.1f}x (below breakeven)")

    return recs


def format_report(campaigns: list[CampaignMetrics], recommendations: list[str]) -> str:
    """Full markdown report with Quick Stats, per-campaign breakdown, wasted spend, and actions."""
    total_spend = sum(c.spend for c in campaigns)
    total_revenue = sum(c.revenue for c in campaigns)
    total_conversions = sum(c.conversions for c in campaigns)
    total_clicks = sum(c.clicks for c in campaigns)
    total_impressions = sum(c.impressions for c in campaigns)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0
    overall_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0

    lines: list[str] = []
    lines.append("# Ad Performance Report")
    lines.append("")

    # Quick Stats
    lines.append("## Quick Stats")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Spend | ${total_spend:.2f} |")
    lines.append(f"| Revenue | ${total_revenue:.2f} |")
    lines.append(f"| ROAS | {overall_roas:.2f}x |")
    lines.append(f"| Conversions | {total_conversions} |")
    lines.append(f"| CTR | {overall_ctr:.1f}% |")
    lines.append("")

    # Per-campaign breakdown
    lines.append("## Campaign Breakdown")
    lines.append("")
    for c in campaigns:
        status = score_campaign(c)
        emoji_map = {"GREEN": "OK", "YELLOW": "WARN", "RED": "ALERT"}
        lines.append(f"### {c.name} [{emoji_map[status]}]")
        lines.append(f"- Spend: ${c.spend:.2f} | Revenue: ${c.revenue:.2f} | ROAS: {c.roas:.1f}x")
        lines.append(f"- Clicks: {c.clicks} | CTR: {c.ctr:.1f}% | CPC: ${c.cpc:.2f} | CPA: ${c.cpa:.2f}")
        lines.append(f"- Impression Share: {c.impression_share:.0f}%")
        lines.append("")

    # Wasted spend table
    all_wasted = []
    for c in campaigns:
        for t in c.search_terms:
            if t.get("conversions", 0) == 0 and t.get("cost", 0) > 2.0:
                all_wasted.append((c.name, t))

    if all_wasted:
        lines.append("## Wasted Spend")
        lines.append("")
        lines.append("| Campaign | Search Term | Clicks | Cost | Conv |")
        lines.append("|----------|------------|--------|------|------|")
        for camp_name, t in all_wasted:
            lines.append(
                f"| {camp_name} | {t['term']} | {t['clicks']} | ${t['cost']:.2f} | {t['conversions']} |"
            )
        lines.append("")

    # Top 5 actions
    lines.append("## Top Actions")
    lines.append("")
    for i, rec in enumerate(recommendations[:5], 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

    return "\n".join(lines)


def format_telegram(
    spend: float,
    roas: float,
    conversions: int,
    status: str,
    top_action: str,
) -> str:
    """Concise Telegram summary, under 300 chars."""
    return (
        f"Ads [{status}]\n"
        f"Spend: ${spend:.2f} | ROAS: {roas:.1f}x | Conv: {conversions}\n"
        f"Action: {top_action}"
    )


def fetch_google_ads_data() -> list[CampaignMetrics]:
    """Fetch campaign metrics from Google Ads API (last 7 days + search term report).

    Requires these env vars:
      GOOGLE_ADS_DEVELOPER_TOKEN
      GOOGLE_ADS_CLIENT_ID
      GOOGLE_ADS_CLIENT_SECRET
      GOOGLE_ADS_REFRESH_TOKEN
      GOOGLE_ADS_CUSTOMER_ID
    """
    from google.ads.googleads.client import GoogleAdsClient

    credentials = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    client = GoogleAdsClient.load_from_dict(credentials)
    customer_id = os.environ["GOOGLE_ADS_CUSTOMER_ID"].replace("-", "")
    ga_service = client.get_service("GoogleAdsService")

    # --- Campaign metrics (last 7 days) ---
    campaign_query = """
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
    campaign_rows = ga_service.search(customer_id=customer_id, query=campaign_query)

    campaign_data: dict[str, dict] = {}
    for row in campaign_rows:
        name = row.campaign.name
        if name not in campaign_data:
            campaign_data[name] = {
                "spend": 0, "impressions": 0, "clicks": 0,
                "conversions": 0, "revenue": 0, "daily_roas": [],
            }
        d = campaign_data[name]
        day_spend = row.metrics.cost_micros / 1_000_000
        day_revenue = row.metrics.conversions_value
        d["spend"] += day_spend
        d["impressions"] += row.metrics.impressions
        d["clicks"] += row.metrics.clicks
        d["conversions"] += int(row.metrics.conversions)
        d["revenue"] += day_revenue
        d["daily_roas"].append(day_revenue / day_spend if day_spend > 0 else 0)
        d["ctr"] = row.metrics.ctr * 100
        d["cpc"] = row.metrics.average_cpc / 1_000_000
        d["cpa"] = row.metrics.cost_per_conversion / 1_000_000 if row.metrics.cost_per_conversion else 0
        d["impression_share"] = (row.metrics.search_impression_share or 0) * 100

    # --- Search term report ---
    search_query = """
        SELECT
            campaign.name,
            search_term_view.search_term,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions
        FROM search_term_view
        WHERE segments.date DURING LAST_7_DAYS
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """
    search_rows = ga_service.search(customer_id=customer_id, query=search_query)

    search_terms_by_campaign: dict[str, list[dict]] = {}
    for row in search_rows:
        name = row.campaign.name
        if name not in search_terms_by_campaign:
            search_terms_by_campaign[name] = []
        search_terms_by_campaign[name].append({
            "term": row.search_term_view.search_term,
            "clicks": row.metrics.clicks,
            "cost": row.metrics.cost_micros / 1_000_000,
            "conversions": int(row.metrics.conversions),
        })

    # --- Assemble CampaignMetrics ---
    results: list[CampaignMetrics] = []
    for name, d in campaign_data.items():
        spend = d["spend"]
        revenue = d["revenue"]
        roas = revenue / spend if spend > 0 else 0
        results.append(CampaignMetrics(
            name=name,
            spend=round(spend, 2),
            impressions=d["impressions"],
            clicks=d["clicks"],
            conversions=d["conversions"],
            revenue=round(revenue, 2),
            roas=round(roas, 2),
            ctr=round(d.get("ctr", 0), 2),
            cpc=round(d.get("cpc", 0), 2),
            cpa=round(d.get("cpa", 0), 2),
            impression_share=round(d.get("impression_share", 0), 1),
            spend_7d_avg=round(spend / 7, 2),
            roas_7d_avg=round(roas, 2),
            roas_trend=d["daily_roas"],
            search_terms=search_terms_by_campaign.get(name, []),
        ))

    return results


async def run():
    """Async pipeline: fetch -> score -> recommend -> report -> telegram."""
    campaigns = fetch_google_ads_data()

    for c in campaigns:
        c._status = score_campaign(c)

    recommendations = generate_recommendations(campaigns)

    total_spend = sum(c.spend for c in campaigns)
    total_revenue = sum(c.revenue for c in campaigns)
    total_conversions = sum(c.conversions for c in campaigns)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0

    # Determine overall status
    statuses = [score_campaign(c) for c in campaigns]
    if "RED" in statuses:
        overall_status = "RED"
    elif "YELLOW" in statuses:
        overall_status = "YELLOW"
    else:
        overall_status = "GREEN"

    report = format_report(campaigns, recommendations)
    top_action = recommendations[0] if recommendations else "No actions needed"
    telegram_msg = format_telegram(
        spend=total_spend,
        roas=overall_roas,
        conversions=total_conversions,
        status=overall_status,
        top_action=top_action,
    )

    # Generate PDF + copy to Obsidian
    from shared.report import generate_pdf, get_report_dir, copy_to_obsidian
    report_dir = get_report_dir()
    pdf_path = report_dir / "adset_optimizer_report.pdf"
    generate_pdf(report, pdf_path)
    copy_to_obsidian(pdf_path)

    print(f"Report saved: {pdf_path}")
    print(f"\nTelegram:\n{telegram_msg}")

    return report, telegram_msg


if __name__ == "__main__":
    asyncio.run(run())
