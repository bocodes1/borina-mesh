# BUILD_LOG — Frontend Rebuild + Life-OS Tabs + Autonomous Telegram Dispatch

Append-only. Each entry: timestamp, what changed, which tests now pass.
Spec: `~/Documents/borinamesh/borina-mesh-frontend-rebuild.md`. Branch: `feature/frontend-rebuild`.

Working model: built on a feature branch in-place; live launchd services (`com.borina.mesh-api/web`)
left running their loaded `main` code; `com.borina.mesh-updater` (StartInterval=120) **paused** for the
build and to be **restored at the end**. Tests/dev servers use non-live ports (pytest uses TestClient).

3-failure rule in effect. Missing real credentials → mock + mark autonomous-complete + add to §12 hand-off
(never fabricate a credential or fake a green check). Safety rules in spec §7 / §8b are never weakened.

---

## 2026-06-02 — Step 0: Assessment + setup
- Mapped apps/web + apps/api. Confirmed gaps: no `/daily`,`/calendar`; Terminal present; stub routers
  (`tasks/daily/calendar/telegram`); no `integrations/`; no Telegram dispatch; no `schedule_daily` brief;
  6 shared UI primitives absent; **no frontend test harness**; `.env.example` missing new keys.
- Paused `com.borina.mesh-updater`; created branch `feature/frontend-rebuild` from `main` (c15b262).
- Decision: keep `/polymarket` tab (spec only mandates deleting Terminal; Polymarket is also a Finance panel).
- Tests pass: (baseline) existing backend pytest suite — to be re-verified.

## 2026-06-02 — Step 1: Test harness (Task #1) ✅
- **Backend:** added `apps/api/conftest.py` — isolates tests from production: temp `DATABASE_URL`
  (protects the live `borina.db` the running service uses), `REPORTS_DIR`→temp, and a per-test
  autouse fixture resetting `OBSIDIAN_VAULT_PATH` so cross-test env leakage (`test_wiki_routes`
  sets it at import) can't bleed real artifacts into hermetic tests.
- Fixed a pre-existing flaky test: `test_claude_code_worker._init_repo` now `git branch -M master`
  so it's independent of the host `init.defaultBranch` (was failing: `master` vs `main`).
- **Frontend:** installed vitest@2 + @testing-library/react@16 (React 19) + jsdom; added
  `vitest.config.ts`, `vitest.setup.ts` (jsdom polyfills: matchMedia/ResizeObserver/scrollIntoView),
  and `npm test` / `test:watch` scripts. There was **no** frontend test harness before.
- **Tests now pass:** backend `pytest -q` → **92 passed** (was 91 + 1 pre-existing fail). Frontend
  `vitest run` → sanity test green.
