# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #241
TITLE: ORCH-2 live proof: owner GitHub UI event to sandbox merge and stop
URL: https://github.com/bimoool/pullup-trainer-bot/issues/241
PRIORITY: p2
TYPE: infra
BASE BRANCH: orch-sandbox/orch2-ui-proof
BASE SHA: 25a5bc99b641dae45e431e5a3434a64d0e2ea739
BRANCH: orch/issue-241
BATCH: 1 (task 1/1)
SELECTED AT: 2026-09-30 07:08 UTC

## Goal

Create only `sandbox/orch-proof/owner-ui-proof.txt` containing exactly one line: `owner GitHub UI dispatcher proof`.

## Acceptance criteria

- [ ] `sandbox/orch-proof/owner-ui-proof.txt` contains exactly `owner GitHub UI dispatcher proof` followed by a newline.
- [ ] No other files changed by the worker.

## Files / areas

Not specified — locate via `.claude/skills/codebase-map` and real code.

## Tests required

The existing worker workflow runs ruff and pytest; no new product tests needed for this proof text file.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Product code, workflows, orchestration state, configuration, deployments, changes to other branches.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
