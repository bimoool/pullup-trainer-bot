# DOMAIN-V2 bounded machine acceptance — 2026-11-18 (#309)

This checkpoint maps the accepted journeys to existing tests and executes a bounded
synthetic J2/convergence check. It does **not** complete Wave 4 acceptance or cutover.
[#309](https://github.com/bimoool/pullup-trainer-bot/issues/309) and
[#302](https://github.com/bimoool/pullup-trainer-bot/issues/302) remain open.
No application, migration, flag, v1 path or release guard changes are included.

## Source and evidence labels

- Examined and executed source: `c28d549db5fb074050e2d5cf15b3e30598cdc1be`
  (`origin/main` after fetch); tree `5dfee2aea8cf55902e45df56d4ae918e9d0e9ee9`.
- This is the same tree as merged [PR #430](https://github.com/bimoool/pullup-trainer-bot/pull/430)
  head `0dede8f003e85a1bb79b91d0218d4da4e94be8ff`. Source comparison of
  `app/`, `tests/` and `webapp-frontend/` produced no differences.
- Wave 0 and the recorded #303–#308 implementation/integration checkpoints are
  verified ancestors, and those six implementation issues are closed. Ancestry
  does not certify that a historical checkpoint was its final accepted review
  head, nor acceptance of every fresh/aged journey or physical device behavior.
- **SOURCE_ONLY**: an assertion/test was located in source; no new execution of it
  is claimed here. Test names containing `jN` can refer to a local test catalog,
  so mapping below follows assertions, not the numeric name alone.
- **TARGETED_PASS**: the specifically named existing checks executed in this task.
- **EXISTING_CI**: earlier exact-head CI evidence reused with the tree boundary above.
  Aggregate counts do not prove every individual acceptance clause or every persona.
- **NOT_TESTED / UNKNOWN**: this checkpoint provides no execution evidence for that cell.
  In particular, simulated browsers do not establish physical **R** acceptance.

Contract basis: [acceptance J1–J12](../domain/ACCEPTANCE_JOURNEYS_V2.md),
[migration](../domain/MIGRATION_V2.md), [Program/Plan](../domain/PROGRAM_PLAN_V2.md),
[current product specification](../PROJECT_SPEC.md),
[implementation navigation](../IMPLEMENTATION_PLAN.md).
For new pull-up inclusions, [PULLUPS_V5_6](../domain/PULLUPS_V5_6.md) governs
prescription and progression. J4's `4 × 3 + max` is explicitly a **legacy-version**
criterion; it must not replace V5.6's block-specific signals. V5.6 golden M=0/10/25/50
examples and the resolved three-day spacing apply where appropriate. Historical
OD references are not a new blocker for these already authorized synthetic checks.

## Existing full-CI evidence reused, not rerun

The integration controller verified these logs on 2026-11-18 at 05:21 UTC, for
PR #430 head `0dede8f003e85a1bb79b91d0218d4da4e94be8ff`:

| Earlier proof | Observed result | Limit |
|---|---|---|
| [Backend job](https://github.com/bimoool/pullup-trainer-bot/actions/runs/44239659425/job/134584660716) | 3,782 passed, 2 skipped, twice | Existing full-suite evidence, not a new #309 run |
| [Main E2E job](https://github.com/bimoool/pullup-trainer-bot/actions/runs/44239658919/job/134584174489) | 632 passed, 9 skipped; 8 peer tests passed | Skips remain skips; no complete fresh/aged persona matrix inferred |
| [Fresh WebKit synthetic diagnosis](https://github.com/bimoool/pullup-trainer-bot/actions/runs/44239658919/job/134584174545) | Exit 0 on first attempt; `release-status.schema1`, `fresh-course`, `iphone-webkit`, `passed` | Synthetic browser evidence, not a physical iPhone/Telegram/watch result |
| [Native Codex source review](https://github.com/bimoool/pullup-trainer-bot/actions/runs/44239762835/job/134584574081) | Success, completed with no findings | Source review, not native device QA |

No backend or frontend full suite was rerun for this docs-only task. Current report
PR documentation checks and final integration review are separate integration work.

## Journey-to-test mapping and remaining cells

Every entry below is SOURCE_ONLY except explicitly identified focused runs.
The prior CI above remains useful evidence for its exact source, without upgrading
these partial mappings into complete journey acceptance. **All complete J1–J12
fresh/aged acceptance cells remain UNKNOWN in this report.**

| Journey / accepted observation | Existing source anchors | This checkpoint and concrete missing acceptance |
|---|---|---|
| J1: onboarding, 7-day trial, free course, prescription, plan/live/history/analytics/reopen | [Trial service](../../tests/test_services/test_onboarding_trial_guarantee.py); [free access API](../../tests/test_web/test_free_program_access.py); [V5.6 API](../../tests/test_web/test_v2_course_v5.py) `test_new_inclusion_uses_v5_6_rule_and_records_provenance`; [V5.6 E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts); [golden Builder E2E](../../webapp-frontend/e2e/scenarios/golden-journey.spec.ts) | SOURCE_ONLY + EXISTING_CI. The Builder journey is not the course journey. Still need a paired course trace proving all specified counts, categories, measured rounded minutes and reopen consistency; R UNKNOWN. |
| J2: aged state converges without history/entitlement loss; repeat is zero | [Plan convergence](../../tests/test_services/test_plan_convergence_v2.py) `test_aged_profile_converges_and_preserves_history`, `test_run_all_second_apply_has_zero_mutations`; [single-history rehearsal](../../tests/test_scripts/test_single_history_migration.py) `test_aged_database_converges_idempotently_without_touching_legacy_history`; [aged runtime repair](../../tests/test_services/test_aged_state_convergence.py) | TARGETED_PASS for the named plan/legacy modules and single direct rehearsal below; **partial J2**, not whole J2 PASS. Missing paired same-history fresh equivalence and Journal/Profile/Analytics totals across all aged personas, including expired/payer, mixed history, archived/deleted definitions and mid-session. |
| J3: exact 17-target W-ladder, order/rest, persistence and Journal labels | [Workout domain](../../tests/test_workout_definition.py) `test_w_ladder_is_17_explicit_sets_in_exact_order`; [API](../../tests/test_web/test_v2_workout_definition.py) `test_w_ladder_detail_and_catalog_show_explicit_sequence`; [Builder execution](../../webapp-frontend/e2e/scenarios/builder-execution.spec.ts) covers protocol execution | SOURCE_ONLY. Generic Builder E2E is not proof of the exact W-ladder journey. Full 17-set live → persisted targets → Journal sequence and all surfaces' labels not established here. |
| J4: legacy 4 working + max persistence; current V5.6 exact recipes | [Legacy prescription domain](../../tests/test_course_prescription.py); [legacy API](../../tests/test_web/test_v2_course_prescription.py); [V5.6 golden examples](../../tests/test_pullups_v5.py) `test_m0_assisted_example`, `test_m10_qualifies_immediately_with_transition_volume`, `test_m25_example`, `test_m50_start_cap_only`; [course engine](../../tests/test_web/test_v2_course_v5_engine.py); [course E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts) | SOURCE_ONLY. Keep version boundaries explicit. The B continuation E2E is conditional on `E2E_JOURNEY_TG`; aggregate green CI does not prove that conditional continuation ran. All golden profiles' end-to-end persistence not established here. |
| J5: automatic deadlines, background return, pause/reload and audio offsets | [Shared vectors](../../tests/test_live_engine_vectors.py); [engine API](../../tests/test_web/test_v2_live_engine.py); [offline reopen](../../tests/test_web/test_v2_live_engine_offline_reopen.py); [engine E2E](../../webapp-frontend/e2e/scenarios/live-engine-v2.spec.ts), deadline/background/pause cases | SOURCE_ONLY + EXISTING_CI. Physical background return at ±1 s and audible/on-device offsets remain UNKNOWN; no watch proof. |
| J6: custom weekly volume 2/2/0/2, one occurrence credit, named editable Journal | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j6_custom_plan_2_2_0_2_2_0_exact_occurrence_counts`; [golden E2E](../../webapp-frontend/e2e/scenarios/golden-journey.spec.ts) | SOURCE_ONLY. API checks exact zero weeks and credit; golden E2E adds a Builder workout to a pool. A mapped UI execution of the exact custom-plan vector through editable Journal is still missing. |
| J7: direct start and clone do not credit a plan | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j7_direct_start_credits_nothing`, `test_clone_never_credits_a_plan_item`; [session API](../../tests/test_web/test_v2_training_session_v2.py) direct/clone checks | SOURCE_ONLY. No new direct-start/clone UI journey or paired fresh/aged execution here. |
| J8: manual existing workout identity, edit/repeat/open, workout/exercise history | [Session API](../../tests/test_web/test_v2_training_session_v2.py) `test_j8_post_factum_existing_workout_keeps_identity_and_is_editable`, `test_j8_history_survives_rename_and_archive`; [workout link API](../../tests/test_web/test_v2_session_workout_link.py); [Journal E2E](../../webapp-frontend/e2e/scenarios/journal-v2.spec.ts) | SOURCE_ONLY. Combined manual-entry UI → all three actions → both analytics panels on fresh/aged profiles not established here. |
| J9: external run 45 min, category/count/minutes, edit, no panel/plan change | [Journal create/list API](../../tests/test_web/test_v2_journal_log.py) `test_freeform_activity_is_stored_and_listed`; [canonical category API](../../tests/test_web/test_canonical_history.py) `test_external_activity_has_a_deterministic_category_and_display_name`; [external edit API](../../tests/test_web/test_v2_training_session_v2.py) `test_external_activity_edit_duration_type_and_date_keeps_duration`; new [nonempty history/custom-plan isolation API](../../tests/test_web/test_j9_external_activity_isolation.py) | Follow-up TARGETED_PASS at source base `047c9c5`: **3 passed, 1 warning in 8.63 s**, exit 0, no skips. Existing cases establish running45 identity/category and editable activity facts. The new case adds an actual API-created two-occurrence custom plan and prior manual history: running45 then cycling60 leaves the entire existing exercise payload, plan API, custom-plan/occurrence rows, prior manual session/recipe/targets/logs unchanged; global counts/minutes move 1/30 → 2/75 → 2/90 and activity identity stays fixed without plan credit. The warning is an unsuppressed existing Starlette 422 deprecation in the adjacent validation case. This fixture has no course inclusion/progression or credited completion; those preservation claims, full UI, paired fresh/aged personas and full J9 remain UNKNOWN. |
| J10: edit date/value moves Journal and analytics week, preserves duration/totals | [Session API](../../tests/test_web/test_v2_training_session_v2.py) `test_date_edit_of_live_session_keeps_measured_duration`; [weekly metrics API](../../tests/test_web/test_v2_analytics_metrics.py) `test_weekly_series_for_both_metrics_and_exclusions`; [history edit E2E](../../webapp-frontend/e2e/scenarios/session-progression-edit.spec.ts) | SOURCE_ONLY. Separate date, weekly-series and edit assertions do not prove one combined previous-week move with unchanged totals and changed exercise value on both profile types. |
| J11: Mon→Thu spacing, all start paths, infeasible capacity, manual violation flag | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j11_monday_main_wednesday_rejected_thursday_allowed`, `test_k2_fresh_wednesday_third_main_is_infeasible`; [V5.6 API](../../tests/test_web/test_v2_course_v5.py) `test_v5_main_start_respects_main_spacing`; [V5.6 E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts) | SOURCE_ONLY; targeted aged-plan module also passed its spacing assertion. Complete bot/legacy/v2/manual-flag/UI acceptance trace remains UNKNOWN. |
| J12: +1…+4 visibility; future start and credit, current week unchanged | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j12_future_week_occurrence_starts_and_credits_itself`; [future-week API](../../tests/test_web/test_v2_plan_future_weeks.py); [week UI](../../webapp-frontend/e2e/scenarios/plans-plan-week.spec.ts) | SOURCE_ONLY. Some future-week tests check the link at start; only completion/unchanged-current assertions can prove final credit. No combined four-future-week UI completion trace executed here. |

Cross-cutting display requirements (no raw slug/id, fractional workout or fake zero
target; consistent names on all six surfaces) are not certified globally by locating
a label test or by an aggregate CI count. No source absence above is a claim that
all possible tests were exhaustively searched; these are concrete acceptance
**evidence gaps** to resolve before writing any additional tests.

## Focused execution and isolation

The existing local environment was loaded without printing its values. Both the
PostgreSQL and Redis URL hosts were asserted to be `localhost` or `127.0.0.1`.
The existing PostgreSQL role was used. Before pytest, the administrative catalog
was queried to assert the shared default `pullup_test` already existed: this
prevents `tests/conftest.py::_ensure_database_exists` from creating it. No tests
were pointed at that shared database; its tables were not read or truncated.

Two independently created targets used unique `pullup_accept309_20261118_…`
names: one for ordinary pytest and one fresh database for the direct rehearsal.
`DATABASE_URL` and `TEST_DATABASE_URL` were overridden to each owned target, and
`BOT_TOKEN=ci-test-token` was set for child processes. The conftest migration and
TRUNCATE fixtures applied only to the owned pytest target. No Docker was needed.

The selected tests, imported helpers, conftest, migration environment and fixture
SQL were inspected before execution. The migration tests' normal `scratch_dsn`
fixture uses `DROP DATABASE … WITH (FORCE)`. To avoid it, the existing aged-history
test function was invoked directly with the second owned database's URL. The test
function and all its assertions were unchanged; **this is not a whole-file pytest
pass**. No schema downgrade/rollback test was selected.

The exact child test commands were as follows, using the existing environment's
Python with the isolated environment overrides described above. URLs and local
private paths are intentionally omitted.

```bash
python -m pytest -q tests/test_services/test_plan_convergence_v2.py tests/test_services/test_legacy_convergence.py
python -c 'from tests.test_scripts.test_single_history_migration import test_aged_database_converges_idempotently_without_touching_legacy_history as check; import os; check(os.environ["DATABASE_URL"]); print("EXISTING AGED HISTORY TEST PASS")'
```

| Executed check | Actual result | Assertions supported |
|---|---|---|
| Entire `test_plan_convergence_v2.py` (8 tests) + `test_legacy_convergence.py` (6 tests) | **14 passed in 12.35 s**, exit 0; no skips | Past aggregates retained; current credits in performed order; unchanged session/history fingerprint, subscription cache and program access; progression/snapshot preserved; fresh occurrence no-op; all-user dry/apply/reapply gives zero second mutations; legacy copy uniqueness, edit idempotence and supersession. Synthetic deletion/reset cases are confined to test fixtures. |
| Direct existing aged single-history rehearsal, one case on its own fresh target | **EXISTING AGED HISTORY TEST PASS**, exit 0 | Migrate pre-#308 aged fixture to head; legacy/subscription fingerprints unchanged; dry-run leaves summary unchanged; deterministic binding/replacement; canonical count remains 5; missing deleted elective not resurrected; apply-again summary/revisions unchanged and `RESULT-JSON.mutations == 0`. |
| Cleanup of both targets | **PASS**, each after assertions | Expected task-specific name and existing role ownership; zero `pg_stat_activity` clients; plain DROP only, no FORCE and no session termination. No task server or daemon was started. |

The output summary above is sufficient public evidence; raw local logs and
synthetic fixture rows are not published. No genuine invariant failure occurred,
so no application repair or new test was needed.

## Migration-clause disposition and remaining acceptance

| Migration clause | Evidence state after this checkpoint | Remaining item |
|---|---|---|
| §3 deterministic backfill and apply-again zero | TARGETED_PASS for the selected history runner; plan runtime PASS | No claim that every backfill ambiguity/type or migration was separately rerun |
| §4 single canonical history / legacy dual-write | TARGETED_PASS for six service tests and the direct aged rehearsal | Cross-view Journal/Profile/Analytics totals across all personas and cutover readiness still UNKNOWN |
| §5 aged plan convergence / history credits | TARGETED_PASS for eight plan service tests | Complete fresh-equivalence for the same events across the rehearsal persona set still UNKNOWN |
| §6 in-flight v1 and cached old clients | SOURCE_ONLY contract; NOT_TESTED in this task | Old bundle/offline queues, active v1 completion at cutover, new v2 starts; keep v1 until separate acceptance |
| §7 subscription/access preservation | TARGETED_PASS for exact fixture fingerprints/cache/access assertions | Not a global audit of all campaign migration writes or all entitled accounts; full persona before/after comparison still required |
| §8 rehearsal and rollback | Partial synthetic migration/convergence PASS only | No production-shaped dump used, no restore drill, no staging cutover or flag change; mandatory full rehearsal remains incomplete |
| Physical R, native Telegram, audible timer and watch | UNKNOWN | Device evidence remains separate; no owner manual QA, new chat or relay requested by this task |

Next acceptance work should attach exact criterion-level before/after evidence to
the missing cells above, reuse existing tests first, and add only tests that cover
a demonstrated gap. The selected synthetic checks can proceed independently of
native/admin capabilities. This report neither authorizes nor performs production
migration, deploy, rollback, freeze/retirement, legacy queue work, account changes,
credential provisioning or paid messages. Wave 4 sign-off and issue closure remain
separate decisions after their actual evidence is complete.
