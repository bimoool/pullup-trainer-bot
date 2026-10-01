# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #252
TITLE: Live session: result input shows unit and target hint
URL: https://github.com/bimoool/pullup-trainer-bot/issues/252
PRIORITY: p2
TYPE: ux
BASE BRANCH: develop/current
BASE SHA: 841f5996401f02877b2433c7db6c846ed323916a
BRANCH: orch/issue-252
BATCH: 5 (task 3/5)
SELECTED AT: 2026-10-01 05:33 UTC

## Goal

Make the live-session result input say what to enter: its label/accessible name and a hint follow the current set's target unit, instead of the generic «Результат».

## Acceptance criteria

- [ ] For a set whose target unit is `reps` (non-max block) the input header and `aria-label` read «Повторений» (same wording already used for max blocks); time (`s`) stays «Секунды», max stays «Повторений».
- [ ] When the current set has a target, a short hint under/next to the input shows it using the existing formatter (`formatTarget` / `formatNumber` in `blockFormat.ts`), e.g. the same text already shown in the plan line; no target (max) ⇒ no invented hint.
- [ ] The generic «Результат» label remains only as a fallback for units the screen does not know.
- [ ] The value sent to the API, set logging, offline queue and progression are unchanged.
- [ ] Existing E2E selectors that use the input's accessible name are updated in the same change; the full Playwright suite stays green.
- [ ] No production deploy or merge to `main`.

## Files / areas

`webapp-frontend/src/SessionLiveScreen.tsx`, `webapp-frontend/src/blockFormat.ts` (reuse only), frontend unit tests, live-session Playwright scenarios (`builder-execution.spec.ts`, `session-*.spec.ts`).

## Tests required

Frontend unit test for the label/hint selection (reps / time / max / unknown unit); Playwright assertion that a reps block shows «Повторений» and the target hint; `npm run build && npm run test:unit`; full E2E suite via the worker gate.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Effort-chip wording, new copy beyond the unit/target hint, redesign of the live screen, interval screen, backend or schema changes.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
