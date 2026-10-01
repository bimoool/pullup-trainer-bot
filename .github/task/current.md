# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #260
TITLE: CRIMPD P1 — Tests hub: assessments with history, record result and trend
URL: https://github.com/bimoool/pullup-trainer-bot/issues/260
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: de8366ca9506afec64cdd2145fc882eb0e7ce284
BRANCH: orch/issue-260
BATCH: 7 (task 3/5)
SELECTED AT: 2026-10-01 22:48 UTC

## Goal

Give users a visible Tests (Тесты) hub — Crimpd «Assessment Tests» / «Primary Assessments» — built on our existing `AssessmentProtocol` / `AssessmentResult` tables.

## Acceptance criteria

- [ ] Seed/ensure a small set of assessment protocols relevant to our domain (e.g. «Максимум подтягиваний», «Вис на перекладине, сек», «Подтягивания с весом, кг» — names in a data migration or seed, additive) — no climbing tests.
- [ ] Тесты section on Профиль (and a «Тесты» row on Главная) lists protocols as cards: name, last result + date or «Ещё не проходили», mini trend when ≥2 results.
- [ ] Test detail: description, result history list (newest first), SVG trend chart, «Записать результат» form (date ≤ today, value, optional note) and edit/delete of the user's own results with confirmation.
- [ ] API under `/api/v2/assessments` (list protocols with last result, list/create/update/delete own results) with ownership checks (404 for others) and validation.
- [ ] Recording a test result does NOT change progression or the onboarding baseline (assessment results are outside the progression cascade, per the model docstring); the UI says so where relevant.
- [ ] crimpd-parity.spec.ts gains a «Tests» block (record, see in history and trend, edit, delete).
- [ ] Add a `test.describe("Tests")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

new `webapp-frontend/src/TestsScreen.tsx`/`TestDetailScreen.tsx`, `ProfileScreen.tsx`, `HomeScreen.tsx`, `apiV2.ts`; new `app/web` assessments routes/schemas, repository; additive seed/migration; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Tests»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Peer comparison (separate issue), feeding tests into progression (owner decision). Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
