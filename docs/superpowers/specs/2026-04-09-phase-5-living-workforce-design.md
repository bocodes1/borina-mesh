# Borina Mesh Phase 5: Living Workforce

**Date:** 2026-04-09
**Status:** Scope approved, needs brainstorming + design per feature
**Priority order:** Morning Brief → Agent Memory → Inter-Agent Messaging → Live Metrics → Agent Chat Threads → Task Board → Agent Personalities

## Context

Phase 4 delivered: model tiering, QA Director, overnight workers, UI refresh. But the agents are still isolated stateless API callers. The user wants them to feel like a real workforce — communicating, learning, adapting, and delivering value you'd actually check every morning.

## Features (all approved by user)

### 1. Morning Brief Card (HOME PAGE)
CEO agent synthesizes what all agents did overnight into one actionable summary. Shows on the dashboard home page as the first thing you see. Not just a list of runs — actual insights, recommendations, blockers.

### 2. Agent Memory (PER-AGENT PERSISTENT STATE)
Each agent remembers past runs, learns what user liked/rejected, adapts over time. Stored in Obsidian vault (per-agent markdown files). Agent reads its memory before every run. QA Director feedback (approve/reject/notes) feeds back into agent memory.

### 3. Inter-Agent Messaging (AGENT-TO-AGENT COMMUNICATION)
Agents can request work from each other via a message bus. Example pipeline: Scout finds product → auto-pings Researcher to validate market → Adset estimates CAC → user gets one packaged recommendation. QA Director orchestrates multi-agent workflows.

### 4. Live Metrics Panels (NATIVE WIDGETS)
Replace iframe embeds with native dashboard widgets:
- Polymarket P&L, open positions, win rate (reads from bot API at localhost:8080)
- Ad ROAS, spend, CPA (reads from Google Ads API or agent reports)
- Product pipeline count (Scout discoveries pending review)
- Agent utilization (tokens used today, cost breakdown by model tier)

### 5. Agent Chat Threads (FULL CONVERSATION HISTORY)
Click an agent card → opens full conversation history, not just last run. Threaded view showing user prompts, agent responses, QA verdicts. Ability to continue a conversation (context carries forward).

### 6. Task Board (ASSIGN WORK TO AGENTS)
Drag-and-drop kanban: Backlog → In Progress → Review → Done. Assign tasks to specific agents. Agents pick up tasks from their queue. Progress visible on dashboard.

### 7. Agent Personalities (DISTINCT IDENTITIES)
Each agent has a name, communication style, opinions. They disagree with each other when appropriate. Personality persists across runs via agent memory. Not gimmicky — useful differentiation (Scout is aggressive on opportunities, Researcher is skeptical, Trader is risk-aware).

## Implementation Order Rationale

1. **Morning Brief** — immediate daily value, proves the system works
2. **Agent Memory** — foundation for everything else (personalities, learning, adaptation)
3. **Inter-Agent Messaging** — unlocks multi-agent pipelines
4. **Live Metrics** — makes dashboard actually useful day-to-day
5. **Chat Threads** — improves interaction quality
6. **Task Board** — project management layer
7. **Personalities** — polish layer on top of memory

## Notes

- Each feature should be its own brainstorm → spec → plan → execute cycle
- Start with Morning Brief in the next session
- Agent Memory is the critical path — blocks personalities, learning, adaptation
- Inter-Agent Messaging should reuse QA Director's dispatch mechanism
- Live Metrics needs the polymarket bot API to be working (separate fix)
