# UX-EDITOR checkpoints

## Checkpoint 1 · 2026-10-18T17:53Z · phase 1 contract
Wrote `checkpoints/UX-EDITOR-contract.md` (data model, API, hand-computed examples a–e, tests, risks, split). No code changed.
Contract request R1: nullable `custom_plans.spec JSONB` (additive migration) — awaiting coordinator; needs chaining with WEB-AUTH migration.
Tests run: none (design only). Active minutes: ~25. Waiting: 0. Rework: 0. Next: stop; phase 2 after «continue».

## Checkpoint 2 · 2026-10-18T18:04Z · P2-1..P2-3 backend (domain, migration, services, endpoints, schedule)
Done: `app/domain/plan_spec.py` (PlanSpec, legacy derivation, edits), migration `c7e2a9d4b1f8` (custom_plans.spec only, down_revision b5d8e1f3a6c9), count reconciliation in `PlanConvergenceService._reconcile_spec_week` (only plans with spec; legacy plans keep the old path = zero change until first edit), `app/services/custom_plan_editor.py`, endpoints in `routes_v2_plan.py` (+ delimited block in `schemas_v2.py`; no main.py change needed, router already registered), `past_day` in `PlanScheduleService.reschedule` (UX-31).
Migration check (local seeded DB ue_editor: 625 users, 475 plan_items; NOTE: the seed contains 0 custom_plans, contrary to the coordinator note — I will add a legacy custom-plan seed in id range 941000+): `alembic downgrade -1` then `upgrade head` both OK, column removed/added, single head c7e2a9d4b1f8.
Tests: tests/test_plan_spec.py 14 passed; tests/test_web/test_custom_plan_editor.py 12 passed (examples a–e, row-id preservation on insert/delete, refusals, quota, past_day); plan-related suites green.
Existing test changed (minimal): tests/test_web/test_v2_plan_item_management.py — 3 move tests used the real weekday; with UX-31 `past_day` they fail on a Sunday. They now freeze «today» to Monday via `_freeze_monday` (intended behaviour changed, not weakened).
Rework: test helper expire_all broke fixtures (fixed with populate_existing). Waiting: ~6 min (seed/vite build in background). Active: ~14 min. Next: revert-proof runs, frontend (P2-4/5), seed + e2e.
