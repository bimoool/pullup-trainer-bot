# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #261
TITLE: CRIMPD P1 — Custom workouts: delete and duplicate a workout
URL: https://github.com/bimoool/pullup-trainer-bot/issues/261
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 7ef474aa0bf9560eb00987ed58fa72f77b3bd8cc
BRANCH: orch/issue-261
BATCH: 7 (task 4/5)
SELECTED AT: 2026-10-01 23:08 UTC

## Goal

Let users delete and duplicate their own workouts, as Crimpd's Edit Workout offers «Delete Workout».

## Acceptance criteria

- [ ] Editor gets «Удалить тренировку» (with confirmation «Удалить тренировку? Это не удалит уже выполненные тренировки из журнала.») and «Дублировать».
- [ ] `DELETE /api/v2/workouts/{id}`: own user workout only (404 otherwise). Definitions are archived/soft-hidden if any plan item or session snapshot references them (CLAUDE.md: definitions are not destroyed by session operations; constitution Principle V) — completed sessions keep their frozen snapshot and stay in the Journal; current-week plan items referencing it are removed or the API returns 409 with a readable reason (choose one, document it in PROJECT_SPEC).
- [ ] `POST /api/v2/workouts/{id}/duplicate` creates «<name> (копия)» with copied items/protocols for the same owner.
- [ ] Deleted workouts disappear from Главная, «Мои тренировки» and search; duplicate appears immediately.
- [ ] pytest covers ownership, referenced-by-session, referenced-by-plan, duplicate fidelity; crimpd-parity.spec.ts gains a «Workout delete/duplicate» block.
- [ ] Add a `test.describe("Workout delete/duplicate")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/WorkoutEditorScreen.tsx`, `apiV2.ts`; `app/web` workouts routes, workout service/repository, additive migration if a hidden/archived flag is needed; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Workout delete/duplicate»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Bulk delete, undo. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
