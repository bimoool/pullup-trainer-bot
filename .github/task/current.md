# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #249
TITLE: Cover Telegram BackButton safety during a live workout
URL: https://github.com/bimoool/pullup-trainer-bot/issues/249
PRIORITY: p1
TYPE: qa
BASE BRANCH: develop/current
BASE SHA: 37741f98a8afeaf4bcf71c77cd6a95d23ca57837
BRANCH: orch/issue-249
BATCH: 5 (task 1/5)
SELECTED AT: 2026-10-01 05:05 UTC

## Goal

Cover Telegram BackButton behavior during a live workout so an accidental back action cannot silently lose the active session.

## Acceptance criteria

- [ ] Extend the Telegram E2E mock with a deterministic BackButton click trigger if one is not already available.
- [ ] Add an E2E scenario that starts a workout, records a set, triggers Telegram BackButton, and verifies the app does not silently discard the session.
- [ ] Cancellation leaves the same active session resumable with the recorded set intact.
- [ ] Confirmation completes at most once and shows a consistent summary.
- [ ] Existing visible navigation and live-session flows remain green.
- [ ] No production deploy or merge to `main`.

## Files / areas

`webapp-frontend/src/SessionLiveScreen.tsx`, `useBackButton.ts`, Telegram E2E mock, and live-session Playwright scenarios.

## Tests required

Focused Playwright coverage for cancel and confirm BackButton paths, plus relevant frontend unit tests.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Native iOS edge-swipe behavior, changing Telegram SDK policy, or changing workout/progression semantics.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
