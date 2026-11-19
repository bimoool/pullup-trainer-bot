# DOMAIN-V2 bounded machine acceptance — 2026-11-18 (#309)

This checkpoint maps the accepted journeys to existing tests and executes a bounded
synthetic J2/convergence check. It does **not** complete Wave 4 acceptance or cutover.
[#309](https://github.com/bimoool/pullup-trainer-bot/issues/309) and
[#302](https://github.com/bimoool/pullup-trainer-bot/issues/302) remain open.
No application, migration, flag, v1 path or release guard changes are included.
The follow-ups add three acceptance tests with separate evidence limits.

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

No backend or frontend full suite was rerun for the original report-only task. Current report
PR documentation checks and final integration review are separate integration work.

## Historical v1 Mini App bundle against the current API

The frontend was built with `npm ci` and `npm run build` from
`020ca64e05f35096dca4d449350d2db395b157ba`, the parent of the Live Engine v2
screen introduction. Its built JavaScript SHA-256 was
`3e6909b43b3f2ffe66c5ae027a400e47519a0fbc4b3b32cccd895e5083553164`.
The API ran from `d230ea984835638fbe48000b635e0c24ea1b230e` and served that
historical bundle from the same loopback origin. The only fixture substitutions
were the Telegram bridge and test identity. HTTP and PostgreSQL were real.

On a migration-only PostgreSQL target, six synthetic users were seeded with
`scripts.e2e_seed.py session_recovery`. The original scenarios ran in Chromium
155 at 320 and 390 px, with one worker and no retries.

- The [offline-set scenario](https://github.com/bimoool/pullup-trainer-bot/blob/020ca64e05f35096dca4d449350d2db395b157ba/webapp-frontend/e2e/scenarios/parity/live-set-nav.spec.ts)
  ran in two themes at each width. It queued the first result offline and
  synchronized it after reconnect. Reopening the set kept its value, and each
  completed session stored `[8, 5, 4]` in order.
- The [offline-finish scenario](https://github.com/bimoool/pullup-trainer-bot/blob/020ca64e05f35096dca4d449350d2db395b157ba/webapp-frontend/e2e/scenarios/parity/live-finish.spec.ts)
  reopened the Mini App after queuing completion and closing it offline. Each
  width produced a single successful completion with the original note.

**Result — 6 passed in 17.9 s, no skips.** A separate database check found six
unique completed v1 sessions, six distinct plan credits, all twelve set values
and both completion notes. The owned target was removed after checking ownership
and zero clients. This is machine evidence for the historical bundle under
MIGRATION_V2 §6. Real Telegram WebView and staging cutover rehearsal remain open.

## Journey-to-test mapping and remaining cells

Every entry below is SOURCE_ONLY except explicitly identified focused runs.
The prior CI above remains useful evidence for its exact source, without upgrading
these partial mappings into complete journey acceptance. **All complete J1–J12
fresh/aged acceptance cells remain UNKNOWN in this report.**

| Journey / accepted observation | Existing source anchors | This checkpoint and concrete missing acceptance |
|---|---|---|
| J1: onboarding, 7-day trial, free course, prescription, plan/live/history/analytics/reopen | [Trial service](../../tests/test_services/test_onboarding_trial_guarantee.py); [free access API](../../tests/test_web/test_free_program_access.py); [V5.6 API](../../tests/test_web/test_v2_course_v5.py) `test_new_inclusion_uses_v5_6_rule_and_records_provenance`; [V5.6 E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts); [golden Builder E2E](../../webapp-frontend/e2e/scenarios/golden-journey.spec.ts) | TARGETED_PASS at `032626d`: the fresh V5.6 browser journey records both blocks of A, checks the named Journal entry and reports its one completed occurrence after reload. Analytics then shows one workout in «Подтягивания» and the actual stored duration rounded to nonzero minutes; the API totals, category and browser display agree. Migration-only Chromium: 1 focused case passed. Trial/access proof remains in the separate service/API tests; the paired aged trace, separate B continuation and physical-device evidence remain open. |
| J2: aged state converges without history/entitlement loss; repeat is zero | [Plan convergence](../../tests/test_services/test_plan_convergence_v2.py) `test_aged_profile_converges_and_preserves_history`, `test_run_all_second_apply_has_zero_mutations`; [single-history rehearsal](../../tests/test_scripts/test_single_history_migration.py) `test_aged_database_converges_idempotently_without_touching_legacy_history`; [aged runtime repair](../../tests/test_services/test_aged_state_convergence.py) | TARGETED_PASS for the named plan/legacy modules and single direct rehearsal below; **partial J2**, not whole J2 PASS. The paired regression below establishes current/future plan equivalence for one legacy representation pair. The follow-up at `45eccac` also verifies two workouts in Journal, Profile and Analytics and 80 measured minutes in Analytics for both. The paid and expired variants below cover the same plan representation and check entitlement preservation. A separate single-profile regression at `12805e8` preserves an archived workout card during mixed-history convergence across calendar boundaries. The paired mixed-history, archived/deleted-definition and mid-session matrix remains UNKNOWN. |
| J3: exact 17-target W-ladder, order/rest, persistence and Journal labels | [Workout domain](../../tests/test_workout_definition.py) `test_w_ladder_is_17_explicit_sets_in_exact_order`; [API](../../tests/test_web/test_v2_workout_definition.py) `test_w_ladder_detail_and_catalog_show_explicit_sequence`; [J3 fresh-install browser case](../../webapp-frontend/e2e/scenarios/fix-wave1/fresh-install-content.spec.ts) | MACHINE_PARTIAL. A new plan-row assertion reproduced the missing recipe on `45eccac`: the row showed only the name, 0/1 and Start. With the canonical recipe added, all four fresh-install Chromium cases pass on a database provisioned only by migrations. W-ladder shows the exact recipe in Detail, on the plan row before and after reload, and on the direct pre-screen. The v2 engine plan specifies 16 rests of 10 seconds; all 17 live targets are checked and submitted; after reload, the single Journal entry shows the persisted plan and result in order. The test skips waits. Elapsed rest timing and physical-device evidence remain outside this run. |
| J4: legacy 4 working + max persistence; current V5.6 exact recipes | [Legacy prescription domain](../../tests/test_course_prescription.py); [legacy API](../../tests/test_web/test_v2_course_prescription.py); [V5.6 golden examples](../../tests/test_pullups_v5.py) `test_m0_assisted_example`, `test_m10_qualifies_immediately_with_transition_volume`, `test_m25_example`, `test_m50_start_cap_only`; [course engine](../../tests/test_web/test_v2_course_v5_engine.py); [course E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts) | TARGETED_PASS for V5.6 on `6be2d38`. A and the opt-in B continuation each passed in Chromium on a single synthetic profile. After A, only its performed date was shifted by three days in the isolated database to model the rest period. B confirmed 10×5 volume, five strength sets, 60-second volume rest and progression to 11×5. PostgreSQL retained all 15 B values in order, with distinct A and B occurrence credit. The legacy and remaining golden-profile scope still uses the source anchors. |
| J5: automatic deadlines, background return, pause/reload and audio offsets | [Shared vectors](../../tests/test_live_engine_vectors.py); [engine API](../../tests/test_web/test_v2_live_engine.py); [offline reopen](../../tests/test_web/test_v2_live_engine_offline_reopen.py); [engine E2E](../../webapp-frontend/e2e/scenarios/live-engine-v2.spec.ts), deadline/background/pause cases | SOURCE_ONLY + EXISTING_CI. Physical background return at ±1 s and audible/on-device offsets remain UNKNOWN; no watch proof. |
| J6: custom weekly volume 2/2/0/2, one occurrence credit, named editable Journal | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j6_custom_plan_2_2_0_2_2_0_exact_occurrence_counts`; [custom plan browser scenario](../../webapp-frontend/e2e/scenarios/custom-plan-journey.spec.ts) | Follow-up TARGETED_PASS on source base `72a48da`: Chromium creates a four-week custom plan for a seeded owned workout, sees 2/2/0/2 rows, completes a live session and sees exactly one credited occurrence. Journal shows one named entry with editable 8/7 set values. This covers creating the plan and opening the edit form. Workout definition creation and paired/device acceptance remain separate. |
| J7: direct start and clone do not credit a plan | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j7_direct_start_credits_nothing`, `test_clone_never_credits_a_plan_item`; [session API](../../tests/test_web/test_v2_training_session_v2.py); [plan credit browser scenario](../../webapp-frontend/e2e/scenarios/plan-credit-journey.spec.ts) | Follow-up TARGETED_PASS on source base `1748ee1`: Chromium uses the same owned workout and one open occurrence. Direct completion produces a free Journal entry and leaves the plan at 0/1. Completion from the plan raises it to 1/1. Cloning the planned entry produces a third Journal card, the clone response has no plan-item link, and the one completed occurrence remains 1/1. This covers the seeded synthetic profile. Paired and device acceptance remain separate. |
| J8: manual existing workout identity, edit/repeat/open, workout/exercise history | [Session API](../../tests/test_web/test_v2_training_session_v2.py) `test_j8_post_factum_existing_workout_keeps_identity_and_is_editable`, `test_j8_history_survives_rename_and_archive`; [workout link API](../../tests/test_web/test_v2_session_workout_link.py); [journal log browser scenario](../../webapp-frontend/e2e/scenarios/parity/journal-log.spec.ts) | Follow-up TARGETED_PASS on source base `f16330e`: two Chromium viewport cases passed on seeded synthetic profiles with empty history. The same manual session keeps its named workout, offers repeat and open actions, retains its ID when the second set changes from 7 to 12, and appears once in that workout’s history. Exercise analytics shows 20 total repetitions and a best set of 12. This confirms availability of the repeat action. Paired fresh/aged device acceptance remains open. |
| J9: external run 45 min, category/count/minutes, edit, no panel/plan change | [Journal create/list API](../../tests/test_web/test_v2_journal_log.py) `test_freeform_activity_is_stored_and_listed`; [canonical category API](../../tests/test_web/test_canonical_history.py) `test_external_activity_has_a_deterministic_category_and_display_name`; [external edit API](../../tests/test_web/test_v2_training_session_v2.py) `test_external_activity_edit_duration_type_and_date_keeps_duration`; new [nonempty history/custom-plan isolation API](../../tests/test_web/test_j9_external_activity_isolation.py) | Follow-up TARGETED_PASS at source base `047c9c5`: **3 passed, 1 warning in 8.63 s**, exit 0, no skips. Existing cases establish running45 identity/category and editable activity facts. The new case adds an actual API-created two-occurrence custom plan and prior manual history: running45 then cycling60 leaves the entire existing exercise payload, plan API, custom-plan/occurrence rows, prior manual session/recipe/targets/logs unchanged; global counts/minutes move 1/30 → 2/75 → 2/90 and activity identity stays fixed without plan credit. The warning is an unsuppressed existing Starlette 422 deprecation in the adjacent validation case. This fixture has no course inclusion/progression or credited completion; those preservation claims, full UI, paired fresh/aged personas and full J9 remain UNKNOWN. |
| J10: edit date/value moves Journal and analytics week, preserves duration/totals | Existing **manual / entered-duration** combined case: [canonical history API](../../tests/test_web/test_canonical_history.py) `test_date_and_value_edit_move_series_journal_day_and_exercise_history`; [measured-live date API](../../tests/test_web/test_v2_training_session_v2.py) `test_date_edit_of_live_session_keeps_measured_duration`; new [measured-live combined API](../../tests/test_web/test_j10_live_edit_convergence.py) | Existing manual source already combines date/value, weekly buckets, calendar/card movement and exercise history; it must not be described as absent. The new case targets the distinct measured `direct_live`, explicit engine-v1 path with literal previous-week buckets, stable 2 workouts / 40 minutes, 30-minute measured duration and immutable targets/snapshots/credit. TARGETED_PASS at source base `047c9c5`: new case plus those two adjacent cases, **3 passed in 6.63 s**, no skips, after a corrected test-authoring tuple error (no product RED claim). The follow-up below verifies the combined edit on v2 with a server-measured pause. Browser UI and the paired fresh/aged J10 matrix remain UNKNOWN. |
| J11: Mon→Thu spacing, all start paths, infeasible capacity, manual violation flag | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j11_monday_main_wednesday_rejected_thursday_allowed`, `test_k2_fresh_wednesday_third_main_is_infeasible`; [legacy API](../../tests/test_web/test_workout.py); [bot dispatcher](../../tests/test_bot/test_workout_section_rest_status.py); [V5.6 E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts) | Follow-up TARGETED_PASS on source base `f16330e`: four focused cases passed. After a Monday v2 session, the Wednesday v2 start rejects with `too_early`, legacy HTTP returns the same 8 October availability date, and the bot notice helper renders 14 hours until 08.10 at 00:00 UTC. The Thursday v2 start and the separate dispatch and infeasible-capacity checks pass. Manual K3 flagging and the full UI/aged/device trace remain open. |
| J12: +1…+4 visibility; future start and credit, current week unchanged | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j12_future_week_occurrence_starts_and_credits_itself`; [week UI](../../webapp-frontend/e2e/scenarios/fix-wave1/later-weeks.spec.ts) | Follow-up TARGETED_PASS on source base `53a4831`: both +1 and +4 API completion cases and two adjacent cases passed. Credit attaches to the selected future occurrence; all five weeks retain their occurrence IDs and the other four completion counts stay at zero. On a fresh V5.6 profile Chromium shows all four future weeks with two start controls each before and after reload. Follow-up at `034fdbb`: migration-only Chromium confirms a fresh V5.6 session can start from week +4, complete all nine sets on Live Engine v2, and credit only that occurrence. After reload, the current week still shows 0/2, week +4 shows 1/2, all ten occurrence IDs are preserved, and the nine other credits remain empty. One focused case passed. Aged UI remains unverified. |

Cross-cutting display requirements (no raw slug/id, fractional workout or fake zero
target; consistent names on all six surfaces) are not certified globally by locating
a label test or by an aggregate CI count. No source absence above is a claim that
all possible tests were exhaustively searched; these are concrete acceptance
**evidence gaps** to resolve before writing any additional tests.

## J9 external activity alongside a credited course workout

The [J9 regression](../../tests/test_web/test_j9_external_activity_isolation.py)
completes a free V5.6 course session with one credit, nine set results and
40 measured minutes. It then adds a 45-minute run on October 31 and changes
that same entry to 60 minutes of cycling on November 2. The edit moves the
activity from the October 26 week to the November 2 week. Analytics shows
two workouts and 85, then 100 minutes.

The completed course card, original credit, progression revision and state,
exercise panels and plan all remain identical. PostgreSQL confirms the same
course inclusion, workout, blocks, targets and result rows after both writes.
The activity has no course inclusion or plan credit.

The two isolation tests and the adjacent activity-edit and V5.6 progression
tests passed on isolated synthetic PostgreSQL (**4 passed in 8.92 s**, one
existing Starlette 422 deprecation warning). Browser and device acceptance
for this specific course and activity sequence remains open.

## J11 start availability at local midnight

The [occurrence tests](../../tests/test_web/test_v2_plan_occurrences.py) check
the same rest limit through the Plan API, Live start, legacy HTTP and the bot
notice. In Yekaterinburg, a session at October 31 19:30 UTC belongs to
November 1 locally, so the next start opens at November 4 00:00 local time.
In Los Angeles, a session at October 31 06:30 UTC belongs to October 30
locally. The next start opens at November 2 00:00 local time, after the clock
change.

In each case all paths report the same date one minute before availability.
At midnight the same planned occurrence becomes available and receives the
new session's credit. The legacy endpoint returns `ready` and the bot notice
clears. The verification called the bot notice helper without sending Telegram
messages.

Both boundary cases and the adjacent UTC, capacity and bot notice checks
passed on isolated synthetic PostgreSQL (**9 passed in 7.35 s**, no skips).
The target was removed after ownership and zero-client checks. The J11
post-factum flag, UI and physical-device traces remain open.

## J10 date and result edits on Live Engine v2

The [J10 regression](../../tests/test_web/test_j10_live_edit_convergence.py)
now runs with both engines. The v2 case records through the event API and
pauses each workout for 90 seconds. The server measures 30 and 10 minutes of
active time. The edit moves the 30-minute workout from October 7 to September
30 and changes its first result from 8 to 20.

Journal and Analytics show the new date, week and result. There are still two
workouts and 40 measured minutes. The control card and the saved workout
definition, recipe, targets and credit stay identical. The completed v2 engine
state and event sequence also stay identical.

Both engines and three neighboring history and deadline checks passed on
isolated synthetic PostgreSQL (**5 passed in 9.73 s**, no skips). The target was
removed after ownership and zero-client checks. Paired fresh/aged, browser UI
and device scenarios remain open.

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
so the original report-only checkpoint needed no application repair or new test.

## Migration-clause disposition and remaining acceptance

| Migration clause | Evidence state after this checkpoint | Remaining item |
|---|---|---|
| §3 deterministic backfill and apply-again zero | TARGETED_PASS for the selected history runner; plan runtime PASS | No claim that every backfill ambiguity/type or migration was separately rerun |
| §4 single canonical history / legacy dual-write | TARGETED_PASS for six service tests and the direct aged rehearsal | Cross-view Journal/Profile/Analytics totals across all personas and cutover readiness still UNKNOWN |
| §5 aged plan convergence / history credits | TARGETED_PASS for eight plan service tests | One paired same-event current/future plan regression now passes (follow-up below); the full rehearsal persona set remains UNKNOWN |
| §6 in-flight v1 and cached old clients | TARGETED_PASS for a synthetic direct v1 session at `32c9a1a` and a planned v1 session on a legacy aggregate at `e15bd69` through aged plan convergence and API replay | Actual cached WebView and cutover rehearsal remain open. Keep v1 until separate acceptance. |
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


## Follow-up: paired current/aged plan representation (#309)

Source base: `047c9c5a0207e422be971c157a4ea359b2f4a37d`, fetched after
PR #431 integrated the report above. Application source is unchanged from the
original examined head. This follow-up adds one acceptance regression,
[test_plan_fresh_aged_equivalence.py](../../tests/test_services/test_plan_fresh_aged_equivalence.py),
and narrows one J2 evidence gap; it is test maintenance, not a reproduced bugfix.

Both synthetic UTC users share one free Program and STEP strategy profile and
explicitly enroll in `pullups_legacy_step` with the same inputs and frozen
prescription. Both replay identical full nine-set planned sessions via the real
API on Monday October 5 and Thursday October 8, completing 40 minutes after each
start. Direct start/completion clocks and plan clocks are fixed. The legacy
program version is deliberate; this does not reinterpret new V5.6 prescriptions.

After replay, one fixture retains current occurrence storage. Only the other's
current-week representation is reconstructed as the documented old A+B aggregates
(`count_per_week = 3`), M2M credits and absent derived inclusion fields. Its
canonical session contents, blocks, targets, logs, prescription snapshots and
progression are retained. This is **representation convergence after identical
API replay**; it does not replay historical writers, migrate progression or assert
that past aggregate display must equal current occurrence display.

The regression executes the same convergence through Friday and the next week
for each profile and compares every returned occurrence business field after
replacing row, owner, week and credit-session IDs with their semantic week/event
keys. It compares all weekly summaries and spacing, inclusion status, sequence
cursor, completed-main count and last-main time. Literal expectations guard the
comparison: current week 3 planned/2 completed; next week 3/0; each completed
occurrence credits its corresponding event; next permitted main date October 11;
status active, cursor/count 2 and last main October 8. Both second convergences
report zero mutations.

Per-owner before/after fingerprints cover every session column except the
explicitly repairable `plan_item_id`, plus complete block/target/log rows.
Frozen inclusion snapshots, initial/progressed state, provenance, start time and
progression revision remain exact per owner; both profiles' snapshot and
progression values also match. Target/log/block content is compared across users
with only identifiers and creation timestamps omitted. Subscription cache and
program access are preserved. Retired aggregates retain their identities.

Actual command, on one new uniquely named owned synthetic PostgreSQL target:

```bash
python -m pytest -q tests/test_services/test_plan_fresh_aged_equivalence.py tests/test_services/test_plan_convergence_v2.py::test_aged_profile_converges_and_preserves_history tests/test_services/test_plan_convergence_v2.py::test_aged_profile_current_and_future_plan_stays_functional
```

**Result: 3 passed in 9.05 s, no skips, exit 0 on the first execution.** The two
adjacent existing tests check the preservation and aged-plan behavior that the
paired fixture extends. Targeted Ruff check/format passed. The local PostgreSQL
and Redis host assertions, existing shared-default check and per-target URL
overrides described above were repeated. The owned target was dropped only after
ownership and zero-client assertions, without FORCE or session termination.

That run established TARGETED_PASS for one paired plan representation. The cross-view checks below extend that evidence. Other aged personas, V5.6 acceptance, in-flight old clients, rehearsal/restore and device evidence remain open.

### Follow-up at `45eccac`: paired Journal, Profile and Analytics (#309)

The same paired regression now reads the product endpoints after the second,
zero-mutation pass. The legacy list has no cards for these v2 events. The v2
Journal lists the same two completed session IDs per profile in newest-first
order, each titled «Подтягивания» with a 40-minute duration. The October calendar
shows one entry on each expected date. Profile reports two workouts. Analytics
reports two workouts and 80 measured minutes in the same week and category.

The extended case, the existing mixed legacy/v2 history convergence case and the
existing cross-view integer-total case passed together on an isolated synthetic
PostgreSQL database: **3 passed in 11.47 s**, no skips. Ruff check and format
check passed. The database was removed after ownership and zero-client checks.
This covers one paired plan-storage representation with active subscription
caches. Mixed legacy/v2 history was tested as a separate, single-profile case.

### Follow-up at `bc37db1` — active v1 session from the V5.6 main slot

The [course regression](../../tests/test_web/test_v2_course_v5.py) starts a v1
V5.6 workout from an existing main occurrence and records one set. Plan
convergence freezes two older aggregate rows with the session still active.
The second convergence reports zero changes. The calendar transitions to
November 1 and November 2 both preserve the original session ID, phase,
prescription and first set. The course progression state and revision remain
the same through convergence.

Completing workout A twice advances the course revision once. The next A
volume targets become 18/17/17/17, its strength load becomes 6.5 kg, and the
next workout role is B. All nine set results and the original prescription
remain in Journal. The original main occurrence has the only new credit.

Both boundaries, the adjacent V5.6 A→B case and the plan convergence module
passed on isolated synthetic PostgreSQL (**14 passed in 17.17 s**, no skips).
The owner and zero-client checks passed before removal of the synthetic target.
Cached WebView and staging cutover rehearsal remain open.

### Follow-up at `12805e8`: archived workout in mixed legacy and v2 history

The [mixed-history regression](../../tests/test_web/test_canonical_history.py)
records a legacy session with an unkeyed pre-#308 copy and a native manual
session with a frozen workout prescription. It archives the workout through
the API before convergence. The dry run leaves the copy unkeyed, apply binds
exactly one legacy copy and apply-again reports zero mutations. The archived
workout's Journal card keeps its title, prescription, sets and 25-minute
duration. Its workout link is unavailable after archiving. Journal, Profile,
Analytics and canonical storage count two sessions across both the month and
week boundaries. Each expected calendar day contains one session.

Both dated cases and the three adjacent archive, legacy deletion and mixed
history checks passed on isolated synthetic PostgreSQL: **5 passed in 12.54 s**,
no skips. The owned database was removed after checking ownership and zero
clients. This covers one aged history representation with an archived
definition. The paired fresh/aged matrix and staging rehearsal remain open.

### Follow-up at `6be2d38`: paid and expired entitlements during J2 convergence

For each access scenario, paired synthetic profiles repeat the same two free
course sessions and converge current and aged plan representations. One pair
has a current paid period and the other has an expired paid period. The
subscription cache, expiry and the complete synthetic subscription row are
preserved. The free course remains free in the Plan API, Journal/Profile and
Analytics still agree on the totals, and the second convergence reports zero
mutations in both access cases. No payment provider participates in the fixture.

The two paired cases and the existing expired-user free and premium-access
boundary cases passed together on isolated synthetic PostgreSQL:
**4 passed, 1 existing Starlette deprecation warning**, no skips. Ruff check
and format check passed. The owned database was removed after verifying
ownership and zero clients. This extends the paired plan representation proof.

### Follow-up at `11c3422`: J2 convergence across five synthetic profiles

The [all-user convergence runner](../../scripts/repair_plan_convergence.py)
ran on a migration-only synthetic PostgreSQL database at source
`11c34221e165bd528b7d5745a875d5c3c7b3efa7`. Four profiles had plans: a fresh
active profile, an active profile with a 23-day-old current-format plan,
an active profile of the same age with a legacy snapshot missing
`program_items`, and an expired-trial profile. An active profile without
a plan was outside the run. The [QA fixture functions](../../scripts/qa/provision_staging_identities.py)
created all five profiles without a payment provider.

The first dry run predicted **19 changes** and left the compared rows
unchanged. Apply made the same 19 changes: one snapshot repair, 12 weeks
and six plan items. All four processed plans passed the runner guards.
The compared user, subscription and program rows remained identical.
The four earlier course sessions and their blocks, targets, 36 set logs
and events were preserved. The runner recorded no changes to session credit.
A second apply and a final dry run both reported **zero changes**; a
row comparison after the second apply confirmed idempotence. The isolated
database was removed after verifying ownership and zero clients.

This checks the runner on the listed synthetic profiles. Staging rehearsal,
backup restore and native Telegram acceptance remain open.

### Follow-up at `32c9a1a`: active v1 session across aged plan convergence

The [in-flight regression](../../tests/test_services/test_plan_convergence_v2.py)
starts a direct workout through the old API request and records one set before
converging an aged plan. Fixed clocks exercise October 31, November 1 and
November 2, 2026. The first two dates expand the fourth week and transfer
three distinct credits from the linked sessions. On Monday the fourth week
freezes as history and no credit is transferred. The in-flight direct session
receives no plan credit. The second convergence reports zero changes in each
case. Reopening the active session returns the same v1 ID,
phase, targets and recorded set. Replaying the first set and a stale phase
request through v1 produces no duplicate or phase change. After the second
set, the Journal preserves the frozen prescription and both results. A
subsequent v2 start has a new session ID and leaves that Journal card unchanged.

The plan convergence module and the adjacent v1-compatibility case passed
on isolated synthetic PostgreSQL, **12 passed in 15.78 s**, no skips. Ruff and diff
checks passed. The owned database was removed after verifying ownership and
zero clients. This exercises the v1 HTTP contract during plan convergence.
The fixture does not run a cached WebView or change a deployment flag.

### Follow-up at `e15bd69` — planned v1 session across aged plan convergence

The [planned-session regression](../../tests/test_services/test_plan_convergence_v2.py)
starts a workout from a legacy twice-weekly plan row with one past completed
session. It records the first v1 set just before midnight. The same workout
resumes after convergence on November 1 and November 2, with its original
phase, prescription and recorded set.

On the month boundary the active session takes the second occurrence and the
past session takes the first. On the week boundary the old aggregate freezes
and the active session retains its link to that aggregate. Replaying the
original start returns the same session ID. The second convergence is a no-op.
Completing twice retains both set results, the Journal card and a 2/2 plan
count for the original week in both cases.

The plan convergence module and v1 compatibility check passed on isolated
synthetic PostgreSQL (**14 passed in 13.84 s**, no skips). The owned database was
removed after checking ownership and zero clients. This extends the synthetic
HTTP evidence to one planned case. Workouts from a program main slot, cached
WebView and the cutover rehearsal remain open.
