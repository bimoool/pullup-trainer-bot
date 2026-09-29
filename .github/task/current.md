# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #231
TITLE: ORCH-TEST 1 — worker smoke: create sandbox hello file
URL: https://github.com/bimoool/pullup-trainer-bot/issues/231
PRIORITY: p1
TYPE: infra
BASE BRANCH: orch-sandbox/orch1-test
BASE SHA: 69df10a54f77568cf44282d62f62571ec752a456
BRANCH: orch/issue-231
BATCH: 1 (task 1/2)
SELECTED AT: 2026-09-29 19:10 UTC

## Goal

Create the file `sandbox/orch-smoke/hello.md` containing exactly one line: `hello from the ORCH-1 worker`.

## Acceptance criteria

- [ ] `sandbox/orch-smoke/hello.md` exists with exactly that line
- [ ] no other files changed

## Files / areas

Not specified — locate via `.claude/skills/codebase-map` and real code.

## Tests required

No new tests; the workflow runs ruff + pytest as usual.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Any product code, docs, workflows.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
