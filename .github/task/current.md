# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #245
TITLE: Cover reconnect plus immediate workout completion race
URL: https://github.com/bimoool/pullup-trainer-bot/issues/245
PRIORITY: p1
TYPE: qa
BASE BRANCH: develop/current
BASE SHA: 67bb7d810fae01b98a309a394a815aeed00f1e28
BRANCH: orch/issue-245
BATCH: 3 (task 1/5)
SELECTED AT: 2026-09-30 22:18 UTC

## Goal

Prevent duplicate or missing workout data when connectivity returns and the user immediately completes a live session.

## Acceptance criteria

- [ ] Add an automated scenario: go offline, log a set, restore connectivity, immediately complete the session.
- [ ] The session completes exactly once and the summary contains every locally logged set exactly once.
- [ ] Repeated completion taps while reconnect is flushing cannot create duplicate completion requests or duplicate sets.
- [ ] If the current implementation fails, fix the race using the existing offline queue and idempotency model.
- [ ] Existing offline-session and live-session tests remain green.
- [ ] No production deploy or merge to `main`.

## Files / areas

`webapp-frontend/src/SessionLiveScreen.tsx`, `webapp-frontend/src/offlineSession.ts`, existing API/idempotency code, and `webapp-frontend/e2e/scenarios/session-offline.spec.ts`.

## Tests required

A deterministic Playwright regression for reconnect plus immediate completion, with focused unit tests if state coordination changes.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Offline architecture redesign, conflict-resolution policy changes, or progression-rule changes.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
