# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #266
TITLE: CRIMPD P1 — Plans: plan overview (in progress / programs history) and program schedule preview
URL: https://github.com/bimoool/pullup-trainer-bot/issues/266
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: d7c001707f35175725c9882532a523f318416715
BRANCH: orch/issue-266
BATCH: 8 (task 3/5)
SELECTED AT: 2026-10-02 02:43 UTC

## Goal

Add Crimpd's plan overview surfaces adapted to one active plan: an «Сейчас» card with week and progress, a list of completed/removed programs, and a program detail that shows the program's schedule before adding it.

## Acceptance criteria

- [ ] Top of Планы: tabs «Сейчас | Завершённые». «Сейчас» = current plan card (programs included, current week number per inclusion if the program has a fixed length, progress this week) followed by the week view; «Завершённые» = inactive `ProgramInclusion`s with name and date range (empty state text).
- [ ] Program detail (from Главная) shows the program's structure from real `ProgramItem`/config data: week-by-week or per-session list of exercises with targets in human form, phase chips when present; «Добавить в план» stays the primary action. Programs without previewable items show only description (no invented schedule).
- [ ] Users can remove a program from the plan («Убрать курс из плана», confirmation) — sets `is_active=false` (no deletion of history) — then it appears under «Завершённые».
- [ ] API additions with ownership checks and pytest; parity spec file («Plans overview»).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/plans-overview.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/DashboardScreen.tsx`, `ProgramDetailScreen.tsx`, `apiV2.ts`; program/plan routes and services; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/plans-overview.spec.ts` («Plans overview»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Multiple active plans, plan start-date change, levels selector unless present in program config. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
