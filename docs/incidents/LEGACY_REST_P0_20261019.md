# P0: legacy STEP rest falls back to 90 seconds

## Verified scope

Production SHA verified via GitHub Actions: last successful `Production deploy (guarded)` apply
(run 39089754717, 2026-10-18) = `e2ed40e5da46e8a2a743fd4a69f0f9e9b4d1d8e0` (= origin/main; its tree is
identical to bd80bc9). Actual host HEAD / affected user and active-session counts were NOT read:
no production connection from this environment. No production mutation.

Legacy `_resolve_main_occurrence` emits A + B targets without workout_snapshot/protocol.
`TrainingSessionV2Service.synthesized_snapshot` deliberately has unknown rest (None).
`engine_plan_for` -> `fallback_block` therefore uses global default 90.
Old `LiveWorkoutScreen` uses user preferences A=240/B=180/big break=900 by default;
settings API still exposes those numbers. Existing legacy STEP role semantics are
block_a/block_b by inclusion exercise ID, not exercise display name. Non-STEP courses
and generic exercises must not inherit this fallback.

## Minimal new-start fix

`_stamp_live_start` passes a `snapshot_patch` to `TrainingSessionV2Service.stamp_new`, which freezes
known legacy STEP settings into the newly synthesized prescription before it is written (the snapshot
is write-once, S1 — a post-stamp `set_prescription_snapshot` is a silent no-op) and before v2 engine
initialization. Preferences use the same `or default` semantics as
settings API. Explicit existing prescription rests are retained. No DB schema change.
Generic default remains 90, V5.6 unchanged, session targets/credits/progression unchanged.
V1 phase advancement reads frozen block rest when no protocol is available; v1's existing
manual transition behavior between blocks is retained. V2 freezes A/B and inter-block gap.

Only actual new starts enter this code; idempotent repeated start/reopen do not. No completed
or already-active session snapshot / engine_plan is rewritten. Old active v2 sessions keep
the wrong rest until a separately reviewed recovery. Do not switch engines mid-session.
A user can wait the prescribed rest before submitting the next set, but automated timers
remain misleading; that is not a product fix. Cancel/restart decisions require checking
existing logs/credits and supported UI, not silent repair or marking completed.

## Verification

Real PostgreSQL: `tests/test_web/test_v2_live_engine.py::test_legacy_step_new_start_preserves_rest_preferences`
(defaults 240/180/900 and custom 300/210/600, frozen after a later preference change) plus
`tests/test_legacy_rest_hotfix.py`. The original patch version (freeze after stamp) passed its mocked
unit tests but FAILED these API tests (90 != 240): `set_prescription_snapshot` is write-once. Reverting
the fix again makes both API tests fail. V5.6, free-workout and full-suite results: see the PR.

## Read-only production inspection (run by capable release session)

Execute `legacy_rest_readonly.sql` using psql ON_ERROR_STOP. Counts are candidate populations,
not proof that every person experienced a short rest. Snapshots/plans identify actual persisted
90s; distinguish old backfill records from native live starts. Inspect deployed SHA first.

## Release handoff

Isolated branch fix/legacy-rest-p0-20261019 is based on bd80bc9 (no campaign UX/auth migrations).
Run focused DB tests, existing V5.6/Builder suites, v1 phase regression and required CI on final
SHA, then review and guarded production release under existing release permissions. First
verify live HEAD and compatible Alembic revision. Do not deploy campaign for this hotfix.
Deploy can fix future starts only; report existing active sessions separately for decision.
