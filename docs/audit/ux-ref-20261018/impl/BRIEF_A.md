RUN MODE: LOCAL CODE
MODEL: STANDARD / SONNET
MODEL REASON: backend/domain change inside existing, well-specified plan model; no new architecture (owner asked for Sonnet executors)
SESSION: NEW
TASK TYPE: IMPLEMENTATION
BASE SHA: e2ed40e5da46e8a2a743fd4a69f0f9e9b4d1d8e0 (main, verified 2026-10-18); campaign tip b769de6 adds audit/contract docs only
BRANCH / WORKTREE: `ux/a-availability` / `/Users/kirillv./Documents/Claude Code/pullup-ux-a`
ACCESS: git, local Docker (test DB via `docker compose` in your worktree), shared venv, no network needed. Unverified: nothing external.
DELIVERABLE: pushed branch with backend + tests satisfying `CONTRACT_A_B.md`; checkpoint file `checkpoints/A.md`
TIMEBOX: first checkpoint ≤ 15 min (plan of attack + first failing tests); expected 1.5–3 days of active work in total; split into pushed slices
NEXT STATUS: first checkpoint pushed within 15 min of start
AUTHORIZED ACTIONS: edit files you own, run focused tests, commit, push your branch. No merge, no deploy.

# Task A — course availability backend (UX-01, UX-02, А/Б, actual schedule of an old connection)

Items: **UX-01** (a row must not offer «Начать» that cannot succeed), **UX-02** (future weeks: correct `available_from`, startable when allowed, crediting that future occurrence), **UX-08** (А/Б distinguishable: `session_variant`), **UX-32** (the plan actually has 3 per week for a pre-V5.6 connection — expose it as fact: `schedule`), UX-20 vanishes with UX-01.
Read: `docs/domain/PROGRAM_PLAN_V2.md` (§K1/K2 spacing, occurrences), `docs/domain/PULLUPS_V5_6.md` (§schedule, A/Б), `ACCEPTANCE_JOURNEYS_V2.md` J11/J12, backlog UX-01/02/08/32, `COMPLAINTS.md` §1.

## You own (edit only these)
`app/domain/plan_occurrence.py`, `app/services/plan_view.py`, `app/services/plan_convergence.py`, `app/services/plan_week.py`, plan/inclusion parts of `app/web/routes_v2.py` and `app/web/schemas_v2.py` (**only** `PlanItemResponse`, `ProgramInclusionResponse`, plan endpoints — another worker (C) edits the session/journal/analytics parts of the same two files; keep your hunks local, do not reformat, do not move code), `tests/**` related to plan/availability, new `tests/helpers/legacy_inclusion.py`.
**Do not edit** `webapp-frontend/**`, `scripts/e2e_seed*.{py,sh}` (B), session/journal/analytics code (C).

## Steps
1. **Slice 1 (checkpoint ≤ 15 min):** read the code path `GET /api/v2/plan` → `plan_view.py`; write the failing tests first: (a) after one main session today the second main occurrence has `start_allowed=false`, `blocked_reason="too_early"`, `available_from = last_start + 3 days`; (b) weeks +1…+4 rows have correct `available_from`/`state`, startable when allowed; (c) legacy-snapshot fixture (CONTRACT §5) → `schedule.sessions_per_week == 3`, `is_legacy`, 3 occurrences, 1 done; V5.6 inclusion → 2.
2. **Slice 2:** implement `start_allowed`/`blocked_reason` from the **same availability rule the start endpoint enforces** (reuse the function; do not duplicate the rule). Verify the start endpoint for a future-week occurrence: it must start (no 422) when spacing/access allow and completing it must credit **that** occurrence (J12); fix if not.
3. **Slice 3:** `session_variant`, `session_variant_basis`, `session_ordinal`: find how the Summary line «Следующая тренировка B» and the session detail «ОБЪЁМ A» are derived (progression cursor / sequence) and expose the same value for the next open main occurrence and project forward for later ones (`projected`). Null when it cannot be projected honestly.
4. **Slice 4:** `ProgramInclusionResponse.schedule` (+ `weekly_capacity`, document the formula in a docstring and a test with hand-computed numbers); `week_summaries` consistency test.
5. **Slice 5:** regression tests on aged data (seed-like profiles in tests) so that convergence stays idempotent (0 changes on a second run) for both legacy and V5.6 inclusions; history/progression untouched (assert).

## Acceptance (all must hold)
- Contract fields present, additive, typed; OpenAPI schema tests (if the repo has them) pass.
- Hand-computed examples in tests: (i) main on Mon → next available Thu; (ii) main on Sun of week N → week N+1 first occurrence available Wed (Sun+3); (iii) legacy 3/week: with the last main on Sat 17 Oct and 3-day spacing, occurrences 2 and 3 of the same week are `infeasible`/`too_early` accordingly (compute by hand, write the expected states); (iv) no change to the number of occurrences materialised for legacy.
- `ruff` clean; focused pytest green (`tests/test_services/*plan*`, `tests/test_web/*plan*`, `tests/test_domain/*`, your new files).
- Nothing outside your ownership list changed (`git diff --stat origin/campaign/ux-ref-20261018` shows only owned paths).
