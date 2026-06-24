# Learning Day-Planner — Design

**Date:** 2026-06-24
**Status:** Approved (design), pending implementation plan
**Owner:** Bo

## Problem

The current day-planner (`planner.generate_plan_with_agent`, surfaced by the
`morning` operator phase) reads only *today's* calendar, open tasks, and the last
two Obsidian daily notes. It has no persistent model of Bo — no understanding of
what he's actually trying to do or the threads he's carrying — so its proposals
are generic and the plan is shallow.

Bo wants a planner that **learns what he wants to do from his daily activity** and
produces a **detailed, layered plan** grounded in that understanding, while writing
nothing to his calendar without an explicit approval tap.

## Goals

- Build a durable, evolving model of Bo learned from his daily workflows.
- Learn from three signals: Obsidian daily notes, Telegram conversations, and
  task + calendar history.
- Produce a layered morning plan: narrative brief → prioritized threads →
  time-blocked agenda.
- Make the agenda actionable: every block is an approvable calendar item; one
  "Approve all" tap writes the whole day to Google Calendar.

## Non-goals

- No autonomous calendar or task writes. The only writer stays `approve_item`,
  reached by Bo's tap. (Preserves the mesh safety invariant.)
- Not learning from approve/reject feedback in this iteration (explicitly dropped).
- No continuous/real-time model updates — learning is a once-nightly rollup.

## Architecture

Four additive pieces. Nothing in the existing approve/calendar safety path changes.

1. **Operator profile** — a durable, human-readable model of Bo at
   `04-resources/brain/operator-profile.md` in the Obsidian vault, alongside the
   existing `vault_brain` file. A compressed picture (~a few KB), not a log.
2. **Conversation log** — a new `ConversationLog` SQLModel table capturing
   Telegram messages. The currently-missing Telegram signal.
3. **Nightly learner** (`operator_brain.py`) — runs in the existing `eod` phase;
   updates the profile from the day's signals.
4. **Layered morning plan** — `generate_plan_with_agent` extended to emit a
   brief + threads + time-blocked agenda alongside the existing approvable items.

**Data flow:**
```
signals (daily note, ConversationLog, tasks, calendar)
  → [eod]   operator_brain.update_profile → rewrites operator-profile.md
  → [morning] planner reads profile + today → layered plan + approvable items
  → Bo taps "Approve all" → approve_item writes the day's blocks to Google Calendar
```

### Naming note

The learner module is `operator_brain.py`, NOT `operator.py` — `operator` shadows
the Python stdlib module (the same trap that made the daily operator
`daily_operator.py`).

## Component detail

### 1. Operator profile (`04-resources/brain/operator-profile.md`)

Fixed-section markdown the learner rewrites each night. Each section is a bounded
bullet list (cap ~8–10 items); on overflow the learner prunes oldest/stale entries.

```markdown
# Operator profile — Bo
_Updated: 2026-06-24 (eod)_

## Active threads
- <thread>: <what it is, current state, why it matters now> — last touched <date>

## Recurring priorities
- <standing weekly/daily commitments and focus areas>

## Working rhythms
- <when Bo does deep work, meeting-load patterns, energy notes>

## Preferences
- <how Bo likes the day shaped — e.g. mornings protected, no meetings before 10>

## Recently completed / closed
- <so the next plan doesn't re-surface finished work>
```

- "Active threads" carry a `last touched` date. The learner ages out threads
  untouched for **N days** (default 7) into a one-line note under "Recently
  completed / closed", keeping the profile a *current* picture.
- Applies the fresh-first / skip-stale principle Bo already wants for daily tasks,
  to the persistent model.
- Bo can read and hand-edit the file directly; the learner treats it as the
  source of truth to update, not to overwrite blindly.

### 2. Conversation log (`ConversationLog`)

New SQLModel table, mirroring `TelegramThread`'s style in `models.py`:

```python
class ConversationLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    role: str                       # "user" | "borina"
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
```

- Written in `routes/telegram.process_update` for inbound user text **after** the
  fail-closed allow-list (nothing from a non-allowed chat is ever stored), and
  where Borina sends replies (`role="borina"`).
- Every write wrapped so a logging failure is swallowed and never blocks dispatch.
- The learner queries one day's window by `created_at`.
- Retention: the nightly job trims rows older than **30 days** so the table can't
  grow unbounded.

### 3. Nightly learner (`operator_brain.py`)

Runs inside `daily_operator.run_phase("eod")`.

`update_profile(day)`:
1. Gather today's signals: today's Obsidian daily note, today's `ConversationLog`
   rows, tasks created/completed today, today's calendar events.
2. Load the current `operator-profile.md` (empty-template if absent).
3. One agent call (the `planner` agent, chief-of-staff persona). Prompt:
   *"Here is Bo's current profile and everything that happened today. Return the
   UPDATED profile — same sections, bounded bullet counts. Add/refresh active
   threads from today's signals, age out threads untouched >N days, move finished
   work to 'Recently completed.' No invention; only what the signals support."*
4. Validate: result is non-empty and contains the expected section headers. On any
   failure, **keep the existing profile** (never overwrite good state with garbage).
5. Write the validated profile back; then trim `ConversationLog` to 30 days.

The `eod` Card gains a line: *"Profile updated — N active threads."*

### 4. Layered morning plan (extend `generate_plan_with_agent`)

The planner agent prompt is injected with `operator-profile.md` + today's calendar
+ open tasks + recent daily notes, and must return a single JSON object:

```json
{
  "brief": "<2-4 sentence narrative: where you are, what today is for>",
  "threads": [{"name": "...", "today": "<concrete next action>", "why": "..."}],
  "items": [ <existing proposal objects — kind "task" | "calendar"> ]
}
```

- `items` keeps the **exact** current proposal shape, so `PlanItem` staging and the
  approve-tap flow are untouched.
- The **agenda blocks are calendar `items`** with real start/end (deep-work blocks,
  task slots, prep buffers). The agenda Bo sees *is* the set of approvable blocks;
  one "Approve all" (`op:approveall:{day}`, telegram.py) writes them all.
- `brief` + `threads` render into `daily-plan.md` and the morning Telegram message
  (above the Approve-all Card).
- **Fallback unchanged:** if the agent call or JSON parse fails, fall back to the
  deterministic `_build_proposals` + plain plan. The feature degrades; the morning
  never breaks.

### Rendering

`_render_plan_md` extended to lay out: brief → threads → agenda (from calendar
items) → tasks. The morning Telegram message is a trimmed version of that document,
followed by the existing approval Card.

## Safety

- No new write path to calendar or tasks. The only writer stays `approve_item`,
  reached by Bo's tap. Learner and planner are text-only (stage `PlanItem`s,
  rewrite a vault file).
- `ConversationLog` writes happen only after the fail-closed allow-list; logging is
  wrapped so a failure never blocks dispatch.
- The learner validates its output and keeps the prior profile on any failure — a
  bad agent run cannot corrupt the model.
- Profile + conversation log stay local (vault + SQLite); no new external surface.
- The planner keeps its existing fallback, so a flaky agent call degrades to
  today's behavior.
- The existing no-autonomous-write regression test must still pass.

## Testing

Matches the repo's `pytest` + hermetic `conftest.py` style; no real
Google/Telegram/LLM calls (stub the agent call as existing planner tests do).

- **ConversationLog:** written on allowed inbound; NOT written on a disallowed
  `chat_id`; a logging failure is swallowed.
- **Learner:** builds the right signal bundle for a day; valid agent output is
  written back; malformed/empty output preserves the old profile; thread-aging
  drops a >N-day-stale thread; conversation-log retention trims >30 days.
- **Planner:** agent JSON with `brief`/`threads`/`items` stages items correctly and
  renders all three layers; agenda calendar items carry valid start/end; parse
  failure falls back to deterministic proposals; the no-autonomous-write regression
  test still passes.
- **Rendering:** `_render_plan_md` lays out brief → threads → agenda → tasks; the
  morning message is the trimmed form.

## Open questions / defaults

- Thread-aging window **N = 7 days**, conversation-log retention **30 days** —
  defaults, tunable later.
- Logging Borina's replies (`role="borina"`) is included for richer context but is
  secondary; if it proves noisy it can be dropped without affecting the learner.

## Affected files (anticipated)

- `apps/api/models.py` — add `ConversationLog`.
- `apps/api/routes/telegram.py` — log inbound (post allow-list) + replies.
- `apps/api/operator_brain.py` — new: nightly learner.
- `apps/api/daily_operator.py` — call the learner in the `eod` phase; eod Card line.
- `apps/api/planner.py` — extend the agent prompt, parsing, `generate_plan_with_agent`,
  and `_render_plan_md` for the layered output.
- `apps/api/tests/` — new tests per the Testing section.
