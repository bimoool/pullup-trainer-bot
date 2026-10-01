# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #255
TITLE: CRIMPD P0 — Workout Detail screen (read-only) with actions and history
URL: https://github.com/bimoool/pullup-trainer-bot/issues/255
PRIORITY: p0
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: b09cc26523d3b2d0993015319750751b9f692f58
BRANCH: orch/issue-255
BATCH: 6 (task 2/5)
SELECTED AT: 2026-10-01 20:15 UTC

## Goal

Add a real Workout Detail screen, separate from the editor, reached from Главная and «Мои тренировки»: summary, exercises, primary actions and this workout's history.

## Acceptance criteria

- [ ] Tapping a workout card on Главная or in «Мои тренировки» opens `WorkoutDetailScreen` (not the editor).
- [ ] Header: workout name, subtitle «Своя тренировка», number of exercises and an estimated duration computed only from stored protocol fields (sets×reps/duration + rest; interval total time); if any item lacks the data needed, show no estimate rather than a guess.
- [ ] Exercise list uses the shared human summary (`blockFormat.ts` / `protocolConfig.ts` formatters), e.g. «3 × 8 повторений · отдых 1:00».
- [ ] Action row with round buttons: «Добавить в план» (existing AddToPlanScreen flow) and «Редактировать» (existing editor). Start/Log/Favorite buttons are added by their own issues — do not render placeholders that do nothing.
- [ ] «История» section lists this user's completed v2 sessions whose frozen `workout_snapshot` refers to this workout (newest first, date + short result), with an empty state «Вы ещё не выполняли эту тренировку»; backend endpoint e.g. `GET /api/v2/workouts/{id}/sessions` enforcing ownership (404 for others, PROJECT_SPEC §5).
- [ ] Telegram BackButton returns to the screen the user came from.
- [ ] crimpd-parity.spec.ts gains a «Workout Detail» block (detail opens instead of editor, actions present, history empty and populated).
- [ ] Add a `test.describe("Workout Detail")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

new `webapp-frontend/src/WorkoutDetailScreen.tsx`, `HomeScreen.tsx`, `MyWorkoutsScreen.tsx`, `App.tsx`, `apiV2.ts`; `app/web/` workouts routes + schema; tests in `tests/test_web/`.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Workout Detail»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Start / Log from detail (separate issue), Favorite (separate issue), workout delete/duplicate (separate issue). Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
