# Borina Mesh: QA Director, Model Tiering, Overnight Workers, and Dashboard Refresh

**Date:** 2026-04-08
**Status:** Design approved, ready for implementation plan

## Goals

1. Stop paying the Opus tax for every agent — tier models per task complexity.
2. Introduce a **QA Director** that both *dispatches* agents and *gatekeeps* every artifact returned to the user.
3. Enable **handoff from Claude Code → borina-mesh**: when a terminal task can't finish, hand it to a borina worker that runs headless `claude -p` overnight inside a git worktree.
4. Refresh the front-page UI so agent cards look like real ops tiles, not emoji.

## Non-Goals

- No changes to the wiki engine / curator.
- No changes to scheduler cron timings (only what they call).
- No multi-machine job distribution (all workers run on the local PC).
- No replacing Claude Agent SDK with raw API.

## Architecture Overview

Three new components, one config refactor, one UI refresh:

1. **`agents/models.py`** — central model registry, env-overridable.
2. **`agents/qa_director.py`** — Opus agent with `dispatch` tool + gatekeeper review pass.
3. **`workers/claude_code_worker.py`** — spawns headless `claude -p` inside a git worktree per job.
4. **Job queue extensions** in `routes/jobs.py` — `kind=overnight_code`, handoff endpoint, log SSE.
5. **Front-page UI** — status-rich tiles with Lucide icons (no emoji).

Cron jobs continue to call agents directly; the QA Director gatekeeper still inspects their output before any user-facing surface (dashboard, Telegram, vault) is updated.

## Component Detail

### 1. Model Tiering (`agents/models.py`)

```python
AGENT_MODELS = {
    "ceo":         "claude-opus-4-6",
    "researcher":  "claude-opus-4-6",
    "scout":       "claude-opus-4-6",
    "polymarket":  "claude-opus-4-6",
    "qa_director": "claude-opus-4-6",
    "trader":      "claude-sonnet-4-6",
    "adset":       "claude-sonnet-4-6",
    "inbox":       "claude-haiku-4-5-20251001",
}
```

- `Agent.__init_subclass__` reads this on registration; the existing class-level `model` attribute is removed from each agent file.
- Env override: `BORINA_MODEL_<AGENT_ID_UPPER>` wins over the registry. Lets you bump a single agent without code changes.
- A new `/agents/models` GET endpoint exposes the live mapping for the dashboard model badges.

### 2. QA Director (`agents/qa_director.py`)

**Dual role:**

- **Director-of-Work (ad-hoc chat path):** receives a high-level user prompt, plans which sub-agents to dispatch (any subset), runs them via an internal `dispatch(agent_id, prompt)` tool, and synthesizes one answer.
- **Gatekeeper (every output path):** any artifact destined for the user — ad-hoc chat answer, scheduled cron output, overnight worker result — passes through `qa_director.review(artifact)` first. The review checks: factual grounding against the artifact's own sources, completeness vs. the original request, contradictions, hallucinated tool output, and tone. Output is one of `approve`, `approve_with_notes`, `request_rerun(reason)`, `block(reason)`.

**Implementation notes:**

- Single new agent class subclassing `Agent`, model from registry (`qa_director` → Opus).
- Exposes one custom tool to the SDK: `dispatch(agent_id: str, prompt: str) -> AgentRun`. The tool resolves the agent via `AgentRegistry`, runs it, returns the structured result.
- Gatekeeper integration points (single chokepoint per surface):
  - `routes/chat.py` — wraps the existing direct-call path so chat now goes through QA Director by default. A `?raw=true` query param bypasses for debugging.
  - `scheduler.py` — after each scheduled run completes and `artifacts.save_run_output` is called, the saved artifact is piped through `qa_director.review()` before any Telegram/dashboard event publishes. Reruns are bounded to 1 retry per scheduled job to prevent loops.
  - `workers/claude_code_worker.py` — on worker completion, the diff + summary go through `qa_director.review()` before the success Telegram fires.
- Review verdict is persisted on the `AgentRun` (new `qa_verdict`, `qa_notes` columns) and surfaced in the dashboard.

### 3. Overnight Worker (`workers/claude_code_worker.py`)

Per job, the worker:

1. Creates a git worktree at `.borina-workers/<job_id>` on a fresh branch `borina/job-<id>` off the job's specified base branch.
2. Writes the handoff context to `BORINA_TASK.md` inside the worktree. Context includes: user prompt, originating cwd, `git status` snapshot, `git diff` of unstaged changes, list of recently touched files, and a "background" section with the last ~20 messages of the originating Claude Code conversation (passed by the slash command).
3. Spawns `claude -p "$(cat BORINA_TASK.md)" --output-format stream-json --permission-mode acceptEdits` with `cwd=worktree`. Stdout is piped line-by-line into `logs/jobs/<job_id>.jsonl`.
4. Tail of that log is broadcast via SSE on `GET /jobs/{id}/log` for the dashboard live view.
5. On exit:
   - Capture `git diff <base_branch>` and the final commit list.
   - Run QA Director review on the diff + worker summary.
   - On approve: push the branch, post Telegram with branch name + dashboard link, write a vault note.
   - On block / failure: post Telegram with the QA notes and last 30 lines of log; leave the worktree in place for inspection.
6. Worktree cleanup is manual (`POST /jobs/{id}/cleanup`) so failures stay debuggable.

**Concurrency:** One worker process per job. Soft cap of 3 concurrent overnight workers (configurable via `BORINA_MAX_WORKERS`). Excess jobs queue.

### 4. Job Queue Extensions (`routes/jobs.py`)

Schema additions to the existing `Job` model:

- `kind: Literal["agent_run", "overnight_code"]` (default `agent_run` for back-compat)
- `repo_path: str | None`
- `base_branch: str | None`
- `worker_branch: str | None`
- `worker_pid: int | None`
- `log_path: str | None`
- `qa_verdict: str | None`
- `qa_notes: str | None`

New endpoints:

- `POST /jobs/handoff` — body: `{repo_path, base_branch, prompt, cwd_snapshot, recent_files, conversation_tail}`. Creates an `overnight_code` job, enqueues a worker, returns `{job_id, dashboard_url}`.
- `GET /jobs/{id}/log` — SSE stream of the job log.
- `POST /jobs/{id}/cancel` — sends SIGTERM to `worker_pid`, marks job cancelled.
- `POST /jobs/{id}/cleanup` — removes the worktree (only allowed in terminal states).

### 5. `/handoff` Slash Command

A new file at `~/.claude/commands/handoff.md` instructing Claude Code to:

1. Read the user's task description from the command args.
2. Run `git status --porcelain`, `git diff`, and `git rev-parse --abbrev-ref HEAD` in cwd.
3. Collect the file paths touched in the last 5 user messages of the current conversation (best-effort from prior tool calls).
4. POST to `http://localhost:8000/jobs/handoff` with the assembled payload.
5. Print the returned `dashboard_url` and job id to the user.

This is the primary path; the dashboard "New Job" modal posts to the same endpoint as the secondary path.

### 6. Front Page UI Refresh

Replace the emoji-based agent grid on `apps/web/app/page.tsx` with **status-rich tiles**:

- **Icon:** Lucide line-art icon, one per agent (e.g. `Briefcase` for CEO, `Search` for Researcher, `Compass` for Scout, `LineChart` for Trader, `Megaphone` for Adset, `Inbox` for Inbox, `TrendingUp` for Polymarket, `ShieldCheck` for QA Director).
- **Accent color:** distinct per agent, used for the icon background and the status dot ring.
- **Status dot:** green = idle/healthy, blue = running, amber = QA flagged, red = error.
- **Metadata row:** model badge (`Opus` / `Sonnet` / `Haiku` colored chip), last-run relative time, next scheduled run.
- **Card body:** one-line purpose, click to open the agent's chat panel.
- **Component:** rewrite `apps/web/components/agent-card.tsx`. Add a small `ModelBadge` and `StatusDot` subcomponent in the same file.
- Data source: existing agent list endpoint, plus the new `/agents/models` mapping for badges.

## Data Flow Summary

**Ad-hoc chat:**
User → web → `POST /chat/qa_director` → QA Director plans → dispatches sub-agents in parallel → collects → reviews own synthesis → returns to user.

**Scheduled cron:**
Scheduler → agent runs directly → artifact saved → QA Director review → on approve, dashboard event + Telegram + vault. On block/rerun, retry once then escalate.

**Overnight handoff:**
Claude Code `/handoff` → `POST /jobs/handoff` → worker creates worktree → spawns `claude -p` → completion → QA Director review → branch push + Telegram + vault note.

## Error Handling

- Worker subprocess crashes → job marked `failed`, log preserved, Telegram alert with last 30 lines.
- QA Director rerun loops → hard cap of 1 retry per surface (chat, cron, worker). After cap, return with QA notes attached and `qa_verdict=approve_with_notes`.
- Worktree creation fails (e.g. dirty base) → job rejected with clear error before any process spawns.
- Claude Code subprocess hangs → wall-clock timeout (default 4h, configurable via `BORINA_WORKER_TIMEOUT`).
- Model env override points at unknown model → startup fails fast with the bad mapping listed.

## Testing Strategy

- **Unit:** model registry resolution (incl. env override), QA Director verdict parsing, job schema migrations, slash command payload assembly.
- **Integration:**
  - Fake `claude` binary on PATH that emits canned stream-json — exercises the worker pipeline end-to-end without burning tokens.
  - QA Director gatekeeper test that injects a deliberately bad artifact and asserts the rerun path fires exactly once.
  - Scheduler test asserting cron output now flows through the gatekeeper.
- **Manual:** real overnight handoff on a sandbox repo with a trivial task ("add a docstring to X"); verify Telegram + dashboard + vault note.

## Migration Notes

- Removing `model` class attributes from existing agents is a breaking change for any caller that read `Agent.model` directly. Audit and update.
- Adding `Job` columns requires an Alembic migration (or whatever the project uses — confirm during planning).
- The chat route default behavior changes (now goes through QA Director). Document the `?raw=true` escape hatch in the README.

## Open Questions for Plan Phase

- Exact Lucide icon mapping per agent (placeholder list above is a starting point).
- Whether QA Director's `dispatch` tool should run sub-agents in parallel by default or require an explicit `parallel=true`.
- Where to store worker logs long-term (vault vs. local-only with rotation).
