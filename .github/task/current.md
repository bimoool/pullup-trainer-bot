# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #246
TITLE: Cover active-session recovery after background and reopen
URL: https://github.com/bimoool/pullup-trainer-bot/issues/246
PRIORITY: p1
TYPE: qa
BASE BRANCH: develop/current
BASE SHA: 90f63f8d18533cefa58f97d26f548ca630c095a7
BRANCH: orch/issue-246
BATCH: 3 (task 2/5)
SELECTED AT: 2026-09-30 22:28 UTC

## Goal

Verify and harden restoration of an active workout after the Mini App is backgrounded or reopened.

## Acceptance criteria

- [ ] Add an automated scenario that starts a session, records progress, simulates background/foreground, reloads the app, and resumes the same active session.
- [ ] Logged sets remain intact and are not duplicated.
- [ ] Timer-based state is reconciled from elapsed time rather than resetting on foreground.
- [ ] The restored screen is usable and does not show a blank or permanently loading state.
- [ ] Fix deterministic recovery defects found by the scenario without changing workout semantics.
- [ ] No production deploy or merge to `main`.

## Files / areas

`webapp-frontend/src/App.tsx`, live/timer screens, session persistence helpers, Telegram mock, and E2E scenarios.

## Tests required

A focused Playwright recovery scenario and relevant frontend unit tests. Existing session and offline suites must remain green.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Native iOS gestures, Telegram client defects, notification behavior, and new progression rules.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
