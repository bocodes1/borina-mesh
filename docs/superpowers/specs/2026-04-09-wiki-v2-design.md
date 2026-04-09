# Borina Wiki v2 — Design Spec

**Status:** Awaiting user approval before implementation.
**Goal:** A focused, high-signal knowledge vault that makes Wenbo AND the Borina agents smarter over time, without drowning in noise.

---

## Your Answers (Captured)

1. **Purpose:** All three — reference library + thinking partner (agents read it) + archive of good work
2. **Top 5 categories:** inferred from your Obsidian + Borina dashboard (confirm below)
3. **Blacklist:** confirmed — use logical judgment
4. **Who writes:** You + **one specifically-trained reviewer subagent** (nothing else)
5. **Trigger:** Fires at **end of every Claude Code terminal session** (Stop hook)
6. **Existing content:** Start fresh — nuclear delete of all 658 current pages + purge the 526-item queue
7. **Size:** No cap, but every page must be signal

---

## The Five Categories (Please Confirm or Edit)

The reviewer only approves content that fits one of these. Everything else is rejected.

### 1. Trading
Polymarket bot strategies, paper-trade results with numbers, whale wallet moves, leaderboard trader profiles, resolution-rule edges, strategy decisions with money impact, lessons from real losses/wins (e.g. "scalp exits cap at 40-50¢"). NOT "test passed" or "bot restarted."

### 2. Ecommerce
Refined Concept decisions, product scouting finds (KaloData trending items with GMV numbers), Meta Ad Library observations, Google Ads performance tuning, Shopify theme insights, competitor teardowns with specific takeaways, creative/fal.ai wins. NOT "pushed theme update."

### 3. Business Decisions
Money-impact decisions (pricing, budget allocation, ad spend shifts, strategic pivots) with rationale and expected outcome. Partnership / collaborator notes. Financial facts (revenue, cost structure). NOT "created spreadsheet."

### 4. Infrastructure Facts
Non-obvious configs that aren't recoverable from code: Tailscale IPs, API endpoints, credential file locations, cron schedules, service dependencies, "X runs on Mac Mini because Y," ports, unusual setup quirks. NOT "installed package X."

### 5. Lessons Learned
Abstracted gotchas with the pattern + fix. Things that cost real time or money to discover. Examples: "RSI needs ≥14 candle lookback," "Dicloak requires manual login, can't automate with headless browser." NOT "fixed bug in function X" (recoverable from git).

---

## Architecture

```
  Any Claude Code terminal (PC / Mac Mini / Telegram bridge / any device)
                              │
                              │ session ends
                              ▼
  ┌────────────────────────────────────────────┐
  │  Stop hook fires wiki-proposer skill       │
  │  • Reads session transcript                │
  │  • Extracts candidate facts (rule-based)   │
  │  • POSTs batch to Borina API               │
  └─────────────────┬──────────────────────────┘
                    ▼
  ┌────────────────────────────────────────────┐
  │  POST /memory/propose (Borina Mesh)        │
  │  Single endpoint, no queue drain loop      │
  └─────────────────┬──────────────────────────┘
                    ▼
  ┌────────────────────────────────────────────┐
  │  WikiReviewer (specialized subagent)       │
  │                                             │
  │  System prompt trained on:                 │
  │  • The 5 categories (above)                │
  │  • Concrete keep/reject examples from      │
  │    Wenbo's actual history (including       │
  │    the polybot-redeemer-fix rejection)     │
  │  • Decision output: JSON                   │
  │                                             │
  │  Default: REJECT                           │
  │  Model: claude-sonnet-4-6 (NOT Haiku —     │
  │          judgment quality matters more     │
  │          than speed for a single session)  │
  └─────────────────┬──────────────────────────┘
                    ▼
  ┌────────────────────────────────────────────┐
  │  Approved → write page to vault            │
  │  Rejected → log to rejected.jsonl          │
  │  Both → append to log.md                   │
  └────────────────────────────────────────────┘
```

**Key differences from v1 (what went wrong):**

| v1 (broken)                              | v2 (new)                                     |
|------------------------------------------|----------------------------------------------|
| Every agent run auto-proposed            | **Only terminal sessions propose**           |
| Generic "signal/noise" prompt            | **5 specific categories, rejection default** |
| Haiku for the reviewer (cheap + dumb)    | **Sonnet (better judgment, one-shot)**       |
| Drain loop churning 706 items            | **One batch per session, no queue growth**   |
| Curator memory = vague guidelines        | **Explicit category schemas + real examples**|
| 88% approval rate                        | **Target: <15% approval**                    |

## Reviewer Subagent — How It Gets "Trained"

No actual model training — just a carefully designed system prompt with:

1. **Category definitions** — the 5 categories above, verbatim
2. **Concrete examples** — 15-20 real examples of what belongs vs. what doesn't, pulled from your actual history:
   - ✓ "Polymarket scalp exits cap at 40-50¢, ride-winners exit strategy is correct policy" (Trading)
   - ✗ "Deleted 90-line broken _auto_redeem() function and wired proper AutoRedeemer class" (rejected — code fix recoverable from git)
   - ✓ "Mac Mini Tailscale IP is 100.116.121.128, Borina dashboard on port 3000" (Infrastructure)
   - ✗ "Phase A complete, 51/51 tests passing" (rejected — build status)
3. **Decision schema** — the reviewer MUST output JSON:
   ```json
   {
     "decision": "approve" | "reject",
     "category": "trading" | "ecommerce" | "business" | "infrastructure" | "lessons" | null,
     "reason": "one sentence",
     "page": { /* if approved: page object */ }
   }
   ```
4. **Self-improvement loop** — a small `rejected-examples.md` file in the vault that the reviewer reads BEFORE each decision. When you manually reject a page the reviewer approved, it gets added to this file. The reviewer learns from its specific mistakes over time.

## File Structure

```
$OBSIDIAN_VAULT_PATH/
├── 00-schema.md              # 5 categories definition
├── curator-memory.md         # Learned rejection examples
├── index.md                  # One-line catalog
├── trading/                  # Category 1
├── ecommerce/                # Category 2
├── business/                 # Category 3
├── infrastructure/           # Category 4
├── lessons/                  # Category 5
├── _archive/
│   └── v1-nuked-2026-04-09/  # All 658 old pages go here
└── _queue/
    └── rejected.jsonl        # Audit trail of rejections
```

Note: **no more `entities/`, `concepts/`, `decisions/`, `sources/`** — those were abstract. The 5 category directories match how you actually think about your work.

## What Changes on the Stack

**Backend (borina-mesh):**
- Replace `wiki_engine/reviewer.py` — new single-subagent reviewer with the trained prompt
- Replace `wiki_engine/mutator.py` — writes to category directories
- Update `wiki_engine/schema.py` — 5 categories instead of 4 types
- Delete: `wiki_engine/queue.py` (no more filesystem queue, direct review)
- Delete: curator agent + scheduled sweep
- `/memory/propose` now reviews synchronously and returns the decision immediately

**Frontend:** no changes — `/jobs`, `/files`, `/terminal` all still work

**Claude Code skill (`wiki-proposer`):**
- Keep the Stop hook, but change what it POSTs — now sends a batch of candidate facts, not a raw transcript
- Light rule-based pre-filter in the skill itself: strip lines matching "pushed commit," "tests passing," etc. before sending
- Reviewer gets cleaner input → better decisions

**Nuclear reset:**
- Move all of `entities/`, `concepts/`, `decisions/`, `sources/` into `_archive/v1-nuked-2026-04-09/`
- Delete the 526 pending queue items
- Fresh `index.md`, `log.md`, `curator-memory.md`

## Estimated Build Size

This is smaller than Phase A was.

- **Backend refactor:** ~6 tasks (replace reviewer, mutator, schema, routes, delete curator, nuclear reset script)
- **Frontend:** no changes needed
- **Skill update:** 1 task (smarter proposer script with pre-filter)
- **Initial bootstrap:** write the 5 category schema file + curator memory with starter examples

Total: maybe 8 tasks. Buildable in one session via subagent-driven development, ~30-45 min build time on Sonnet.

## What's Explicitly OUT of Scope

- ❌ Big-bang migration of the old vault (user said start fresh — easier to add later if needed)
- ❌ Auto-proposing from Borina agent runs (only terminal sessions)
- ❌ Scheduled sweeps / cron-driven reviewer
- ❌ Multiple specialized reviewers (one reviewer, one prompt)
- ❌ Approval queue / human-in-loop — trust the reviewer, audit via `rejected.jsonl`
- ❌ Fancy features (network graph of new pages, per-category analytics)

Adding any of these is a Phase 2 decision, not now.

---

# Before I Write the Implementation Plan, Confirm:

1. **The 5 categories** — do Trading / Ecommerce / Business / Infrastructure / Lessons match how you think about your work? Any you want to rename, merge, split, or drop?

2. **Sonnet for the reviewer** — judgment quality matters more than speed since it's one batch per session. OK with Sonnet or prefer Opus?

3. **Nuclear reset scope** — move the 658 pages to `_archive/v1-nuked-2026-04-09/` (reversible) OR delete outright (permanent)? I recommend archive so you can spot-check if anything was actually valuable.

4. **Rule-based pre-filter in the skill** — I want to drop obvious noise (lines like "pushed commit", "tests passing", "error: ", tool output traces) BEFORE sending to the reviewer. Any lines/patterns you specifically want filtered out right at the source?

5. **Rejection visibility** — when the reviewer rejects something, do you want:
   - **(a) Silent** — only written to `rejected.jsonl` audit file
   - **(b) Notified at session end** — "Reviewer rejected 5 things: [brief list]" so you can override
   - **(c) Daily digest** — morning email/Telegram summary of what got filtered

Answer any or all of these in one reply and I'll write the implementation plan for you to read before the build starts.
