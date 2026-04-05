# Multi-Agent Browser Automation System — Design Spec

**Date:** 2026-04-05
**Status:** Draft
**Author:** Wenbo + Claude

---

## Problem

Three daily workflows require browser-based intelligence gathering:
1. Product discovery for branded dropshipping (KaloData + Meta Ad Library)
2. Polymarket competitive intelligence (leaderboards, whales, resolution rules)
3. Ad performance monitoring and optimization (Google Ads API)

These are currently manual, time-consuming, and inconsistent. Automating them delivers a structured daily briefing by 8 AM.

## Architecture

Three independent Python scripts, each running its own headless Playwright browser (where needed). Dispatched in parallel. Results written to Obsidian vault as PDF reports + Telegram summary.

```
agents/
├── ecommerce_scout.py        # KaloData + Meta Ad Library
├── polymarket_intel.py        # Leaderboard + whale + resolution rules
├── adset_optimizer.py         # Google Ads API
├── shared/
│   ├── browser.py             # Headless Playwright setup (stealth mode)
│   ├── report.py              # Markdown -> PDF generation
│   └── telegram.py            # Telegram summary sender
└── reports/                   # Symlinked into Obsidian vault
    └── YYYY-MM-DD/
        ├── product-ideas.pdf
        ├── polymarket-intel.pdf
        └── adset-report.pdf
```

### Why Headless Scripts (Not MCP Playwright)

Claude Code's Playwright MCP plugin controls a single shared browser. Dispatching 3 parallel agents that all use MCP Playwright would cause tab conflicts. Instead:
- Each agent script spawns its own headless `playwright` browser via the `playwright` pip package
- True parallelism, no conflicts, isolated failure domains
- The MCP browser stays available for manual oversight

## Agent 1: Ecommerce Scout

### Purpose
Daily product discovery pipeline. Surfaces 5-10 branded dropshipping opportunities.

### Data Sources
| Source | Method | What We Extract |
|--------|--------|----------------|
| KaloData (paid account) | Headless browser + login | Trending products, GMV velocity, supplier data, margin estimates |
| Meta Ad Library | Headless browser | Active ads by category, estimated spend, creative examples, launch dates |

### Scraping Flow

1. **KaloData Login** — authenticate with saved credentials (from .env)
2. **Trending Products** — navigate to trending/rising products dashboard
   - Filter: rising GMV (7-day trend), margin > 30%, not oversaturated
   - Extract: product name, category, GMV, growth rate, supplier links, price range
   - Capture: product images (screenshot or URL)
3. **Meta Ad Library Cross-Reference** — for each top product from KaloData:
   - Search Meta Ad Library for related ads
   - Filter: active ads, sorted by estimated impressions/spend
   - Extract: ad creative thumbnails, copy, landing page URLs, estimated run time
4. **Score & Rank** — rank products by composite signal:
   - KaloData GMV growth (40% weight)
   - Meta ad activity (30% weight) — more active ads = validated demand
   - Estimated margin (20% weight)
   - Competition density (10% weight, inverse — less = better)

### Output

**PDF Report** (`reports/YYYY-MM-DD/product-ideas.pdf`):
```
# Product Discovery Report — YYYY-MM-DD

## Top Picks (Ranked)

### 1. [Product Name]
- **Category:** Home & Garden
- **KaloData GMV (7d):** $45,000 (+120% WoW)
- **Estimated Margin:** 35-45%
- **Supplier Price:** $12-15 (AliExpress/1688)
- **Retail Price Range:** $35-55
- **Active Meta Ads:** 12 advertisers, 34 active creatives
- **Competition Level:** Medium (growing niche, not saturated)
- **Top Ad Creative:** [screenshot/description]
- **Branded Dropship Viability:** HIGH
- **Why:** Strong growth curve, healthy margins, proven ad spend from competitors,
  room for brand differentiation with better creative/positioning
- **Supplier Links:** [URL1], [URL2]

### 2. [Product Name]
...
```

**Telegram Summary:**
```
Daily Product Scout (YYYY-MM-DD)
5 opportunities found:
1. [Product] — $45K GMV, +120% WoW, 35% margin
2. [Product] — $32K GMV, +85% WoW, 40% margin
...
Full report in Obsidian vault.
```

## Agent 2: Polymarket Intel

### Purpose
Competitive intelligence on top traders and market opportunities. Identify strategies to implement on top of the current Signal Engine bot.

### Data Sources
| Source | Method | What We Extract |
|--------|--------|----------------|
| Polymarket.com/leaderboard | Headless browser | Top 50 traders: PnL, win rate, volume, recent trades |
| Polymarket market pages | Headless browser | Resolution rules, liquidity depth, volume trends |
| Whale wallet tracking | Headless browser (profile pages) | Large position changes, entry/exit timing |

### Scraping Flow

1. **Leaderboard Scrape** — navigate to Polymarket leaderboard
   - Extract top 50: username/address, total PnL, win rate, volume (24h/7d/30d)
   - Flag: new entrants to top 50, big PnL jumps, volume spikes
2. **Top Trader Deep Dive** — for top 10 traders:
   - Visit profile page, extract recent positions
   - Identify: which markets they're active in, position sizes, timing patterns
   - Classify trader type: HFT bot (>100 trades/day), swing trader, event specialist, arb bot
   - Note: HFT bots trade thousands/day — flag their strategies but mark as "requires latency edge, not directly implementable"
3. **Whale Movement Tracking** — maintain a watchlist of whale addresses
   - Detect position changes > $1,000
   - Track: what they bought/sold, at what price, market context
   - Flag: contrarian moves (whale buying what market is selling)
4. **Resolution Rules Scrape** — for new/active markets:
   - Extract full resolution criteria text
   - Identify ambiguity or edge cases in rules
   - Flag markets where resolution mechanics create tradeable edges
5. **Strategy Gap Analysis** — compare top trader behavior against current bot:
   - Markets they trade that bot doesn't cover
   - Sizing patterns (are they more aggressive on high-conviction?)
   - Timing (do they front-run events differently?)
   - Generate implementable recommendations (not HFT-dependent)

### Output

**PDF Report** (`reports/YYYY-MM-DD/polymarket-intel.pdf`):
```
# Polymarket Intelligence Report — YYYY-MM-DD

## Leaderboard Movers
| Rank | Trader | 24h PnL | 7d PnL | Volume | Type | Notable |
|------|--------|---------|--------|--------|------|---------|
| 1 | 0xabc... | +$12,400 | +$45K | $890K | HFT Bot | New #1, was #5 last week |
| ... |

## Whale Movements (>$1K position changes)
- 0xdef... BOUGHT $5,200 YES on "Fed Rate Cut June" at $0.42 (market avg $0.45)
  → Contrarian buy, whale has 78% historical win rate
- ...

## New Resolution Edge Opportunities
### "Will X happen by Y date?"
- **Rule ambiguity:** Definition of "happen" is vague — could resolve YES on announcement vs completion
- **Current market price:** $0.65
- **Edge:** If resolution requires only announcement, fair value is ~$0.80
- **Recommendation:** Small position YES, $5-10 max

## Strategy Recommendations (Implementable)
1. **Market gap:** Bot doesn't trade [category] — top 3 traders all active there, avg 65% WR
2. **Sizing improvement:** Top traders size 2-3x larger on resolution-edge trades vs bot's flat sizing
3. **NOT implementable (HFT-dependent):** Trader #1 makes 2,400 trades/day with <100ms latency — skip

## Your Bot vs Top 10 Comparison
| Metric | Your Bot | Top 10 Avg | Gap |
|--------|----------|------------|-----|
| Win Rate | 59.6% | 62.1% | -2.5% |
| Avg Trade Size | $2.50 | $45.00 | Scale difference |
| Markets Active | 3-5 | 12-20 | Coverage gap |
| ...
```

**Telegram Summary:**
```
Polymarket Intel (YYYY-MM-DD)
Leaderboard: 3 new top-50 entrants
Whales: 2 contrarian buys flagged (Fed Rate, ETH ETF)
Resolution edges: 1 new opportunity (ambiguous rule on X market)
Strategy gaps: 2 implementable recommendations
Full report in Obsidian.
```

## Agent 3: Adset Optimizer

### Purpose
Daily ad performance monitoring with specific optimization recommendations to maximize ROAS.

### Data Source
| Source | Method | What We Extract |
|--------|--------|----------------|
| Google Ads API | REST API (google-ads-python library) | Campaign/adgroup/ad metrics: impressions, clicks, CTR, CPC, conversions, ROAS, cost |

### Analysis Flow

1. **Pull Performance Data** — Google Ads API, last 7 days + yesterday
   - Campaign level: spend, ROAS, conversions, impression share
   - Ad group level: CTR, CPC, conversion rate
   - Search term report: what queries are triggering ads
2. **Performance Scoring** — flag issues by severity:
   - **RED (action needed today):** ROAS < 100%, CPA > 2x target, budget exhausted before noon
   - **YELLOW (monitor):** ROAS declining 3+ days, CTR dropping, impression share < 50%
   - **GREEN (working):** ROAS > target, stable or improving metrics
3. **Optimization Recommendations** — prioritized by expected ROAS impact:
   - Negative keyword additions (from search term report — irrelevant queries eating budget)
   - Bid adjustments (device, location, time-of-day based on conversion data)
   - Budget reallocation (shift spend from RED campaigns to GREEN)
   - Ad copy/creative recommendations based on CTR patterns
   - Landing page flags (high CTR but low conversion = page problem)
4. **Competitive Context** — auction insights if available:
   - Who else is bidding on your keywords
   - Impression share vs competitors
   - Position ranking trends

### Output

**PDF Report** (`reports/YYYY-MM-DD/adset-report.pdf`):
```
# Ad Performance Report — YYYY-MM-DD

## Quick Stats (Yesterday)
| Metric | Value | vs 7d Avg | Status |
|--------|-------|-----------|--------|
| Spend | CA$48.20 | CA$50.00 | Normal |
| ROAS | 2.8x | 2.4x | Improving |
| Conversions | 3 | 2.1 | Above avg |
| CPC | CA$1.85 | CA$2.10 | Improving |
| Impression Share | 42% | 38% | Growing |

## Issues (RED)
None today.

## Warnings (YELLOW)
- Campaign "CA-RCSHOPPING-1" impression share dropped to 38% — budget may be limiting reach
  → **Recommendation:** Test CA$60/day for 3 days, monitor ROAS

## What's Working (GREEN)
- Marble furniture category: 4.2x ROAS, best performing segment
- Desktop conversions: 3.5x ROAS vs mobile 1.8x
  → **Recommendation:** Increase desktop bid modifier +20%

## Top 5 Actions (Prioritized by ROAS Impact)
1. Add 8 negative keywords (saving est. CA$4.50/day in wasted spend)
2. Increase desktop bid modifier +20% (est. +0.3x ROAS)
3. Test CA$60/day budget on Shopping campaign
4. Pause "accent chairs" ad group (0 conversions, CA$35 spend in 7d)
5. Create new ad variant for marble collection (highest CVR category)

## Wasted Spend Analysis
| Search Term | Clicks | Cost | Conversions | Action |
|-------------|--------|------|-------------|--------|
| "free furniture" | 12 | CA$18 | 0 | Add as negative |
| "ikea marble table" | 8 | CA$14 | 0 | Add as negative |
| ...

## 7-Day Trend
[Daily ROAS, spend, conversions as table]
```

**Telegram Summary:**
```
Ad Performance (YYYY-MM-DD)
Spend: CA$48.20 | ROAS: 2.8x | Conversions: 3
Status: All GREEN
Top action: Add 8 negative keywords (save ~CA$4.50/day)
Full report in Obsidian.
```

## Shared Infrastructure

### `shared/browser.py`
- Headless Chromium via `playwright` pip package
- Stealth mode (playwright-stealth or equivalent) to avoid bot detection
- Configurable viewport, user-agent rotation
- Screenshot capture for evidence/reports
- Cookie persistence for authenticated sessions (KaloData, Google)

### `shared/report.py`
- Markdown generation from structured data
- Markdown-to-PDF conversion (WeasyPrint or markdown-pdf)
- Output to `reports/YYYY-MM-DD/` directory
- Symlink or copy into Obsidian vault at `~/obsidian-vault/reports/`

### `shared/telegram.py`
- Send summary messages via Telegram Bot API
- Chat ID from .env (existing Telegram integration)
- Supports markdown formatting

### Configuration (`.env`)
```
# KaloData
KALODATA_EMAIL=xxx
KALODATA_PASSWORD=xxx

# Google Ads API
GOOGLE_ADS_DEVELOPER_TOKEN=xxx
GOOGLE_ADS_CLIENT_ID=xxx
GOOGLE_ADS_CLIENT_SECRET=xxx
GOOGLE_ADS_REFRESH_TOKEN=xxx
GOOGLE_ADS_CUSTOMER_ID=xxx

# Telegram
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx

# Paths
OBSIDIAN_VAULT_PATH=~/obsidian-vault
REPORTS_DIR=./reports
```

## Dispatch Pattern

### Manual (Claude Code)
```
/dispatch-agents
```
Dispatches 3 parallel agents via `superpowers:dispatching-parallel-agents`. Each agent runs its script via Bash and reports results.

### Scheduled (Cron / Claude Code triggers)
```
# 7:30 AM ET daily
30 7 * * * cd /path/to/agents && python ecommerce_scout.py && python polymarket_intel.py && python adset_optimizer.py
```

Or via Claude Code's `/schedule` skill for managed triggers.

### On-Demand
Each agent can be run independently:
```bash
python agents/ecommerce_scout.py           # Just product discovery
python agents/polymarket_intel.py          # Just Polymarket intel
python agents/adset_optimizer.py           # Just ad performance
python agents/run_all.py                   # All 3 in parallel
```

## Dependencies

```
playwright>=1.40
playwright-stealth>=1.0
google-ads>=25.0
weasyprint>=60.0
python-telegram-bot>=20.0
python-dotenv>=1.0
```

## Error Handling

- Each agent runs independently — one failure doesn't block others
- On scraping failure (site layout change, auth expired): log error, send Telegram alert, skip that section
- On API failure (Google Ads rate limit, network): retry 3x with backoff, then alert
- Reports are timestamped — missing sections are noted, not silently skipped

## Success Criteria

1. All 3 agents produce useful reports within 15 minutes total
2. Product ideas are actionable (not generic "trending on TikTok" noise)
3. Polymarket intel identifies at least 1 implementable strategy improvement per week
4. Ad optimizer catches wasted spend that manual review would miss
5. Reports land in Obsidian vault as PDFs before 8 AM daily

## Out of Scope (v1)

- Auto-executing ad changes (v1 recommends, human decides)
- Auto-trading based on whale signals (v1 surfaces intel, human decides)
- Real-time monitoring (v1 is daily batch)
- Multi-platform ad support beyond Google Ads (Meta Ads can be added in v2)
