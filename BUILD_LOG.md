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

## 2026-06-02 — Step 2: Design system + shared primitives (Task #2) ✅
- Extended token system additively (kept violet `--primary` as the single accent): added
  `--surface`/`--surface-2` layers + `--brand`/`--positive`/`--negative`/`--warn` semantics in
  `globals.css` (both `:root` and `.dark`), wired matching Tailwind colors (`bg-surface`, `text-positive`…).
  Added `.surface-card` (hairline + inner top-light gradient + shadow) and `.value-flash` (live-update tint).
- Created the 6 shared primitives in `components/ui/`: `section-header`, `kpi-card` (tabular-nums + delta tones),
  `data-table` (generic, numeric cols → tabular-nums, empty→EmptyState), `empty-state` (CTA slot for "Connect X"),
  `error-state` (retry), `loading-skeleton` (Skeleton + KpiStrip/Card/Rows presets).
- Fixed a type conflict (`title: ReactNode` vs HTML `title`) via `Omit<…,"title">`.
- **Tests now pass:** `vitest run test/primitives.test.tsx` → 6 passed; `tsc --noEmit` clean; `npm run build` clean.
