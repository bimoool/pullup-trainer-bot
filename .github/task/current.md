# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #264
TITLE: CRIMPD P1 — Live session: add an extra set and pause/resume
URL: https://github.com/bimoool/pullup-trainer-bot/issues/264
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 512b20dd9a27a259dc9fd315d051c5621aea99fd
BRANCH: orch/issue-264
BATCH: 8 (task 1/5)
SELECTED AT: 2026-10-02 01:37 UTC

## Goal

Let users do one more set than prescribed and pause/resume the live workout, as Crimpd's player allows.

## Acceptance criteria

- [ ] During a reps/time/max block, after the last prescribed set, the user sees «+ Ещё подход» which records an extra set (not counted as a planned target; flagged `is_extra` or equivalent additive field) — available offline via the local phase machine.
- [ ] A pause button freezes the rest/get-ready countdown; «Продолжить» resumes with the remaining time; pause state survives reload/background (stored in the local session snapshot, reconciled with server on sync).
- [ ] Interval blocks: pause is not offered if the server-clock interval model cannot pause safely — documented in the UI by simply not showing it (no fake).
- [ ] Progression ignores extra sets unless current rules already consider all logs (document which in PROJECT_SPEC); exactly-once completion and `sets:batch` idempotency unchanged.
- [ ] pytest for extra-set persistence/idempotency; crimpd-parity.spec.ts «Live extra set & pause» block; existing session-* specs green.
- [ ] Add a `test.describe("Live extra set & pause")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/SessionLiveScreen.tsx`, `offlineSession.ts`, `apiV2.ts`; live session service/routes, additive migration if a flag is needed; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Live extra set & pause»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Rep-level timer, skipping exercises out of order. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
