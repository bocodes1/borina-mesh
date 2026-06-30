# Borina Mesh — Agent Job Contracts (Design)

- **Date:** 2026-06-27
- **Status:** Approved design — pending implementation plan
- **Depends on:** the efficiency overhaul (PR bocodes1/borina-mesh#11) — this builds directly on its scheduler/finance changes. Generalizes the per-agent treatment that overhaul Workstream B applied to the finance brief.
- **Branch:** `feature/agent-job-contracts` (stacked on `feature/os-efficiency-overhaul`)

## Problem

Every scheduled agent produces low-value, context-free "slop" that burns tokens. Concretely, the trader artifact `reports/2026-06-27/trader-02877-1830.pdf` reads in full: *"Sunday weekend, no-op. Newest brief still June 27, nothing changed since the last trigger. Book flat, weekend hold."* — an LLM run spent to say nothing. Three root causes, all confirmed in code:

1. **No real task.** `scheduler.py:521` hands *every* cron agent the literal prompt `"Run your scheduled daily task. Now: …Z"`. There is no concrete, consistent job, so the agent improvises a vacuous result. Only `finance` has an actual task spec (`~/.borina/agents/finance/{CLAUDE.md,BRIEF_FORMAT.md}`, with a fixed workdir so the specs travel with it — `runner_v2.py:44-45`). trader/inbox/researcher/ceo/scout/adset have only a one-line role in `agents/<agent>.py:16` (`system_prompt`).
2. **No context.** `vault_brain.recall()` (`dispatch/vault_brain.py:41`) exists but is **not** injected on the cron path. `scheduler._run_agent` (`scheduler.py:504-575`) builds the prompt with zero vault recall, zero real data, and no memory of the agent's own prior output — so an agent literally cannot "update from context."
3. **Raw pane → PDF.** The cron path saves `result.output` straight from an 80-line tmux pane capture (`runner_v2.py:112`); it does **not** use the clean answer-file handoff `run_agent_for_answer` (`dispatch/answer.py:148`) that `finance`/`mission` use. Short replies survive; longer ones become scraped chrome (echoed prompt, ⏺ tool calls, ANSI).

**Deeper issue:** several agents have **no live data source**. trader watched the Polymarket bot (deleted in the overhaul); inbox-triage needs Microsoft-Graph email that is not connected. They can *only* emit "nothing changed" filler — structural token loss.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Scope | **General framework** — a reusable job-contract every agent uses, then concrete jobs for the active ones |
| trader / scout / adset | **Off** — no cron (no live data source); keep code, reactivate when a source exists |
| inbox-triage | **Gate off** until Microsoft OAuth is connected (same pattern as Outreach) |

## Goals

- Every agent run is grounded in real context and produces a readable, consistently-formatted artifact.
- An agent never spends an LLM call to report "nothing changed."
- Agents with no live data source do not run on a timer.

## Non-goals

- Wiring new data integrations (Microsoft OAuth email, on-chain, etc.) — out of scope; we gate off instead.
- Changing the agent roster model or the overhaul's cron cadence (this layers on top).
- The orchestration engine (separate spec).

---

## Design — the Job Contract

A **Job Contract** is the generalization of the finance pattern to every agent. Four parts:

### 1. Task spec (`~/.borina/agents/<agent>/TASK.md`)
One concrete, repeatable job + a fixed, readable output format. Replaces the generic `scheduler.py:521` prompt. Stored per-agent in a **fixed workdir** (generalize the finance special-case at `runner_v2.py:44-45` so *every* contracted agent gets a stable workdir, not a pane-prefixed ephemeral one — so its `TASK.md` + any format spec travel with it). The cron prompt becomes: *"Do the job defined in TASK.md using the CONTEXT below. Output exactly in the specified format. If the context shows nothing new, reply with the single line `NO CHANGE`."*

### 2. Context pack (deterministic, assembled before the run)
A small Python builder (`agents/context_pack.py`, new) assembles and injects, per agent:
- **Vault recall** — `vault_brain.recall(query)` keyed off the agent's domain (Obsidian vault: goals, relevant notes).
- **Real data** — the agent's own data source (e.g. researcher → today's `daily-brief` inputs; planner → calendar/free-busy/tasks). No source ⇒ the agent is off (per decisions).
- **Last artifact** — the agent's most recent output (so it "updates from context": what did I say last time, what changed). Read from `reports/` / the agent's workdir.
The pack is rendered into the prompt under a `CONTEXT:` header, size-capped (mirror `recall`'s `max_chars`).

### 3. Clean output (answer-file handoff)
Route the cron path through `run_agent_for_answer(agent_id, prompt, job_id)` (`dispatch/answer.py:148`) instead of saving the raw pane capture. The agent writes its answer to a file in its workdir; we read that back — the same clean handoff finance/mission already use. The PDF/artifact is rendered from the clean answer, not pane scrape.

### 4. Skip-if-no-signal (deterministic short-circuit)
Two layers:
- **Pre-LLM:** if the context-pack builder detects no change since the last artifact (e.g. same upstream brief hash, empty data, no new vault signal), `_run_agent` writes a one-line `NO CHANGE` artifact and **spends no LLM** (mirrors the finance brief empty-screen short-circuit from the overhaul).
- **Post-LLM:** if the agent itself returns exactly `NO CHANGE`, persist it as a terse status, not a PDF report.

### Runner change (`scheduler._run_agent`)
Replace the generic prompt (`scheduler.py:521`) with: build the context pack → if no signal, short-circuit → else render `TASK.md` + `CONTEXT:` into the prompt → `run_agent_for_answer` → persist the clean artifact. A contract is opt-in per agent: agents without a `TASK.md` fall back to today's behavior (so nothing breaks during rollout).

---

## Per-agent jobs (v1)

| Agent | Cron | Job (TASK.md) | Context pack | Status |
|---|---|---|---|---|
| **researcher** | 6:00 | Morning research digest: 3–5 grounded items tied to the operator's active goals + live web; fixed sections | vault goals + web + last digest | **Keep + contract** |
| **planner** | 6:30 | Consolidated morning brief + proposed plan (already the overhaul's single morning brief) | calendar/free-busy + tasks + vault + last plan | **Keep + contract** |
| **operator-eod** | 18:15 | Nightly profile update (already writes `operator-profile.md`) | day's tasks/approvals + last profile | **Keep + contract** |
| **inbox-triage** | — | (email triage) | — | **Off** until Microsoft OAuth set |
| **trader** | — | (none — bot deleted) | — | **Off** |
| **scout / adset** | — | (parked) | — | **Off** |
| **ceo** | on-demand | mission decompose/synthesis | per-call | contract applies when invoked |

Turning trader/scout/adset/inbox off = no cron registration. The overhaul already removed `trader` (and `ceo`/`researcher`) from `DEFAULT_SCHEDULES`, and `scout`/`adset` are parked so the roster gate already blocks their crons; this spec additionally **gates inbox-triage's cron behind a Microsoft-OAuth-present check** (same shape as the Outreach gate). Note: `researcher`'s morning run is the `schedule_daily` 6am path (not a `DEFAULT_SCHEDULES` entry); the contract attaches there. The contract framework still applies whenever any off-agent is invoked on-demand.

## Safety invariants (unchanged)

- Contracts are **propose-only**: a TASK.md may instruct an agent to *draft/propose*, never to autonomously write the calendar or send anything. No new write path; the `user_initiated=True` calendar gate is untouched.
- Vault access is **read-only recall**; `remember()` writes stay on the existing explicit path.
- Telegram fail-closed; cooperative cancel; the planner no-autonomous-write regression test stays green.

## Files

- **Add:** `apps/api/agents/context_pack.py` (the deterministic builder); `~/.borina/agents/<agent>/TASK.md` for researcher, planner, operator (runtime files, outside git — note in deploy).
- **Modify:** `apps/api/scheduler.py` (`_run_agent`: context pack + TASK.md prompt + `run_agent_for_answer` + short-circuit; gate inbox-triage cron on Microsoft-OAuth presence); `apps/api/agents/runner_v2.py` (generalize the fixed-workdir special-case beyond finance); `apps/api/dispatch/answer.py` if the handoff needs a save hook for artifacts.

## Tests

- Context pack: builds the expected sections; size-capped; "no change since last artifact" detected from a stub last-artifact.
- Short-circuit: no-signal ⇒ `_run_agent` writes `NO CHANGE` and makes **zero** agent calls (assert the runner is not invoked); signal ⇒ runs once via `run_agent_for_answer`.
- Clean output: the persisted artifact comes from the answer file, never the raw pane capture (assert pane-chrome strings absent).
- Gating: inbox-triage cron is **not** registered when the Microsoft-OAuth env is absent; is registered when present.
- Fallback: an agent with no `TASK.md` still runs via the legacy path (no regression).
- Safety: a TASK.md cannot trigger a calendar write — the no-autonomous-write regression stays green.

## Future / non-goals (v2)

- Connecting Microsoft OAuth so inbox-triage has a real source.
- A real data source for trader (FMP/Polygon market note) — overlaps the finance agent; decide later.
- Richer per-agent output formats / PDF templating.
