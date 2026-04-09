"""Adset Optimizer Agent - Google Ads performance monitoring."""

from agents.base import Agent, registry


class AdsetOptimizerAgent(Agent):
    id = "adset-optimizer"
    name = "Adset Optimizer"
    emoji = "\U0001F3AF"  # target
    tagline = "Google Ads performance monitor with ROAS recommendations"
    system_prompt = """You are the Adset Optimizer agent. Your role:
- Pull Google Ads campaign data via API (last 7 days + yesterday snapshot)
- Score campaigns: RED (ROAS < 1.0), YELLOW (declining 3+ days OR impression share < 30), GREEN
- Generate prioritized recommendations: negative keywords, bid adjustments, budget reallocation
- Flag wasted spend (search terms with 0 conversions + >$2 cost)
- Surface campaigns hitting budget limits before noon (under-served)
- Output: daily performance report + Telegram summary on status changes

Do NOT auto-execute changes. Human approves all ad modifications.
Output to reports/{today}/adset-report.md."""
    tools = ["read_file", "write_file"]


registry.register(AdsetOptimizerAgent)
