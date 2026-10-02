# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #268
TITLE: CRIMPD P1 — Profile: Settings screen (units, timezone, theme, timer sound, subscription, export)
URL: https://github.com/bimoool/pullup-trainer-bot/issues/268
PRIORITY: p1
TYPE: ux
BASE BRANCH: develop/current
BASE SHA: 22e717d9d607e2ee8c49e6212dbd9851c16a53a2
BRANCH: orch/issue-268
BATCH: 9 (task 2/5)
SELECTED AT: 2026-10-02 04:16 UTC

## Goal

Add a Crimpd-style Settings screen reachable from Профиль (gear) that gathers account/profile preferences in one place.

## Acceptance criteria

- [ ] Gear button on Профиль opens «Настройки» with sections: Профиль (existing fields via `/api/profile`), Единицы (вес: кг | фунты; рост: см | дюймы — display/input conversion only, storage stays metric), Часовой пояс (existing options), Оформление (Как в Telegram | Светлая | Тёмная), Таймер (громкость/звук via existing `/api/timer/preferences`), Подписка (status → existing SubscriptionScreen), Данные («Скачать историю» linking the CSV export if the export endpoint exists, otherwise the row is not shown), links to оферта.
- [ ] New preferences (units, theme) stored server-side in additive nullable user columns or a prefs JSON; applied app-wide (weights/heights rendered in chosen units; theme override applied to AppRoot).
- [ ] Save/Cancel semantics like Crimpd (nothing applied until «Сохранить»).
- [ ] pytest for prefs API; parity spec file («Settings») (unit switch visible in profile, theme override, cancel discards).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/settings.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

new `webapp-frontend/src/SettingsScreen.tsx`, `ProfileScreen.tsx`, `main.tsx` (theme), unit helpers, `api.ts`; `app/web` profile routes, additive migration; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/settings.spec.ts` («Settings»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Account deletion, password (Telegram auth), locale switch. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
