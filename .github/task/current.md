# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #275
TITLE: CRIMPD P1 — Plans: schedule future weeks and clone a week's schedule
URL: https://github.com/bimoool/pullup-trainer-bot/issues/275
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: eb371dc791efbf579416b46515e44160948fa4b8
BRANCH: orch/issue-275
BATCH: 10 (task 1/5)
SELECTED AT: 2026-10-02 05:55 UTC

## Goal

Let users plan ahead: add/move items into upcoming weeks and copy one week's manual schedule to the next week (Crimpd schedule editing / Clone Training Plan adapted).

## Acceptance criteria

- [ ] Week navigation (from the week-navigation issue) allows › into up to 4 future weeks, creating `PlanWeek` rows on demand (additive behaviour, no schema change expected).
- [ ] In a future week the user can add own workouts/exercises and move items between days (existing endpoints extended with `plan_week_id`); program-backed items continue to be materialised by existing program logic only.
- [ ] «Скопировать неделю → на следующую» copies manual (user) items of the shown week into the next week (skipping duplicates), with confirmation.
- [ ] Moving an item to another week (not only another day) is supported for manual items.
- [ ] pytest for week creation, copy rules and ownership; parity spec file («Plans schedule»).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/plans-schedule.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`DashboardScreen.tsx`, `MovePlanItemScreen.tsx`, `apiV2.ts`; plan routes/services; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/plans-schedule.spec.ts` («Plans schedule»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Copying program-backed items, changing program start dates. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
