# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #257
TITLE: CRIMPD P1 — Live session: workout effort, session note and labelled per-set effort
URL: https://github.com/bimoool/pullup-trainer-bot/issues/257
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 8dbee8b922cf145854a540bbeb49b2c6d6d3bb1d
BRANCH: orch/issue-257
BATCH: 6 (task 5/5)
SELECTED AT: 2026-10-01 21:15 UTC

## Goal

Let the user rate the whole workout and leave a note when finishing a live session, and make per-set effort understandable — matching Crimpd's «How hard was this set?» and Log Workout review.

## Acceptance criteria

- [ ] Per-set effort chips keep the stored 1–5 values but show words under/with the numbers (1 Очень легко · 2 Легко · 3 Средне · 4 Тяжело · 5 Предел) and the prompt «Насколько тяжело было?»; stored values unchanged.
- [ ] Before final completion (the «Завершить» path after the last block), a short review step asks «Как прошла тренировка?» (same 1–5 scale, optional) and «Заметка» (optional), then completes.
- [ ] `POST /api/v2/sessions/live/{id}/complete` accepts optional `effort` (1–5) and `comment` (≤1000 chars), validated; stored on `TrainingSession`; idempotent repeat calls do not overwrite with nulls; offline queue (`offlineSession.ts`) carries them.
- [ ] Journal v2 detail shows the saved workout effort and note (already rendered — verify).
- [ ] Exactly-once completion, abandon path and offline guarantees unchanged (existing session-* E2E stay green).
- [ ] crimpd-parity.spec.ts gains a «Live effort» block (labelled chips, review step, values visible in Journal).
- [ ] Add a `test.describe("Live effort")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/SessionLiveScreen.tsx`, `SessionSummaryScreen.tsx`/`PlanSessionFlow.tsx`, `offlineSession.ts`, `apiV2.ts`; `app/web/schemas_v2_session.py`, live session service/route; pytest for validation and idempotency.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Live effort»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Changing progression inputs (effort does not affect progression). Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
