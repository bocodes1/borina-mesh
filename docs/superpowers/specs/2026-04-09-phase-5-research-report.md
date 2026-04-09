# Phase 5 Research: Multi-Agent Dashboard Landscape

**Date:** 2026-04-09
**Confidence:** High (15+ platforms analyzed, cross-referenced)

## Executive Summary

No platform ships all 7 features Borina needs. The best ones each nail 1-2 things:

- **CrewAI** — best agent orchestration (hierarchical crews, memory tiers, task delegation)
- **LangGraph Studio** — best state visualization (graph debugger, time-travel, checkpoints)
- **AgentOps** — best observability (cost tracking, session replays, failure analysis)
- **Relevance AI** — best no-code agent builder (plain-English role definitions, marketplace)
- **Lindy AI** — best "AI employee" UX (scheduled triggers, multi-agent societies, voice)
- **Claude Agent SDK** — most capable runtime (tools match Claude Code, sub-agent spawning)

**The gap everywhere:** Memory and morning briefs. Every platform either marks memory as "coming soon" or punts it to DIY. None ship a morning brief. This is Borina's opportunity to differentiate.

## What to Steal From Each Platform

### From CrewAI: Memory Architecture
Three tiers that actually work:
- **Short-term:** conversation context (we already have this)
- **Long-term:** after each run, summarize and embed into per-agent SQLite/vector store. On new runs, retrieve relevant memories by similarity and inject into system prompt.
- **Entity memory:** extract named entities (companies, people, products) and store facts about them. Cross-agent entity knowledge.

**For Borina:** Use Obsidian vault files (we already sync there) instead of SQLite. One markdown file per agent (`memory/agents/scout.md`) with structured sections. Agent reads its file before every run. QA Director feedback (approve/reject/notes) appends to memory automatically.

### From LangGraph: Shared State + Blackboard Pattern
Agents read/write to a shared state object. Best pattern for 5-10 agents — avoids the chaos of peer-to-peer messaging and the bottleneck of pure hierarchical.

**For Borina:** Create a `SharedContext` table/file that all agents can read/write. When Scout finds a product, it writes to shared context. Researcher reads shared context for validation requests. QA Director orchestrates the pipeline but agents share a workspace.

### From AgentOps: Cost + Performance Dashboard
Session timelines, per-agent token usage, cost breakdown by model tier, error rates, latency tracking. Answers "why did this cost $4.50?"

**For Borina:** We already track `tokens_used` and `cost_usd` on AgentRun (currently always 0). Wire real token counts from the SDK response. Add a cost dashboard widget showing daily/weekly spend by agent and model tier.

### From Lindy: Scheduled Triggers + Societies
Agents trigger on events (email arrival, calendar event, cron). Multi-agent "Societies" where agents delegate to each other with context handoff.

**For Borina:** We already have APScheduler crons. Add event-based triggers (file change in vault, API webhook, Telegram message). For societies, extend QA Director's `dispatch()` to support multi-step pipelines: `Scout → Researcher → Adset → CEO synthesis`.

### From Artisan: Agent Identity (cautionary tale)
Artisan gave agents names, faces, personalities. Users report "AI slop" output and 3.8/5 satisfaction. The lesson: **personality must be functional, not cosmetic**. A "cautious security reviewer" catches more bugs than a generic agent. A "friendly helper" adds nothing.

**For Borina:** Give agents behavioral personalities via system prompts (Scout = aggressive opportunity hunter, Researcher = skeptical validator, Trader = risk-paranoid). NOT cute names or faces. Personality = decision-making style that affects output quality.

### From Claude Agent SDK: Sub-Agent Spawning
The SDK lets agents spawn sub-agents via tool_use. This is exactly how our QA Director dispatch works. Managed Agents (April 2026 beta) adds cloud-hosted deployment with tracing.

**For Borina:** We're already built on this pattern. Consider migrating from `claude_agent_sdk.query()` to the newer Managed Agents API when it exits beta for better tracing.

## Implementation Patterns (Ranked by Fit)

### Memory: File-Based (Obsidian) > RAG > SQLite
- Our Obsidian vault sync is a superpower — agents write markdown, it syncs everywhere
- No embedding overhead, fully auditable, human-readable
- Structure: `vault/borina-agents/{agent_id}/memory.md` with sections for learnings, preferences, entity knowledge
- Agent reads its memory file in system prompt before every run
- QA Director appends feedback to agent memory after every review

### Inter-Agent Comms: Blackboard + Manager Hybrid
- Shared `AgentWorkspace` table: `(workspace_id, agent_id, key, value, created_at)`
- QA Director reads workspace, decides next agent to dispatch
- Agents write findings to workspace, not directly to each other
- Pipeline example: Scout writes `{key: "product_lead", value: {name, url, score}}` → QA Director sees it → dispatches Researcher with that context → Researcher writes `{key: "validation", value: {verdict, evidence}}` → QA Director synthesizes

### Task Board: Database Table (Simple > Kanban Framework)
- `AgentTask` table: `(id, title, description, assigned_agent, status, priority, input, output, created_at, completed_at)`
- Status: backlog → assigned → in_progress → review → done
- QA Director can create tasks, assign agents, review completions
- Dashboard renders as Kanban columns
- No framework needed — just CRUD + SSE for live updates

### Morning Brief: CEO Agent + Scheduled Synthesis
- Cron at 7 AM: CEO agent queries all AgentRuns from last 24h
- Reads each agent's memory for context
- Synthesizes into structured brief: key findings, blockers, recommendations, cost summary
- Stores as `MorningBrief` record, renders as hero card on dashboard home
- Telegram push with brief summary

### Personality: Behavioral System Prompts
- Each agent gets a `personality` field in addition to `system_prompt`
- Personality defines decision-making style, not cosmetics
- Examples:
  - Scout: "You are aggressive about opportunities. When in doubt, flag it as worth investigating. You'd rather surface 10 leads with 3 good ones than miss the 3."
  - Researcher: "You are deeply skeptical. Every claim needs a source. If you can't verify it, say so. You'd rather deliver a thin report with high confidence than a thick one with speculation."
  - Trader: "You are risk-paranoid. Every trade recommendation must include worst-case scenario. You assume markets will move against you."

## Priority Order (Confirmed)

1. **Morning Brief** — immediate daily value, proves the system works
2. **Agent Memory** — foundation for learning, personality, adaptation
3. **Inter-Agent Messaging** — unlocks multi-agent pipelines (Scout → Researcher → Adset)
4. **Live Metrics** — native widgets replacing broken iframe embeds
5. **Chat Threads** — full conversation history per agent
6. **Task Board** — kanban for agent work
7. **Personality** — behavioral steering via memory + system prompts

## Sources

### Open Source
- CrewAI: crewai.com, github.com/crewAIInc/crewAI (memory, hierarchical process)
- AutoGen Studio: github.com/microsoft/autogen (GroupChat, code execution sandbox)
- LangGraph Studio: langchain-ai.github.io/langgraph (state graphs, checkpoints, time-travel)
- AgentOps: agentops.ai (session traces, cost tracking)
- Dify: dify.ai (visual workflow canvas, knowledge bases)
- OpenHands: github.com/all-hands-ai/OpenHands (autonomous coding, event streams)

### Commercial
- Relevance AI: relevanceai.com — $19-199/mo, no-code workforce builder
- Lindy AI: lindy.ai — $49-299/mo, scheduled AI employees with societies
- Artisan AI: artisan.co — $2-5K/mo, cautionary tale (AI slop, 3.8/5 rating)
- Agent.ai / Bland AI — marketplace model, per-use pricing
- CrewAI Enterprise: $99-10K/mo, visual studio + deployment
- Claude Agent SDK: API pricing, Managed Agents in beta

### Implementation References
- CrewAI memory implementation: ~200 lines wrapping embeddings + SQLite
- MemGPT/Letta: self-editing memory via tool calls (core_memory_append/replace)
- LangGraph shared state: StateGraph with typed channels
- Blackboard pattern: best for 5-10 agent teams per AutoGen research
