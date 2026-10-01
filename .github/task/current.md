# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #259
TITLE: CRIMPD P1 — Analytics: metric toggle (workouts / minutes), range selector, weekly chart
URL: https://github.com/bimoool/pullup-trainer-bot/issues/259
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 20e24eab291519d956946fcfd6c1ae09d07837b9
BRANCH: orch/issue-259
BATCH: 7 (task 2/5)
SELECTED AT: 2026-10-01 22:28 UTC

## Goal

Bring the Analytics «Тренировки» view to Crimpd's model: choose the metric (workouts vs training minutes) and the range (1 мес / 3 мес / свой), with a weekly bar chart.

## Acceptance criteria

- [ ] Additive nullable column `training_sessions.completed_at` set when a session completes (live complete, interval auto-finish, manual create); migration is additive; no backfill guessing.
- [ ] Duration of a session = `completed_at − performed_at` only when both exist and the result is within 1 min–6 h; other sessions count as workouts but are excluded from minutes, and the UI says «без данных о времени: N».
- [ ] Metric switch «Тренировки | Минуты» and range tabs «1 мес | 3 мес | Свой» (custom = from/to dates + «Применить»); default 1 мес / Тренировки.
- [ ] Weekly bar chart (Monday-labelled, user timezone) for the selected metric and range, project SVG chart rules (no Recharts).
- [ ] (i) button opens a short definitions sheet for both metrics.
- [ ] `GET /api/v2/analytics/training` (or a sibling endpoint) accepts `from`/`to` and returns weekly series for both metrics; pytest covers ranges, timezone, exclusions.
- [ ] crimpd-parity.spec.ts gains an «Analytics metric» block.
- [ ] Add a `test.describe("Analytics metric")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/TrainingAnalytics.tsx`, `AnalyticsScreen.tsx`, `apiV2.ts`; `app/domain/training_analytics.py`, analytics route, alembic migration (additive), live session completion service; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Analytics metric»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Category distribution and summary table (separate issue), export (separate issue). Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
