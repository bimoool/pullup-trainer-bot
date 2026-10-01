# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #272
TITLE: CRIMPD P0 — Favorites: favorite workouts and programs + Home row
URL: https://github.com/bimoool/pullup-trainer-bot/issues/272
PRIORITY: p0
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: cedd7faf0e79c1c5bcb29ad2da438828c36569f0
BRANCH: orch/issue-272
BATCH: 6 (task 3/5)
SELECTED AT: 2026-10-01 20:37 UTC

## Goal

Persisted per-user favorites for workouts and programs: a heart on detail screens and an «Избранное» row on Главная.

## Acceptance criteria

- [ ] Additive table `user_favorites` (user_id, target_type `workout|program`, target_id, created_at, unique per user+target).
- [ ] API `GET /api/v2/favorites`, `PUT`/`DELETE /api/v2/favorites/{target_type}/{target_id}` — idempotent; only targets visible to the user (own workouts, published programs) — 404 otherwise.
- [ ] Heart toggle on Workout Detail and Program detail: instant optimistic toggle, reverted with a short error if the request fails.
- [ ] Главная: «Избранное» row with favorited items (hidden when empty? — show an honest empty hint «Нажмите ♡ на тренировке, чтобы добавить» only if the user has never favorited; otherwise hidden).
- [ ] Search (if the Home discovery search exists) gets an «Избранное» filter chip.
- [ ] Deleted/hidden targets drop out of the list automatically.
- [ ] pytest; crimpd-parity.spec.ts «Favorites» block (toggle, persists after reload, Home row).
- [ ] Add a `test.describe("Favorites")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

alembic (additive), `app/db`, `app/web` favorites routes; `WorkoutDetailScreen.tsx`, `ProgramDetailScreen.tsx`, `HomeScreen.tsx`, `apiV2.ts`; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Favorites»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

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
