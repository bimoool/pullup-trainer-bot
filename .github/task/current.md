# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #274
TITLE: CRIMPD P1 — Analytics: distribution by category and multi-month summary table
URL: https://github.com/bimoool/pullup-trainer-bot/issues/274
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: affc6997f8118136b4a85ec7a2f34eea629c1cf5
BRANCH: orch/issue-274
BATCH: 9 (task 5/5)
SELECTED AT: 2026-10-02 05:28 UTC

## Goal

Add Crimpd's «by Type» distribution chart and the Summary table to Analytics, for the selected metric and range.

## Acceptance criteria

- [ ] Distribution SVG donut (inner ring = exercise/program category, outer = subcategory when present) for the selected metric/range from the analytics-metric issue; legend with colours from the project palette; sessions of mixed categories split by block share (documented).
- [ ] Summary table: rows per category (+ subcategory rows), columns Тренировки / Минуты, TOTAL row; zeros shown for categories present in the library.
- [ ] Free activities (if logged) appear as their own category «Другая активность».
- [ ] Backend aggregation + pytest; parity spec file («Analytics distribution»).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/analytics-distribution.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`TrainingAnalytics.tsx`, new SVG donut component, `app/domain/training_analytics.py`, analytics route; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/analytics-distribution.spec.ts` («Analytics distribution»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
