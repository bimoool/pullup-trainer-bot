# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #267
TITLE: CRIMPD P1 — Export training history as CSV
URL: https://github.com/bimoool/pullup-trainer-bot/issues/267
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 93e04c8d88bcad5fad3e195d274e18a7c5de10d0
BRANCH: orch/issue-267
BATCH: 9 (task 1/5)
SELECTED AT: 2026-10-02 03:52 UTC

## Goal

Let users download their training history as CSV from Analytics (Crimpd «Export Log Data — Download»).

## Acceptance criteria

- [ ] `GET /api/v2/export/sessions.csv` streams the current user's completed v2 sessions and set logs (one row per set: date, workout/exercise name, protocol, set number, value, unit, effort, note, session effort, session comment) and legacy workouts in a second file or a `source` column; UTF-8 with BOM for Excel; only the caller's data.
- [ ] Analytics shows a card «Экспорт данных — CSV» with «Скачать»; inside Telegram the download uses `Telegram.WebApp.downloadFile` when available, otherwise opens the URL; an authenticated short-lived signed link is used if headers cannot be sent (no initData in query strings).
- [ ] pytest: content, ownership, empty history (header row only), escaping; parity spec file («Export») verifies the response (request interception).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/export.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

new `app/web` export route, `webapp-frontend/src/AnalyticsScreen.tsx`, `apiV2.ts`; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/export.spec.ts` («Export»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Import. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
