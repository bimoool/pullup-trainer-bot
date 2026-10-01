# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #253
TITLE: Cover leaving Summary after a live session (no blank or stale screen)
URL: https://github.com/bimoool/pullup-trainer-bot/issues/253
PRIORITY: p2
TYPE: qa
BASE BRANCH: develop/current
BASE SHA: f5a0e953a7615d7c35a69a70a30aac4913a635c3
BRANCH: orch/issue-253
BATCH: 5 (task 4/5)
SELECTED AT: 2026-10-01 05:43 UTC

## Goal

Automate the iPhone QA checklist item §5 "Leaving Summary (button or Back) lands on a sensible screen, not a blank/stale one" for a plan-started live session.

## Acceptance criteria

- [ ] Playwright scenario: start a plan session from «Планы», log a set, complete it, reach Summary.
- [ ] On Summary the Telegram BackButton mock is hidden (or, if visible, triggering it does not re-open the finished live session or re-send complete).
- [ ] Pressing Summary's close button lands on the screen the code currently returns to (the plan flow's `onClose` target), which renders real content (no blank page, no spinner stuck, no error banner) and reflects the completed session where that screen shows session state.
- [ ] After leaving Summary, reopening the same plan item does not resurrect the finished session as active.
- [ ] Runs at 390px (desktop project is fine as well); no console errors / failed API calls beyond those the existing fixtures already tolerate.
- [ ] If the scenario exposes a deterministic defect (stale BackButton handler, blank screen), fix it minimally in the same task without changing workout/progression semantics.
- [ ] No production deploy or merge to `main`.

## Files / areas

`webapp-frontend/e2e/scenarios/` (new focused spec or extension of a plans/session spec), Telegram E2E mock in `webapp-frontend/e2e/fixtures/`, `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if a dedicated seed is needed, `SessionSummaryScreen.tsx` / `PlanSessionFlow.tsx` / `useBackButton.ts` only for a minimal fix.

## Tests required

The new Playwright scenario; existing frontend unit tests; full E2E suite via the worker gate.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Adding a BackButton to Summary, changing where Summary navigates, native iOS swipe behaviour, Journal/Analytics content checks (covered by `golden-journey.spec.ts`).

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
