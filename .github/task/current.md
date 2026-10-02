# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #273
TITLE: CRIMPD P0 — Workout Detail: Start now and Log from detail
URL: https://github.com/bimoool/pullup-trainer-bot/issues/273
PRIORITY: p0
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 3804b198c95c3442ce867f77a7e52ae779ce1c37
BRANCH: orch/issue-273
BATCH: 8 (task 5/5)
SELECTED AT: 2026-10-02 03:19 UTC

## Goal

Add Crimpd's «Start Workout» and «Log Workout» actions to Workout Detail: start a live session of this workout without scheduling it, or log it as done.

## Acceptance criteria

- [ ] «Начать» on Workout Detail starts a live session from the workout's frozen snapshot with `source=freeform` (no PlanItem required); backend `POST /api/v2/sessions/live` accepts `workout_id` for the user's own workout (PROJECT_SPEC §5 visibility; 404 otherwise) and keeps client_session_id idempotency; the existing one-active-session rule applies (if another live session is active, the user is offered to resume it).
- [ ] The session runs through the existing pre → live → summary flow; completion does not touch program progression; it appears in Journal and in the workout's history.
- [ ] «Записать» opens the backdated log form (from the Journal logging issue) pre-filled with this workout.
- [ ] Plan counters are unaffected by freeform sessions unless explicitly linked (documented in PROJECT_SPEC).
- [ ] pytest for start-by-workout (ownership, idempotency, active-session conflict); parity spec file («Workout Detail start/log»).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/workout-detail-start-log.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`WorkoutDetailScreen.tsx`, `PlanSessionFlow.tsx`, `App.tsx`, `apiV2.ts`; live session service/routes; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/workout-detail-start-log.spec.ts` («Workout Detail start/log»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Starting program sessions outside the plan. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
