# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #270
TITLE: CRIMPD P1 — Profile: body metrics history (weight/height) with edit and delete
URL: https://github.com/bimoool/pullup-trainer-bot/issues/270
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 1985e11dfa3ddbf971bf11440ebd43fbba0269db
BRANCH: orch/issue-270
BATCH: 9 (task 4/5)
SELECTED AT: 2026-10-02 05:07 UTC

## Goal

Keep a history of body weight (and height) like Crimpd's attributes, with a trend and the ability to correct or delete entries.

## Acceptance criteria

- [ ] Additive table `user_body_metrics` (user_id, metric `weight_kg|height_cm`, value, measured_at, created_at); writing the profile weight/height also appends a history row; first deploy seeds one row from the current value (data migration, additive).
- [ ] Профиль → «Вес» opens a history screen: SVG trend, list (date, value), «Добавить замер», edit and delete with confirmation; the latest entry stays mirrored to `User.weight_kg` (deleting the latest falls back to the previous one).
- [ ] Existing consumers of `User.weight_kg` (GTO/WSF, leaderboard) keep working unchanged.
- [ ] API with ownership + validation; pytest; parity spec file («Body metrics»).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/body-metrics.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/ProfileScreen.tsx`, new `BodyMetricsScreen.tsx`, `api.ts`; `app/web` profile routes, repository, additive migration; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/body-metrics.spec.ts` («Body metrics»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Body fat or other metrics. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
