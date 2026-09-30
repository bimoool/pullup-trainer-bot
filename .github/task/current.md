# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #243
TITLE: ORCH start must surface an empty queue and recover on approval
URL: https://github.com/bimoool/pullup-trainer-bot/issues/243
PRIORITY: p1
TYPE: infra
BASE BRANCH: develop/current
BASE SHA: c99ab730d89476d0a1f0979bc6e11f1d13babdd3
BRANCH: orch/issue-243
BATCH: 2 (task 1/5)
SELECTED AT: 2026-09-30 20:29 UTC

## Goal

Make an owner `/orch start` with an empty executable queue report the idle state clearly and stop waiting silently.

## Acceptance criteria

- [ ] When an owner start reaches `none-ready`, #230 gets a clear message that no worker was dispatched and names the required owner action (`/orch approve` on a complete issue).
- [ ] The batch does not remain presented as actively coding after `none-ready`; its persisted state is safe for `/orch approve` to restart automatically.
- [ ] A later owner approval of a valid task starts planner → worker without requiring a second `/orch start` comment.
- [ ] Existing one-worker, owner-only, branch, hop, and batch-limit guards remain enforced.
- [ ] No production deploy or merge to `main` is added.

## Files / areas

`scripts/orch.py`, `scripts/orch_control.py`, `.github/workflows/orch-planner.yml`, orchestration tests and docs as needed.

## Tests required

Add deterministic tests for empty-queue owner start, dashboard/status output, and approval-driven restart. Existing orchestration tests must pass.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Creating product tasks, choosing product semantics, deploying production, or changing the batch limit.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
