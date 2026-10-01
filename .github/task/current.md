# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #258
TITLE: CRIMPD P1 — Plans: week navigation and done/skipped state per plan item
URL: https://github.com/bimoool/pullup-trainer-bot/issues/258
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 041237d83a592fb37b5bdf1f49abdaeaf2660da2
BRANCH: orch/issue-258
BATCH: 7 (task 1/5)
SELECTED AT: 2026-10-01 22:07 UTC

## Goal

Give Планы Crimpd-style week navigation (‹ Неделя N · даты ›) and show, per plan item, whether it was done this week.

## Acceptance criteria

- [ ] Планы shows ONE week at a time with a stepper «‹ Неделя · 29 сен – 5 окт ›» (phase chip when `PlanWeek.phase` is set); default = current week; past weeks reachable with ‹; › stops at the current week unless future weeks exist.
- [ ] Each plan item row shows a counter «сделано/план» (`done/count_per_week`) derived from completed sessions linked via `SessionPlanItem` in that week — no new stored status column unless strictly required (if added: additive, nullable).
- [ ] A week header shows overall progress «N из M» for that week.
- [ ] Past weeks are read-only except existing allowed actions; current-week actions («Начать», «+ Добавить упражнение», move/remove) keep working.
- [ ] API returns per-item done counts (e.g. extend `GET /api/v2/plan` or a week endpoint) computed in the user's timezone; pytest covers counting rules (completed only, mixed sessions counted once per item).
- [ ] crimpd-parity.spec.ts gains a «Plans week» block (navigation, counters after a completed session).
- [ ] Add a `test.describe("Plans week")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/DashboardScreen.tsx`, `apiV2.ts`; `app/web` plan routes/schemas, plan service; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Plans week»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Future-week scheduling and cloning (separate issue), plan list tabs (separate issue), a second active plan. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
