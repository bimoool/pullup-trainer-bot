# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #262
TITLE: CRIMPD P1 — Journal: edit and clone a logged session
URL: https://github.com/bimoool/pullup-trainer-bot/issues/262
PRIORITY: p1
TYPE: feature
BASE BRANCH: develop/current
BASE SHA: 7b88d7fc99e1900d1211f4c100bdd6a8971931d2
BRANCH: orch/issue-262
BATCH: 7 (task 5/5)
SELECTED AT: 2026-10-01 23:26 UTC

## Goal

Add Crimpd's «Edit Log» and «Clone Log» to the v2 Journal detail for sessions the user may safely change.

## Acceptance criteria

- [ ] Journal v2 detail shows «Изменить» and «Повторить (клонировать)» next to the existing safe delete.
- [ ] Edit allows changing set values, per-set effort/note, workout effort and comment, and date (not into the future) — ONLY for sessions that pass the same safety predicate as delete (Builder sessions independent of protected progression, PROJECT_SPEC §3); otherwise the button is hidden and the API returns 409 with a reason. Program-backed/STEP sessions are never edited by this path.
- [ ] Clone creates a new completed session for the user (date picker defaulting to today) with the same blocks/targets/logs copied, `source=backdated`, no progression side effects.
- [ ] API: `PATCH /api/v2/sessions/{id}` and `POST /api/v2/sessions/{id}/clone` with ownership (404), safety (409), validation; analytics and calendar reflect changes.
- [ ] pytest covers predicate, ownership, clone fidelity and no progression mutation; crimpd-parity.spec.ts gains a «Journal edit/clone» block.
- [ ] Add a `test.describe("Journal edit/clone")` block to `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (created by the campaign; runs at 320 and 390 px, light and dark where noted) covering the new user-visible contract; seed via `scripts/e2e_seed.py` + `scripts/e2e_seed_all.sh` if needed. Backend: focused pytest on real Postgres. Frontend: `npm run build && npm run test:unit`. The worker gate runs the full Playwright suite.
- [ ] `docs/CRIMPD_FULL_PARITY_8_5.md` rows for this capability updated (status + test evidence) and `docs/PROJECT_SPEC.md` updated where behaviour changes.

## Files / areas

`webapp-frontend/src/JournalV2.tsx`, new edit form, `apiV2.ts`; `app/web` v2 sessions routes, session service, delete-safety predicate reuse; tests.

## Tests required

Backend pytest (real Postgres) for every new/changed endpoint; frontend unit tests for pure helpers; `crimpd-parity.spec.ts` block «Journal edit/clone»; full Playwright suite via the worker's deterministic gate. Campaign: Crimpd 8.5 full parity (owner mandate 2026-10-02).

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Editing program-backed sessions (progression owner decision), legacy A/B edit changes. Production deploy, merge to `main`, changes to progression formulas/cascade, coins/GTO/WSF semantics, destructive migrations.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
