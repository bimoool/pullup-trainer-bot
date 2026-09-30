# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #244
TITLE: Automate critical iPhone-width layout regression coverage
URL: https://github.com/bimoool/pullup-trainer-bot/issues/244
PRIORITY: p1
TYPE: qa
BASE BRANCH: develop/current
BASE SHA: 050687384d0d614b59c346a6d893644b639674ad
BRANCH: orch/issue-244
BATCH: 3 (task 1/5)
SELECTED AT: 2026-09-30 22:09 UTC

## Goal

Add automated mobile viewport coverage for the critical Mini App navigation and layout so iPhone-width regressions fail CI.

## Acceptance criteria

- [ ] Playwright runs a focused critical-flow project at representative 320px, 375px, and 390px mobile widths.
- [ ] Tests cover all five bottom-navigation tabs and assert that labels and primary controls are visible without horizontal page overflow.
- [ ] The test exercises both light and dark Telegram theme parameters using the existing mock.
- [ ] Any deterministic layout defect exposed by the tests is fixed without changing product behavior.
- [ ] Runtime remains bounded: reuse existing seeded state and avoid duplicating the full desktop suite at every viewport.
- [ ] No production deploy or merge to `main`.

## Files / areas

`webapp-frontend/e2e/playwright.config.ts`, focused E2E scenarios/fixtures, and layout CSS only if a regression is reproduced.

## Tests required

Run the new focused mobile Playwright scenarios plus existing frontend unit tests. The new assertions must fail if tab labels are clipped or the page gains horizontal overflow.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Real iPhone, keyboard behavior, Dynamic Type, gestures, and visual redesign.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
