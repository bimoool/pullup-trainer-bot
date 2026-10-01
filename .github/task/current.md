# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #263
TITLE: CRIMPD P1 — Journal: backdated logging and free activity entry
URL: https://github.com/bimoool/pullup-trainer-bot/issues/263
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: db431b21bc3948cfede40a501617a0042165f15c
BRANCH: orch/issue-263
BATCH: 7 (task 5/5)
SELECTED AT: 2026-10-01 23:46 UTC

## Goal

Let users record a workout they did without the timer (backdated) and log a free activity (running, swimming…), reachable from Журнал and the Home «+» sheet.

## Acceptance criteria

- [ ] Журнал gets a «+ Записать» button opening a sheet: «Тренировку из моих» and «Другую активность».
- [ ] «Тренировку из моих»: pick an own workout, date (today or past, not future), per-exercise set values, workout effort and note → creates a completed v2 session `source=backdated` via `POST /api/v2/sessions`; no progression side effects for program content.
- [ ] «Другую активность»: date, type from a fixed list (Бег, Велосипед, Плавание, Ходьба/хайкинг, Йога/растяжка, Силовая в зале, Единоборства, Другое), duration (h:mm), effort 1–5, note → stored as a v2 session `source=freeform` with additive nullable columns `activity_type`, `duration_seconds`.
- [ ] Both entries appear in the Journal (calendar dots, cards with type/duration) and count as workouts in Analytics; free activities count minutes from `duration_seconds`.
- [ ] Validation: future dates rejected, duration 1 min–12 h; ownership enforced.
- [ ] pytest + crimpd-parity.spec.ts «Journal log» block.
- [ ] Add a `test.describe("Journal log")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/HistoryScreen.tsx`, new `LogActivitySheet.tsx`/forms, `HomeScreen.tsx` («+» sheet entry), `apiV2.ts`; `app/web` v2 sessions create route/schema, additive migration; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Journal log»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Heart-rate zones (no data), importing from wearables. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
