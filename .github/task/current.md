# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #265
TITLE: CRIMPD P1 — Live session: logging panel follows the timer; GET READY in the last 10 s of rest
URL: https://github.com/bimoool/pullup-trainer-bot/issues/265
PRIORITY: p1
TYPE: ux
BASE BRANCH: develop/current
BASE SHA: ab4d65724ff08aa380f22d3771cefee8934d7988
BRANCH: orch/issue-265
BATCH: 8 (task 2/5)
SELECTED AT: 2026-10-02 02:08 UTC

## Goal

Make the set-logging panel part of the timer flow: compact during work, expanded during rest long enough to log, with a visible «Приготовься» cue in the final 10 seconds of rest.

## Acceptance criteria

- [ ] During work (`go`) the logging panel is collapsed to one line (set n/N, target) with the primary «Готово» reachable; during rest ≥ 20 s it expands automatically to show value, effort and note for the just-finished set (editable until the next set starts); during short rest it stays collapsed but can be expanded manually.
- [ ] In the last 10 seconds of any rest the screen shows «Приготовься» with a countdown and the existing phase beep fires at the end (audio as already implemented; no new audio permissions).
- [ ] No change to stored data shape; the values entered during rest are the same set log (no duplicate set).
- [ ] Works offline and after reload/background (state derived from local phase machine timestamps).
- [ ] crimpd-parity.spec.ts «Live logging panel» block using a short-rest seed and fake timers / clock control where available; existing session-* specs green.
- [ ] Add a `test.describe("Live logging panel")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/SessionLiveScreen.tsx`, `offlineSession.ts`, `index.css`; e2e seed with short rest.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Live logging panel»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': New audio cues, vibration API. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
