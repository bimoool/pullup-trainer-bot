# Checkpoint log — executor A (availability backend)

## CP1 — plan + first failing tests
- Time: see commit date. Active ~20 min, waiting ~1 min, rework 0.
- Findings: `derive_occurrence_states` already yields too_early / infeasible with global `available_from`
  (last main start + 3, same `available_from`/`is_too_early` as `MainSpacingService.status`); the gap is that the
  response exposes no single `start_allowed`. Start endpoint = K1 (`require_main_start_allowed`, admin bypass) +
  `ProgramAccessService.training_parts_allowed`; plan will reuse both.
- Plan: S2 `start_allowed`/`blocked_reason` in `PlanViewService` (+`now`, `bypass_spacing` params from route);
  S3 `session_variant*`/`session_ordinal` from V5.6 `next_role`, projected by alternation, completed rows from the
  credited session snapshot; S4 `ProgramInclusionResponse.schedule` + `weekly_capacity` (domain, added);
  S5 regression on aged data.
- Added: `tests/helpers/legacy_inclusion.py`, `tests/test_web/test_v2_plan_availability.py` (9 red: missing fields),
  `weekly_capacity()` in `app/domain/plan_occurrence.py`.
- Contract note: `blocked_reason` for `awaiting_assessment` rows is not in the vocabulary; will emit
  `"awaiting_assessment"` (additive) and file a contract request.
- Next: implement S2.

## CP2 / FINAL — slices 2-5 done
- Active ~60 min since CP1; waiting ~4 min (test runs); rework: 2 test-side fixes (week without GET -> StopIteration,
  tautological credit assertion), no code rework.
- Summary: `PlanItemResponse` gets `start_allowed`, `blocked_reason`, `session_variant`, `session_variant_basis`,
  `session_ordinal`; `ProgramInclusionResponse.schedule` (+ `weekly_capacity`, domain `weekly_capacity()`).
  `start_allowed` is computed in `PlanViewService` with the same inputs the start uses: access via
  `ProgramAccessService.training_parts_allowed`, rest via the same `available_from`/`is_too_early` that
  `MainSpacingService` uses (state derivation), admin bypass (`settings.is_admin`). `available_from` and future-week
  states/starts were already correct in the engine (hand-computed tests pin them; J12 credit asserted). Variant:
  V5.6 `next_role` for first open main row (actual), alternation after (projected), credited rows from the session
  recipe `workout_role`; legacy -> null. No migration; no change to `derive_slots`, history, progression.
- Files: app/domain/plan_occurrence.py, app/services/plan_view.py, app/web/routes_v2.py, app/web/schemas_v2.py,
  tests/helpers/{__init__,legacy_inclusion}.py, tests/test_web/test_v2_plan_availability{,_v56}.py, this file,
  A-contract-request.md.
- Revert proof: with the `too_early` branch of `_start_availability` disabled, 6 tests fail (list in run), restored.
- Open risks: `blocked_reason="awaiting_assessment"` beyond the contract enum (see A-contract-request.md);
  infeasible rows are non-startable by contract although the start endpoint itself would accept them when K1 allows.
- Verify (coordinator): in worktree, `BOT_TOKEN=x DATABASE_URL=postgresql+asyncpg://u:p@localhost/db`
  `.venv-ux312/bin/pytest tests/test_web/test_v2_plan*.py tests/test_web/test_v2_program_inclusions.py tests/test_web/test_v2_course_v5.py tests/test_services/test_plan_convergence_v2.py tests/test_plan_occurrence.py -q`
  and `.venv-ux312/bin/ruff check app/ tests/`.
