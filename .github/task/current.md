# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #238
TITLE: ORCH-TEST 3 — merge-path proof: create sandbox proof file
URL: https://github.com/bimoool/pullup-trainer-bot/issues/238
PRIORITY: p2
TYPE: infra
BASE BRANCH: orch-sandbox/orch2-merge-proof
BASE SHA: 367a13e1cfc02602bab0a2b6ea38c10873b1af48
BRANCH: orch/issue-238
BATCH: 1 (task 1/1)
SELECTED AT: 2026-09-30 06:14 UTC

## Goal

Create the file `sandbox/orch-proof/merge-proof.txt` containing exactly one line: `merge path proof from the ORCH worker`.

## Acceptance criteria

- [ ] `sandbox/orch-proof/merge-proof.txt` exists with exactly that line
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
- issue 'Out of scope': Any product code, docs, workflows, config.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
