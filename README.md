# Borina Mesh

> Multi-agent command center. One dashboard to message all your AI agents.

Borina Mesh is a unified control plane for specialized AI agents running on your own hardware. Built for running 24/7 on a Mac Mini (or any always-on machine), it gives you a premium web dashboard where you can dispatch jobs to a CEO agent, product scout, trading intel agent, and anything else you define — all powered by Claude Agent SDK.

**Designed to run while you sleep. Wake up to finished work.**

## Features

- **Agent Mesh** — Bento grid of specialized agents with live status indicators
- **Streaming Chat** — Real-time Server-Sent Events, token-by-token responses
- **Premium UI** — Dark-first design with shadcn/ui, Framer Motion, Geist font
- **Mobile Ready** — Access the dashboard from any device via Tailscale
- **Autonomous** — Cron-scheduled agent runs (Phase 2)
- **Extensible** — Add a new agent in ~30 lines of Python
- **One-Command Deploy** — `docker compose up`

## Architecture

```
              Any device (PC, phone, iPad)
                       │
                       ▼
                  Browser
                       │
                  Tailscale
                       │
              ┌────────▼────────────────┐
              │   Mac Mini (always on)  │
              │                         │
              │   Next.js Dashboard     │
              │   :3000                 │
              │           │             │
              │   FastAPI Backend       │
              │   :8000                 │
              │           │             │
              │   Claude Agent SDK      │
              │   + SQLite + APScheduler│
              └─────────────────────────┘
```

## Stack

**Backend:** Python 3.11, FastAPI, SQLModel, Claude Agent SDK, APScheduler, SSE
**Frontend:** Next.js 15, React 19, shadcn/ui, Tailwind, Framer Motion, Geist
**Deploy:** Docker Compose, Tailscale

## Quick Start

```bash
# Clone
git clone https://github.com/bocodes1/borina-mesh.git
cd borina-mesh

# Configure
cp apps/api/.env.example .env
# Edit .env — add ANTHROPIC_API_KEY

# Run
bash scripts/bootstrap.sh
```

Open **http://localhost:3000** — dashboard. API docs at **http://localhost:8000/docs**.

## Adding a New Agent

1. Create `apps/api/agents/my_agent.py`:
   ```python
   from agents.base import Agent, registry

   class MyAgent(Agent):
       id = "my-agent"
       name = "My Agent"
       emoji = "🚀"
       tagline = "What this agent does in one line"
       system_prompt = "You are..."
       tools = ["read_file", "web_fetch"]

   registry.register(MyAgent)
   ```

2. Import it in `main.py`:
   ```python
   import agents.my_agent  # noqa
   ```

3. Done. It appears in the dashboard grid.

## Phase 1 vs Phase 2

**Phase 1 (now):** Working MVP with 3 agents, chat, deploy
**Phase 2 (next):** React Flow network graph, Tremor analytics, cron UI, sound effects, animations polish
**Phase 3 (later):** More agents (Trader, Researcher, Adset Optimizer, Inbox Triage), Computer Use integration

## Development

```bash
bash scripts/dev.sh    # Runs API + Web concurrently
```

## License

MIT
