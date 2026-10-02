# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #269
TITLE: CRIMPD P1 — Background timer web-equivalent: reconciliation, wake lock, cues, platform note
URL: https://github.com/bimoool/pullup-trainer-bot/issues/269
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: ec691d7467dd1aef953718c25b4bc126136547a4
BRANCH: orch/issue-269
BATCH: 9 (task 3/5)
SELECTED AT: 2026-10-02 04:46 UTC

## Goal

Guarantee timer correctness when the Mini App is backgrounded/reopened and document what a Telegram Mini App cannot do compared to native timers.

## Acceptance criteria

- [ ] After background/lock of 10 s–5 min, rest and get-ready countdowns show the correct remaining time (computed from absolute timestamps, never paused by the OS); if the phase ended while hidden, the UI advances exactly once (no double transition, no duplicate set).
- [ ] Interval workouts resume on the server clock with the correct phase and round.
- [ ] Wake lock is re-acquired on `visibilitychange` → visible during a live session and released after completion/abandon.
- [ ] The end-of-phase beep is not replayed for phases that ended while hidden.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` platform section documents: no native Live Activity / Dynamic Island / lock-screen controls / background audio in a Telegram Mini App; what we do instead.
- [ ] Playwright with clock control (`page.clock`) covers hidden→visible across a phase boundary for rest and interval; parity spec file («Background timer»).
- [ ] Add a new spec file `webapp-frontend/e2e/scenarios/parity/background-timer.spec.ts` (helpers in `webapp-frontend/e2e/fixtures/parity.ts`, see `scenarios/parity/README.md`; do NOT append to `crimpd-parity.spec.ts`; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/SessionLiveScreen.tsx`, `IntervalLiveScreen.tsx`, `offlineSession.ts`, `phaseAudio.ts`, `wakeLock.ts`, `docs/CRIMPD_FULL_PARITY_8_5.md`.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `scenarios/parity/background-timer.spec.ts` («Background timer»); full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Push notifications for timers (bot reminders already exist). Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
