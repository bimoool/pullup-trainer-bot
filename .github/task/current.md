# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #254
TITLE: CRIMPD P0 — Home discovery: sticky search, category rows, quick + sheet
URL: https://github.com/bimoool/pullup-trainer-bot/issues/254
PRIORITY: p0
TYPE: ux
BASE BRANCH: develop/current
BASE SHA: ea2d1ec18de3aeb8abb0c5ad93f42920252d96c9
BRANCH: orch/issue-254
BATCH: 6 (task 1/5)
SELECTED AT: 2026-10-01 19:57 UTC

## Goal

Make Главная a discovery surface like Crimpd Home: a sticky search entry, content grouped into horizontal category rows, and a quick «+» action sheet — while keeping «Мои тренировки» and the program catalog.

## Acceptance criteria

- [ ] Sticky header on Главная with a search pill «Что потренируем сегодня?» that stays visible while scrolling; tapping opens a Search screen with an auto-focused input, live filtering and a «Найдено: N» counter.
- [ ] Search covers real content only: programs (`GET /api/v2/programs`), the user's own workouts (`GET /api/v2/workouts`) and library exercises (`GET /api/v2/exercises`); results are grouped by kind, each result opens its existing screen (program detail / workout / exercise add-to-plan). Empty result shows an honest «Ничего не найдено» state.
- [ ] Category filter chips on Search built from the real `category` values present in the loaded data (no hard-coded climbing categories); clearing restores all results.
- [ ] Programs on Главная are shown as horizontal rows grouped by `Program.category` (programs without a category go to one «Другое» row); each card shows name and goal/short summary. «Мои тренировки» section stays, unchanged in behaviour.
- [ ] A «+» button in the sticky header opens a bottom sheet with actions that work today: «Создать тренировку» (existing editor) and «Тренировка на сегодня» (opens Планы); «Отмена» closes it. No dead actions.
- [ ] Back/close from Search returns to Главная with scroll position preserved where the router allows; no horizontal overflow at 320/390 px in light and dark.
- [ ] crimpd-parity.spec.ts gains a «Home» block proving search, category rows and the «+» sheet.
- [ ] Add a `test.describe("Home")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/HomeScreen.tsx`, new `SearchScreen.tsx`, `App.tsx` (routing), `index.css`, `apiV2.ts`; e2e seed for a user with programs in ≥2 categories.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Home»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Favorites row (separate issue), curated collections (separate issue), equipment filter (our exercises have no equipment field), backend search endpoint (client-side filtering is enough for current catalog size). Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
