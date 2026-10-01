# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #256
TITLE: CRIMPD P1 — Journal: month calendar and day-grouped history
URL: https://github.com/bimoool/pullup-trainer-bot/issues/256
PRIORITY: p1
TYPE: ux
BASE BRANCH: develop/current
BASE SHA: 997cc0dc082980f1c2fdc2b1865a39b1a8836534
BRANCH: orch/issue-256
BATCH: 6 (task 4/5)
SELECTED AT: 2026-10-01 20:54 UTC

## Goal

Make Журнал read like Crimpd's Training History: a month bar with an expandable calendar showing training days, and the list grouped by week and day.

## Acceptance criteria

- [ ] Month bar «‹ Октябрь 2026 ›» at the top of Журнал; arrows change the month; tapping the label expands/collapses a month calendar (Mon-first, user timezone) with a dot on each day that has at least one completed session (v2 and legacy).
- [ ] Tapping a day in the calendar scrolls to / filters that day's entries; tapping it again clears the selection.
- [ ] The list is grouped by week (Mon–Sun band) and day header; entries keep their existing cards and detail behaviour (v2 detail, safe delete, legacy edit).
- [ ] Data is loaded per month from the backend (e.g. `GET /api/v2/journal/days?month=YYYY-MM` returning day counts, and the existing session lists filtered by date range) — no client-side full-history scan; timezone handling follows Analytics v2 (user tz, default Europe/Moscow).
- [ ] Empty month shows «В этом месяце тренировок нет»; no horizontal overflow at 320/390 px.
- [ ] crimpd-parity.spec.ts gains a «Journal calendar» block (dots on seeded days, day selection, month switch).
- [ ] Add a `test.describe("Journal calendar")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/HistoryScreen.tsx`, `JournalV2.tsx`, `useJournalV2.ts`, new calendar component, `app/web` v2 sessions routes (date-range filter / day counts).

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Journal calendar»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Edit/clone of sessions and backdated logging (separate issues). Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
