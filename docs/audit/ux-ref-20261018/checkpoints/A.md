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
