# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #235
TITLE: Forward-port main hotfix #228 (admin user-list pagination) into develop/current
URL: https://github.com/bimoool/pullup-trainer-bot/issues/235
PRIORITY: p1
TYPE: bug
BASE BRANCH: develop/current
BASE SHA: 45bdef7d124f9f2bf118c62cd63249f20e95455f
BRANCH: orch/issue-235
BATCH: 1 (task 1/5)
SELECTED AT: 2026-09-30 04:37 UTC

## Goal

`develop/current` contains the admin user-list pagination fix that is already on `main` and in production (PR #228), so the next develop→main merge does not regress it.

## Acceptance criteria

- [ ] the change from `f80c7ff` (`app/bot/handlers/admin.py`, `app/bot/keyboards.py`, `tests/test_bot/test_admin_grants.py`) is applied on top of `develop/current` (`git cherry-pick -x f80c7ff`; resolve conflicts against develop/current code if any)
- [ ] the pagination tests from #228 pass on develop/current
- [ ] full `pytest -q` and `ruff check app/ tests/ scripts/` green
- [ ] no other behaviour change

## Files / areas

`app/bot/handlers/admin.py`, `app/bot/keyboards.py`, `tests/test_bot/test_admin_grants.py`

## Tests required

`pytest tests/test_bot/test_admin_grants.py -q` then full `pytest -q`.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Merging `main` itself into develop/current; any other main/develop reconciliation; deploys.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
