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

### Follow-up on the current protected runtime

The same historical bundle and six offline scenarios ran against the exact
API at protected main `a95eabe`. The bundle SHA-256 matched the original
artifact. Chromium passed all six cases in 16.7 seconds without retries
or skips. PostgreSQL confirmed six unique completed v1 sessions, six
distinct plan credits, and preservation of the queued set values and
completion notes. The synthetic target was removed after ownership and
zero-client checks. Native Telegram WebView evidence remains open.

### An open v1 session with an offline result during Plan convergence

Chromium ran the same historical bundle on the exact protected API
`10e5b41` with a single synthetic profile. After a live planned v1
session reached its first working set, Chromium went offline and queued
eight repetitions. PostgreSQL still had no result for the open session.

The harness represented that plan as an old two-session weekly aggregate.
It linked one earlier synthetic completion to the aggregate and left
the open session's phase and snapshots intact. The real Plan convergence
service split the aggregate into two occurrences and credited the earlier
completion to the first and the open session to the second. The queued set
was still absent on the server. A second apply reported zero changes.

On reconnect, the browser synchronized the queued result and reopened the
first set with eight repetitions in the same v1 session. It then finished
with results of eight, five and four. Replaying completion returned the
same result ID. The Journal held two completed sessions. PostgreSQL
confirmed that each retained a distinct, single credit, and Plan showed 2/2.

**Result — 1 passed in 6.9 s**, with no retries. The synthetic database
was removed after ownership and zero-client checks. Native WebView
and the staging cutover rehearsal remain open.

### Offline v1 completion during Plan convergence and weekly rollover

The historical `020ca64` bundle ran against the API from `0bc3759` and
`6e852be` in Chromium on isolated PostgreSQL. Two runs staged the finish
request offline after saving sets of eight, five and four. The server still
held an open v1 session without the note or effort when convergence ran.
After the tab closed and reopened online, the browser sent one completion
request for the same session ID. The Journal showed two completed sessions
and preserved the three results, note and effort of three.

- **Same week — 1 passed in 6.1 s on `0bc3759`.** The real convergence service
  split the synthetic two-session aggregate into two occurrences. PostgreSQL
  preserved one distinct occurrence credit per completion. Plan showed 2/2.
- **Weekly rollover — 1 passed in 11.7 s on `6e852be`.** The browser and
  API used fixed UTC clocks from Sunday 1 November 2026 at 23:59:55 to Monday
  2 November at 00:00:05. Convergence froze the original aggregate as
  history. PostgreSQL preserved the earlier completion's legacy link and
  the resumed session's direct link to that same aggregate, with a Sunday
  start and a Monday completion. Plan showed 2/2 in week one and zero
  items in week two.

The second convergence reported zero mutations in both runs. Each synthetic
database was removed after verifying ownership and zero clients. Native
Telegram and the staging cutover rehearsal remain open.

### Offline completion of an unplanned v1 session during convergence

Chromium ran the historical `020ca64` bundle against the protected
`27b9852` runtime. One synthetic profile opened the same workout that
was present in Plan and started it from Workout Detail. The old client
recorded eight, five and four repetitions, then queued completion offline.

Plan convergence split a two-session weekly aggregate while the device
was offline. It credited the earlier planned session to the first
occurrence, and a second apply reported zero changes. Reopening online
sent one completion request for the same direct v1 session. The returned
Journal card retained the three results, effort of three and note.
PostgreSQL and the Plan response showed a single credit from the earlier
planned session, leaving the count at 1/2.

**Result — 1 passed in 7.4 s.** The first harness attempt checked session
source on the active response. The passing run checked it in PostgreSQL
and the completed Journal card. The synthetic database was removed
after verifying ownership and zero clients.

## Journey-to-test mapping and remaining cells

The source links point to test assertions. The evidence column gives the
profile, execution layer and receipt for each focused result. Full Wave 4
acceptance still requires the fresh and aged matrix on the rehearsal dataset,
invariant checks, and staging and device evidence specified in #309.

| Journey / accepted observation | Existing source anchors | Executed evidence | Remaining targeted coverage |
|---|---|---|---|
| J1: onboarding, 7-day trial, free course, prescription, plan/live/history/analytics/reopen | [Trial service](../../tests/test_services/test_onboarding_trial_guarantee.py); [free access API](../../tests/test_web/test_free_program_access.py); [V5.6 API](../../tests/test_web/test_v2_course_v5.py) `test_new_inclusion_uses_v5_6_rule_and_records_provenance`; [V5.6 E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts); [golden Builder E2E](../../webapp-frontend/e2e/scenarios/golden-journey.spec.ts) | Fresh Chromium verified onboarding, the seven-day trial, V5.6 A, measured Analytics minutes and reopening in a new tab on `1867853`. Fresh M=0 A→B passed on `397594b`. Aged Chromium on `348d870` checked Plan, Journal and Analytics after A, then separately completed A→B and preserved the two earlier records. Expired-trial Chromium started and completed the free course. [Fresh reopen](#j1-trial-and-course-state-after-opening-the-app-in-a-new-tab), [fresh A→B](#j4-continuation-from-a-to-b-at-m0), [aged readback](#j1-j6-and-j7-browser-checks-on-profiles-with-existing-history), [aged A→B](#j4-course-progression-a-to-b-on-a-profile-with-existing-history), [expired trial](#j2-and-j4-weighted-course-after-trial-expiry) | Physical iPhone/Telegram J1, including reopening the Mini App. |
| J2: aged state converges without history/entitlement loss; repeat is zero | [Plan convergence](../../tests/test_services/test_plan_convergence_v2.py) `test_aged_profile_converges_and_preserves_history`, `test_run_all_second_apply_has_zero_mutations`; [single-history rehearsal](../../tests/test_scripts/test_single_history_migration.py) `test_aged_database_converges_idempotently_without_touching_legacy_history`; [aged runtime repair](../../tests/test_services/test_aged_state_convergence.py) | Paired current and aged fixtures preserved history, credits and paid/expired entitlements. A separate six-profile synthetic run on `7016323` compared the Journal, calendar, Profile and Analytics before and after Plan convergence. Apply made the 24 predicted changes and reapply made zero. Additional checks covered mixed legacy/v2 history, archived or absent definitions, and offline v1. [Paired readback](#follow-up-at-45eccac-paired-journal-profile-and-analytics-309), [six-profile run](#j2-cohort-reads-before-and-after-plan-convergence), [mixed history](#follow-up-at-a46ec0e-paired-mixed-history-archived-workout-and-plan-credit), [absent definition](#mixed-history-when-its-former-workout-definition-is-absent), [offline v1](#offline-v1-completion-during-plan-convergence-and-weekly-rollover) | Production-shaped rehearsal and invariant checker across the required personas. Actual cached Telegram WebView and restore evidence remain open. |
| J3: exact 17-target W-ladder, order/rest, persistence and Journal labels | [Workout domain](../../tests/test_workout_definition.py) `test_w_ladder_is_17_explicit_sets_in_exact_order`; [API](../../tests/test_web/test_v2_workout_definition.py) `test_w_ladder_detail_and_catalog_show_explicit_sequence`; [J3 fresh-install browser case](../../webapp-frontend/e2e/scenarios/fix-wave1/fresh-install-content.spec.ts) | Fresh Chromium reproduced the missing plan-row recipe on `45eccac`. After the fix on `2d37305`, four migration-only cases passed. Detail, Plan, pre-screen, persisted targets and Journal agreed on all 17 targets. Aged Chromium on `348d870` and fresh Chromium on the executable tree of `c20a1ec` each waited for all 16 automatic ten-second transitions. Separate aged passes verified the title through Summary and restored the same active session after reload. [aged elapsed rests](#j3-w-ladder-with-all-rests-elapsed), [fresh elapsed rests](#j3-w-ladder-with-all-rests-elapsed-on-a-fresh-profile), [summary](#j3-name-and-results-from-detail-to-summary), [reload](#j3-restoring-the-active-w-ladder-after-reload) | Rehearsal coverage across the required aged personas. |
| J4: legacy 4 working + max persistence; current V5.6 exact recipes | [Legacy prescription domain](../../tests/test_course_prescription.py); [legacy API](../../tests/test_web/test_v2_course_prescription.py); [V5.6 golden examples](../../tests/test_pullups_v5.py) `test_m0_assisted_example`, `test_m10_qualifies_immediately_with_transition_volume`, `test_m25_example`, `test_m50_start_cap_only`; [course engine](../../tests/test_web/test_v2_course_v5_engine.py); [course E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts) | Legacy Chromium verified four work sets plus the explicit max set, five persisted results and both STEP outcomes. Fresh V5.6 Chromium completed A and B at M=0, 10, 25 and 50, with persisted recipes, results and distinct credits. Aged V5.6 Chromium on `348d870` retained both earlier records through A and B. The continuation harness modelled the required rest by backdating only the synthetic A session. [Legacy](#j4-legacy-block-b-execution-and-progression), [M=0](#j4-continuation-from-a-to-b-at-m0), [M=25](#j4-weighted-continuation-from-a-to-b-at-m25), [M=10 and M=50](#j4-v56-transition-and-starting-target-cap), [aged](#j4-course-progression-a-to-b-on-a-profile-with-existing-history) | Rehearsal coverage across the required aged personas. |
| J5: automatic deadlines, background return, pause/reload and audio offsets | [Shared vectors](../../tests/test_live_engine_vectors.py); [engine API](../../tests/test_web/test_v2_live_engine.py); [offline reopen](../../tests/test_web/test_v2_live_engine_offline_reopen.py); [engine E2E](../../webapp-frontend/e2e/scenarios/live-engine-v2.spec.ts), deadline/background/pause cases | Fresh and aged Chromium verified the inter-block deadline and return after 60 seconds of simulated hidden state. Aged runs checked offline pause, reload and API cue timestamps across pause/resume. The audio hook vectors and instrumented phase-end playback passed. [Inter-block return](#j5-paired-browser-return-after-inter-block-rest), [60-second return](#j5-paired-browser-return-after-60-seconds-hidden), [offline pause](#j5-offline-interval-pause-on-a-profile-with-history), [audio checks](#j5-audio-timeline-and-phase-end-playback), [live cue timestamps](#j5-live-api-timestamps-across-pause-and-resume) | Physical Telegram background return, audible cue timing and watch behavior. |
| J6: custom weekly volume 2/2/0/2, one occurrence credit, named editable Journal | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j6_custom_plan_2_2_0_2_2_0_exact_occurrence_counts`; [custom plan browser scenario](../../webapp-frontend/e2e/scenarios/custom-plan-journey.spec.ts) | Fresh Chromium on `72a48da` used a seeded workout, verified week counts 2/2/0/2, completed one occurrence and opened the named Journal card for editing. Aged Chromium on `2e910bd` built the workout, checked its name through Summary and saved a changed result in Journal while keeping one credit and the earlier records. Fresh Chromium on the executable tree of `c20a1ec` also built the workout and saved the Journal edit. [Fresh browser scenario](../../webapp-frontend/e2e/scenarios/custom-plan-journey.spec.ts), [aged title and saved edit](#j6-title-and-edited-result-on-a-profile-with-history), [fresh Builder and edit](#j6-building-and-editing-on-a-fresh-profile) | Rehearsal coverage across the required aged personas. |
| J7: direct start and clone do not credit a plan | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j7_direct_start_credits_nothing`, `test_clone_never_credits_a_plan_item`; [session API](../../tests/test_web/test_v2_training_session_v2.py); [plan credit browser scenario](../../webapp-frontend/e2e/scenarios/plan-credit-journey.spec.ts) | Fresh Chromium on `1748ee1` completed a direct and a planned workout, then cloned the planned Journal entry. Only the planned occurrence earned credit. Fresh Chromium on the executable tree of `6c83453` built the workout and checked matching names from Detail through Summary and Journal. Aged Chromium on `5107448` checked the same title, results and single credit while preserving earlier history. [Fresh browser scenario](../../webapp-frontend/e2e/scenarios/plan-credit-journey.spec.ts), [fresh title and credits](#j7-matching-titles-and-credits-on-a-fresh-profile), [aged title and credits](#j7-matching-titles-for-direct-planned-and-cloned-workouts) | Rehearsal coverage across the required aged personas. |
| J8: manual existing workout identity, edit/repeat/open, workout/exercise history | [Session API](../../tests/test_web/test_v2_training_session_v2.py) `test_j8_post_factum_existing_workout_keeps_identity_and_is_editable`, `test_j8_history_survives_rename_and_archive`; [workout link API](../../tests/test_web/test_v2_session_workout_link.py); [journal log browser scenario](../../webapp-frontend/e2e/scenarios/parity/journal-log.spec.ts) | Chromium covered two viewports on seeded empty-history profiles at `f16330e`, including Repeat/Open availability, saving the edit and the updated exercise totals. Aged Chromium checked the same edit and earlier records. Later aged runs preserved the snapshot and results after rename and archive. Archive hid the workout links and the direct lookup returned 404. [Empty-history browser scenario](../../webapp-frontend/e2e/scenarios/parity/journal-log.spec.ts), [aged edit](#j8-backdated-workout-on-a-profile-with-existing-course-history), [rename](#j8-preserving-the-historical-record-after-renaming-its-workout), [archive](#j8-preserving-the-historical-record-after-archiving-its-workout) | Rehearsal coverage beyond the seeded empty-history and two-record profiles. |
| J9: external run 45 min, category/count/minutes, edit, no panel/plan change | [Journal create/list API](../../tests/test_web/test_v2_journal_log.py) `test_freeform_activity_is_stored_and_listed`; [canonical category API](../../tests/test_web/test_canonical_history.py) `test_external_activity_has_a_deterministic_category_and_display_name`; [external edit API](../../tests/test_web/test_v2_training_session_v2.py) `test_external_activity_edit_duration_type_and_date_keeps_duration`; new [nonempty history/custom-plan isolation API](../../tests/test_web/test_j9_external_activity_isolation.py) | The HTTP runs verified that a 45-minute run edited to 60 minutes of cycling preserved custom-plan and credited course state. On `047c9c5` the custom-plan case and two adjacent checks passed in 8.63 s, with one existing Starlette 422 deprecation warning. Fresh and aged Chromium on `afe36ad` moved that same activity across a week and month boundary, matching both Analytics series to the API and preserving course credit, Plan and exercise panels. [Course HTTP check](#j9-external-activity-alongside-a-credited-course-workout), [cross-boundary Chromium](#moving-the-same-activity-across-a-week-and-month-boundary) | Rehearsal coverage across the required aged personas. |
| J10: edit date/value moves Journal and analytics week, preserves duration/totals | Existing **manual / entered-duration** combined case: [canonical history API](../../tests/test_web/test_canonical_history.py) `test_date_and_value_edit_move_series_journal_day_and_exercise_history`; [measured-live date API](../../tests/test_web/test_v2_training_session_v2.py) `test_date_edit_of_live_session_keeps_measured_duration`; new [measured-live combined API](../../tests/test_web/test_j10_live_edit_convergence.py) | The manual-entry HTTP check and the measured direct engine-v1 regression on `047c9c5` checked movement across weekly buckets, saved results and unchanged totals. The measured v1 case and two adjacent checks passed in 6.63 s after correcting a test fixture. The engine-v2 HTTP follow-up covered measured time with a pause. Fresh and aged Chromium moved a plan-started v2 session between weeks and preserved measured duration and credit. [HTTP checks](#j10-date-and-result-edits-on-live-engine-v2), [paired Chromium](#j10-paired-browser-edit-on-fresh-and-aged-profiles) | Rehearsal coverage across the required aged personas. |
| J11: Mon→Thu spacing, all start paths, infeasible capacity, manual violation flag | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j11_monday_main_wednesday_rejected_thursday_allowed`, `test_k2_fresh_wednesday_third_main_is_infeasible`; [legacy API](../../tests/test_web/test_workout.py); [bot dispatcher](../../tests/test_bot/test_workout_section_rest_status.py); [V5.6 E2E](../../webapp-frontend/e2e/scenarios/program-journey-v56.spec.ts) | The v2 and legacy APIs and the bot notice helper agreed on the first allowed date, including local midnight and a clock change. Aged Chromium on `348d870` observed both an available date and infeasible capacity in Plans. Fresh Chromium on the executable tree of `209bfc7` verified a blocked start during rest and completion of the same planned occurrence on the first allowed day. K3 stored the retrospective spacing flag for course sessions through HTTP. The separate Journal-form run covered an owned workout. [Local midnight](#j11-start-availability-at-local-midnight), [aged browser](#browser-availability-and-calendar-on-profiles-with-existing-history), [fresh first allowed day](#j11-first-allowed-day-on-a-fresh-profile), [K3 course flag](#j11-retrospective-main-session-spacing-flag-k3), [Journal form](#j11-k3-and-the-existing-journal-recording-form) | Physical iPhone/Telegram J11. The bot helper checks used synthetic state without sending Telegram messages. |
| J12: +1…+4 visibility; future start and credit, current week unchanged | [Occurrence API](../../tests/test_web/test_v2_plan_occurrences.py) `test_j12_future_week_occurrence_starts_and_credits_itself`; [week UI](../../webapp-frontend/e2e/scenarios/fix-wave1/later-weeks.spec.ts) | The API on `53a4831` verified completion from weeks +1 and +4. Fresh Chromium on `034fdbb` and aged Chromium on `8efcbd2` verified visibility of +1 through +4, completed from +4, and preserved the current week, occurrence IDs and other credits. [Future-week API](../../tests/test_web/test_v2_plan_occurrences.py), [browser scenario](../../webapp-frontend/e2e/scenarios/fix-wave1/later-weeks.spec.ts), Aged Chromium on the executable tree of `321da45` also completed week +1 and verified that its occurrence alone earned credit. [Aged week +4 receipt](#j12-future-week-credit-on-a-profile-with-old-plan-history), [aged week +1 receipt](#j12-next-week-credit-on-a-profile-with-old-plan-history) | Rehearsal coverage across the required aged personas. |

The shared browser display criteria are still open across the full rehearsal
matrix. Check human-readable labels, whole workout counts, real targets, and
consistent names across Detail, Plan, Live, Summary and Journal. The linked
receipts identify which surfaces each check exercised.

## J1, J6 and J7 browser checks on profiles with existing history

Three independent Chromium scenarios ran against API and frontend source
`348d870`. Each used a separate synthetic database with a 23-day-old plan
and two previous course workouts. Each database was removed after
ownership and zero-client checks.

- **J1, 1 passed in 1.1 min.** A V5.6 course session retained all nine
  set results and its measured duration. After reload, the current week
  showed 1/2 with exactly one credited occurrence. The Journal showed the
  new named course card and preserved both previous cards. Analytics added
  one workout and its nonzero measured minutes to the course category.
- **J6, 1 passed in 5.1 s.** The Builder saved a new 2 × 8 workout. A four-week
  plan showed 2/2/0/2 occurrences and credited one after completion. The named
  Journal entry opened for editing with results eight and seven. The earlier
  course cards and course plan items were identical. Earlier harness attempts
  stopped while locating the empty-state create button, returning through
  workout detail, and selecting the saved prescription. The passing run
  used the corresponding controls and checked the prescription at list-item
  level.
- **J7, 1 passed in 8.3 s.** A newly built workout was added to the plan.
  Starting it directly kept the current week at 0/3. Starting from its
  occurrence raised the count to 1/3. Cloning the planned entry left that
  count unchanged and the clone response had no plan-item link. The two
  original course cards and course plan items remained identical.

Native Telegram and the complete profile matrix still need separate evidence.

### J6 title and edited result on a profile with history

On the executable tree of protected `2e910bd`, Chromium built «Силовая J6»
as a two-set workout and created a four-week plan with 2/2/0/2 occurrences.
The same title appeared in Detail, Plan, the start screen, Live Engine v2,
the completion summary and the Journal. The summary showed two sets with
eight and seven repetitions.

Editing the second result to nine kept the session ID, workout identity,
prescription snapshot and single credited occurrence. The named Journal
card showed eight and nine. The Plan and both earlier cards stayed intact.
**Result — 1 passed in 6.8 s.** The synthetic database was removed after
verifying ownership and zero clients.

### J6 building and editing on a fresh profile

Chromium ran on the executable tree of protected `c20a1ec`. The synthetic
profile had an active entitlement, no prior sessions and no plan. It created
a 2 × 8 workout in Builder, created a four-week plan with 2/2/0/2 occurrences
and completed one of the current week's two occurrences.

Detail, Plan, the start screen, Live Engine v2, Summary and Journal showed
the same title. Summary retained eight and seven repetitions. Saving a
Journal edit changed the second result to nine. The session ID, workout ID,
prescription snapshot and single Plan credit stayed the same.

**Result — 1 passed in 8.9 s.** The synthetic database was removed after
verifying ownership and zero clients.

### J7 matching titles for direct, planned and cloned workouts

On the executable tree of protected `5107448`, Chromium created
«Силовая J7» and completed it from its own detail and from its plan
occurrence. The workout name matched on both start screens, both Live
Engine screens and both completion summaries. Each summary showed eight
and seven repetitions. The planned entry and its clone kept the same
workout identity and results, and all three new Journal cards showed the
original title.

The planned session earned exactly one occurrence credit. The direct
session and clone had empty plan-item links. The earlier Journal cards
and course plan items stayed identical. **Result — 1 passed in 8.0 s.**
The synthetic database was removed after verifying ownership and zero
clients.

### J7 matching titles and credits on a fresh profile

Chromium ran on the executable tree of protected `6c83453`. The
synthetic profile had no previous workouts or plan. It built a workout
with two sets, added it to the plan, and completed it both directly
from Detail and from its planned occurrence. Detail, Plan, the start
screens, Live Engine v2, Summary and Journal showed the same title.
Both summaries showed eight and seven repetitions.

The direct start left Plan at 0/1. The planned start moved it to 1/1,
and cloning its Journal card left it at 1/1. All three records retained
the workout ID. PostgreSQL-backed responses showed that only the
planned record held the occurrence link and credit. The clone carried
the same eight and seven repetitions.

**Result — 1 passed in 7.1 s.** The synthetic database was removed after
verifying ownership and zero clients.


## J3 W-ladder with all rests elapsed

The [fresh journey](../../webapp-frontend/e2e/scenarios/fix-wave1/fresh-install-content.spec.ts)
was adapted to an isolated synthetic profile with two previous workouts
and a 23-day-old course plan. API and frontend source was `348d870`.
The workout detail, Plan before and after reload, and start screen showed
the exact W-ladder prescription with ten-second rest. Live Engine v2
returned the same 17 targets in order and a ten-second rest for every
gap between sets. Chromium waited for each of the 16 transitions to the
next working set. The shortest observed wait was 10.36 seconds.

After completion and reload, the Journal showed the exact prescription
and results. The completed session API returned 17 persisted targets and
17 results in the same order. The two earlier Journal cards stayed
identical. **Result — 1 passed in 3.0 min**, zero retries. The isolated
database was removed after ownership and zero-client checks.

### J3 W-ladder with all rests elapsed on a fresh profile

Chromium ran on the executable tree of protected `c20a1ec` with one
synthetic profile and no prior sessions or plan. It added W-ladder to
the free pool and checked all 17 targets and the ten-second rest in
Detail, Plan before and after reload, and the start screen.

Live Engine v2 prescribed ten seconds for each of the 16 gaps.
Chromium waited for all 16 automatic transitions without advancing the
timer. The shortest observed wait from the rendered Rest phase was
9.89 seconds. After completion and reload, the Journal and completed
session API showed one card with all 17 planned targets and results
in the original order.

**Result — 1 passed in 3.0 min.** The synthetic database was removed
after verifying ownership and zero clients.

### J3 name and results from detail to summary

On the executable tree of protected `1899586`, Chromium followed
«W-лесенка» from its catalogue card through Detail, Plan, the start screen,
Live Engine v2, the completion summary and the Journal. Each surface
displayed the workout name. The summary showed 17 sets and listed each
result in order. The Journal and completed-session API showed the same
17 planned targets and results, and both earlier cards stayed identical.

This run advanced waits using the application's start-now control.
The preceding elapsed-rest run covers all 16 automatic waits.
**Result — 1 passed in 10.8 s.** The synthetic database was removed after
verifying ownership and zero clients.

### J3 restoring the active W-ladder after reload

On the executable tree of protected `595e1e2`, Chromium reloaded during
the first rest after the server had recorded five repetitions. The normal
active-session response restored the same session, workout title and first
result. Chromium continued from the next set without issuing another start
request.

The completion summary retained the title and all 17 results. The Journal
showed one matching card with all 17 targets and results. Both older cards
stayed identical and the active session cleared. **Result — 1 passed in
11.2 s.** The synthetic database was removed after verifying ownership and
zero clients.

## J1 and J4 with a zero baseline in V5.6

Chromium ran the fresh onboarding-to-course journey with zero
pull-ups on protected runtime `27b9852`. A migration-only PostgreSQL
database started without a user. Onboarding saved the zero baseline,
and the course prompted for assistance inputs before showing the
prescription. With volume capacity ten, the prescreen and Live Engine
showed A as 7/7/7/7+ and assisted strength as 5/5/5/5/5–8.

The session saved 7, 7, 7, 9 and 5, 5, 5, 5, 6. Plan showed 1/2 after
reload, Journal showed both named blocks, and Analytics showed one
course workout with its measured minutes. The next prescription
contained ten sets of five with sixty-second rests. PostgreSQL confirmed
the zero baseline, both sets of results and one plan credit.

**Result — 1 passed in 39.5 s.** The synthetic database was removed after
verifying ownership and zero clients.

### J1 trial and course state after opening the app in a new tab

On the executable tree of protected `1867853`, Chromium started with
an empty user database, recorded a zero baseline and completed the
course's first V5.6 workout through both blocks. After onboarding the
subscription endpoint showed an active trial. PostgreSQL confirmed
that the trial covered exactly seven days and that the user's expiry
matched the trial end. The fixture used no paid subscription rows.

Opening the app in a new browser tab retained the subscription status
and expiry. Plan still showed one of two occurrences completed,
Journal still showed one named course workout and Analytics still
counted one workout. The original tab had also verified the measured
duration in Analytics and the Journal details for both sets of results.
PostgreSQL confirmed the nine saved results and one occurrence credit.

**Result — 1 passed in 41.8 s.** The synthetic database was removed
after verifying ownership and zero clients. Native Telegram acceptance
remains open.

### J4 continuation from A to B at M=0

A separate Chromium run on protected `397594b` completed both sessions.
The fixture shifted only A's performed date three days back to model
the rest. B showed 10×5 with the selected volume band and a
one-minute volume rest. The strength block used bodyweight and
recorded 5, 5, 5, 5 and 7.

The next session returned to A. The stored B volume prescription
advanced to 11×5 and retained the selected bodyweight strength setup.
The Journal and PostgreSQL kept 24 results and both frozen recipes,
and the Plan credited two distinct occurrences.

**Result — 1 passed in 43.9 s.** The synthetic database was removed after
verifying ownership and zero clients.

## J4 first weighted V5.6 session at M=25

Chromium ran against protected runtime `c360d2a` on a migration-only
synthetic PostgreSQL database. A new profile entered 25 pull-ups through
onboarding, then supplied a body mass of 70 kg and a 0.5 kg loading step.
The browser submitted eight scripted outcomes through the server's 1RM
ladder. The server confirmed a 31 kg additional-weight result.

The prescreen showed 17/17/17/17+ and 5×5 at +5.5 kg. Live Engine v2
showed all nine targets and the same load on each strength set. The UI
showed the planned four-minute, fifteen-minute and three-minute rests.
The completed session retained 17, 17, 17, 19 and five results of five.
The Journal, PostgreSQL snapshot and Plan agreed on the saved session,
the prescribed +5.5 kg and its single occurrence credit. The API then
prescribed B as 15×5 with a separate 5×3 strength block at +10.5 kg.

**Result — 1 passed in 10.2 s.** The synthetic database was removed
after checking ownership and zero clients.

### J4 weighted continuation from A to B at M=25

A separate Chromium run on the same executable tree completed A, then
shifted only its performed date three days back in the synthetic
database to model the required rest. The Plan opened B. The prescreen,
Live Engine and frozen recipe agreed on 15×5 volume and 5×3 at +10.5 kg.
The browser checked the one-minute volume rest and recorded all 20 B
results. Confirming technique and rest moved the next session to A and
updated the stored Volume B target to 16×5.

The Journal and PostgreSQL preserved the A recipe at +5.5 kg and the B
recipe at +10.5 kg, with all 29 results and two distinct occurrence
credits. **Result — 1 passed in 13.1 s.** The synthetic database was
removed after checking ownership and zero clients.

### J4 V5.6 transition and starting target cap

Two further Chromium runs on the `c360d2a` executable tree used separate
new profiles with baseline M=10 and M=50. Both used the same 70 kg body
mass, 0.5 kg step and scripted results in the 1RM ladder. The server
confirmed +31 kg and assigned strength A as 5×5 at +5.5 kg in both runs.

| Onboarding maximum | Level | Volume A targets | Saved Volume A results | Next Volume B prescription |
|---|---|---|---|---|
| 10 | Transition | 5/5/5/5+ | 5, 5, 5, 7 | 10×3 |
| 50 | Weighted | 20/20/20/20+ | 20, 20, 20, 22 | 17×5 |

The table distinguishes the M=50 cap on first prescribed targets from
the higher accepted AMRAP result. Both sessions recorded five strength
sets of five. The Journal and PostgreSQL kept the two blocks and the
frozen strength A load, and the Plan showed one credit per profile.
The next strength B recipe was 5×3 at +10.5 kg.

**Result — 1 passed in 7.7 s for each profile.** Both synthetic
databases were removed after checking ownership and zero clients.
These first runs executed A and checked the next recipe. Two independent
Chromium runs then also executed B, using the same executable tree in
`c360d2a` and protected `397594b`. Each run shifted only the performed
date of A by three days in its synthetic database to model the rest.

| Baseline | Completed B volume and strength | Next B volume | Persisted A and B results | Browser result |
|---|---|---|---|---|
| M=10 | 10×3, then 5×3 at +10.5 kg | 10×4 | 24 | 1 passed in 12.4 s |
| M=50 | 17×5, then 5×3 at +10.5 kg | 18×5 | 31 | 1 passed in 16.1 s |

The M=50 recipe returned to A with targets of 21, 20, 20 and 20 after
the initial 20-repetition cap. The original M=50 results of 20, 20, 20
and 22 survived. In both runs PostgreSQL confirmed the frozen strength
loads (+5.5 kg for A and +10.5 kg for B), the two Journal entries and
two distinct plan occurrence credits. Both synthetic databases were
removed after checking ownership and zero clients.

## J4 legacy Block B execution and progression

Chromium ran two sessions on the protected runtime `6e852be`, each with a
separate synthetic profile and migration-provisioned PostgreSQL. Both
showed four working sets targeting three repetitions, followed by an
explicit maximum attempt at 5/5. The Journal and database preserved five
targets and five results, with the maximum flag on the last set only.

The earlier acceptance line expected 3 → 4 for any working sets when the
maximum was six. The UI smoke first reproduced the discrepancy with four
sets of two. The [legacy STEP contract](../domain/PROGRAM_PLAN_V2.md#11-implementation-notes-wave-1c-305)
uses the working sets and the maximum. With the maximum fixed at six,
Chromium and PostgreSQL confirmed two different results:

| Block B logged sets | Summary and stored next target | Result |
|---|---|---|
| 2, 2, 2, 2, max 6 | 3 → 3 | 1 passed in 8.7 s |
| 3, 3, 3, 3, max 6 | 3 → 4 | 1 passed in 7.3 s |

The runner checked the live counter after the transition from block rest
to work. Both synthetic databases were removed after checking ownership
and zero clients.

## J4 course progression A to B on a profile with existing history

Chromium ran against API and frontend source `348d870`. The synthetic
profile had a 23-day-old course plan and two earlier training sessions.
After completing A, the harness shifted only that new synthetic session
back three days to model the course rest period.

The B start screen showed ten sets of five for volume and five strength
sets. Live used the 60-second volume rest setting. Completing B
advanced its volume from 10 × 5 to 11 × 5 and preserved the A targets.
PostgreSQL retained distinct occurrence credits for A and B, all 15 B
results in order, and both original training-session rows unchanged.

**A — 1 passed in 6.4 s. B — 1 passed in 5.8 s.** The initial harness
file filter located neither split scenario. After correcting the filter,
both scenarios completed. The isolated database was removed after
ownership and zero-client checks.

### J2 and J4 weighted course on a profile with existing history

Chromium ran on the executable tree of protected `74a7c7b` with an
M=25 profile, a 23-day-old plan and two earlier synthetic course
sessions. Only the first week was materialized in the fixture. Opening
Plan restored the missing `program_items` key and displayed the current
week. The run captured both earlier Journal cards at that point.

The simulated 1RM ladder confirmed +31 kg at body mass 70 kg. Session A
recorded 17/17/17/19 and 5×5 at a prescribed +5.5 kg. The fixture shifted
A's performed date three days back to model rest. B recorded 15×5 and
5×3 at a prescribed +10.5 kg. The next B volume became 16×5.

Both earlier cards matched the captured cards after A and after B.
The Journal ended with four cards. PostgreSQL confirmed all 29 new
results, the two original prescribed loads and distinct A and B credits.
**Result — 1 passed in 12.6 s.** The synthetic database was removed after
checking ownership and zero clients.

### J2 and J4 weighted course with mixed legacy and v2 history

Chromium ran on the executable tree of protected `15a20e6` with an
M=25 profile, a 23-day-old plan missing `program_items`, two earlier native
v2 workouts and one legacy workout entered through the backdated writer.
The fixture used the production tagging path for native sessions. A's
performed date was shifted by three days in the synthetic database to
model rest before B.

Journal, its calendar, Profile and Analytics agreed on three workouts
before the course and five after it. Analytics moved from 50 to 51 measured
minutes and continued to count one workout without a measured duration. The
three historical Journal cards matched after A and B. PostgreSQL still had
one legacy workout and one canonical copy linked to it. The two new course
sessions had all 29 expected results, stored loads of +5.5 and +10.5 kg
and distinct plan credits.

**Result — 1 passed in 1.3 min.** The isolated database was removed after
verifying ownership and zero clients.

### J2 and J4 mixed history across a calendar month boundary

On the same executable tree, the older legacy workout was dated in October
and the two earlier v2 workouts were dated in November. Chromium opened the
October calendar, selected the workout day and checked the legacy card.
After both weighted sessions, October still had one workout on the same day
and the card and its API record matched the originals. November went from
two workouts to four. Profile and Analytics went from three to five, and
Analytics measured minutes increased from 50 to 51. PostgreSQL confirmed
one linked legacy copy, all 29 new results and two distinct A/B credits.

**Result — 1 passed in 1.3 min.** The initial harness selector matched both
the calendar cell and the Journal date group. The passing assertion scoped
the selector to the calendar grid. The synthetic database was removed after
verifying ownership and zero clients.

### J2 and J4 weighted course after trial expiry

A separate Chromium run on the executable tree of protected `74a7c7b`
completed the same weighted A and B on an M=25 profile with a 23-day-old
plan and two earlier workouts. It preserved both earlier Journal cards,
saved 29 results and awarded separate credits at the same prescribed
loads. PostgreSQL confirmed that the subscription status remained `expired`
and that its expiry timestamp stayed identical. The fixture again modelled
rest by shifting A's date three days in synthetic PostgreSQL.

**Result — 1 passed in 12.2 s.** The isolated database was removed after
verifying ownership and zero clients. Native Telegram remains open for both
weighted scenarios.

## J8 backdated workout on a profile with existing course history

Chromium ran against API and frontend source `348d870` on a separate
synthetic profile with a 23-day-old course plan and two earlier workouts.
The Builder saved a workout with two sets of eight. The Journal form used
that workout to record eight and seven for the previous day.

The same record kept its workout link when the second result changed to
twelve. The Journal showed 8 and 12, offered Repeat and Open, and the
linked Workout showed the record once in its own history. Analytics
showed 20 repetitions and a best set of 12. Both earlier Journal cards
and the full Plan payload remained identical. The backdated entry had
no plan item or credit.

**Result — 1 passed in 4.5 s.** An initial harness attempt selected a
low-level Live Engine fixture whose manual form offered one set. The
passing run built the two-set workout through the normal UI. The
isolated database was removed after verifying ownership and zero clients.

### J8 preserving the historical record after renaming its workout

On the executable tree of protected `f772d3f`, Chromium logged an owned
workout for the previous day and renamed its definition through Builder.
After reload, the Journal showed the original title and the same eight
and seven repetitions. The session API retained the prescription
snapshot, workout link and block results. Opening the linked workout
showed its new name and one record in its history.

Both original Journal cards and the Plan response stayed identical.
PostgreSQL confirmed that the new backdated record had no course,
plan credit or spacing-violation flag. **Result — 1 passed in 6.3 s.**
The synthetic database was removed after verifying ownership and zero
clients.

### J8 preserving the historical record after archiving its workout

On the executable tree of protected `369c1a3`, Chromium logged an owned
two-set workout for the previous day and archived its definition through
Builder. The archive request returned 204 and the direct workout lookup
returned 404. After reload, the Journal showed the original title,
prescription and results of eight and seven repetitions. The workout
link disappeared from both the Journal sheet and the session details.

Both original Journal cards and the full Plan response stayed identical.
PostgreSQL confirmed that the definition was archived and the backdated
record remained stored without a course, plan credit or spacing-violation
flag. **Result — 1 passed in 6.7 s.** The synthetic database was removed
after verifying ownership and zero clients.

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
existing Starlette 422 deprecation warning).

### Browser activity edit alongside a credited course

Chromium ran against API and frontend source `348d870` on an isolated
synthetic profile with a 23-day-old plan and two previous course workouts.
The browser completed nine sets of a new V5.6 course workout and verified
that only one occurrence credited that session.

The Journal form added 45 minutes of running and then edited the same card
to 60 minutes of cycling on the previous day. The cards showed the new
activity name, duration and date. Analytics added one workout in
«Другая активность», first with 45 minutes and then with 60. The exercise
panels, plan response, course credit and all three prior Journal cards
stayed identical. The activity had no plan-item link.

**Result — 1 passed in 7.4 s**, zero retries. The isolated database was
removed after ownership and zero-client checks. This covers the activity
journey in Chromium on one aged profile. Device acceptance remains open.

### J9 paired browser verification on fresh and aged profiles

Chromium used the executable tree of protected `9f092be` on a new
profile with an empty history and a 23-day-old profile with two earlier
workouts. The new profile added the course through its detail screen.
Each profile then completed a nine-result course workout with one credit.

The Journal added a 45-minute run and edited the same card to 60 minutes
of cycling on the previous day. The category and totals in Analytics
reflected each write. On both profiles the Plan, the course credit and
the exercise panels matched the originals, as did all prior Journal cards.
The activity had no plan item.

**Result — 2 passed in 8.3 s and 9.4 s.** The first fresh-profile attempt
stayed inside the course detail screen. The passing scenario returned to
the main screen before opening Plan. Both synthetic databases were removed
after verifying ownership and zero clients.

### Moving the same activity across a week and month boundary

On the executable tree of protected `afe36ad`, Chromium completed one
nine-set V5.6 workout and checked its Plan credit on each of two synthetic
profiles, one fresh and one with two prior course records. Each profile
logged a 45-minute run on October 31, 2026, then edited the same entry to
60 minutes of cycling on November 2. The October calendar and Journal
lost the activity, and the November calendar and Journal gained it.

Both weekly Analytics series matched the API before and after the edit.
The extra workout and 45 minutes in the October 26 week moved to one
extra workout and 60 minutes in the November 2 week. The credited
course, previous Journal cards, full Plan and exercise panels retained
their values. The external activity had no plan item.

**Result — 1 passed in 8.4 s on the profile with history and 1 passed in
9.3 s on the fresh profile.** Each synthetic database was removed after
verifying ownership and zero clients. Native Telegram acceptance remains
open.

## J12 future-week credit on a profile with old plan history

Chromium ran against the application built from
`8efcbd2ca9bdc9ba462a7a2b376f72e7bfff4b7e` and a migration-only synthetic
PostgreSQL target. The [aged fixture](../../scripts/qa/provision_staging_identities.py)
created a plan 23 days in the past, one materialized week, two completed
historical workouts and a course snapshot missing `program_items`. Those
conditions were checked before the browser opened Plans.

The browser trace adapted the [existing J12 scenario](../../webapp-frontend/e2e/scenarios/fix-wave1/later-weeks.spec.ts)
to start from that profile and compare its original Journal cards. The Plan
API repaired the snapshot. Each of weeks +1 through +4 showed two actionable
occurrences before and after reload. The +4 start returned engine version 2
and targeted one occurrence. The workout completed through the UI. On reload,
the current week stayed at 0/2, week +4 showed 1/2, and the ten occurrence
IDs across those five weeks were preserved. The other nine had no credit.
The Journal gained one card and both prior cards were identical.

**Result — 1 passed in 10.0 s**, with zero retries. The synthetic target was
removed after ownership and zero-client checks. This covers one old plan
representation in Chromium. Native Telegram and the complete J12 matrix
remain open.

### J12 next-week credit on a profile with old plan history

Chromium ran on the executable tree of protected `321da45`. The
synthetic profile had a 23-day-old plan, one materialized week, two
completed workouts and a course snapshot without `program_items`.

Weeks +1 through +4 each showed two startable occurrences before and
after reload. Chromium returned from +4 to +1, started a V5.6 workout
from the next week's Plan and completed it in Live Engine v2. After
reload the next week showed 1/2 and the current week stayed at 0/2.
All ten occurrence IDs stayed the same. Only the selected +1 occurrence
earned credit, and the two earlier Journal cards stayed identical.

**Result — 1 passed in 9.2 s.** The synthetic database was removed
after verifying ownership and zero clients.


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
The target was removed after ownership and zero-client checks.

### Browser availability and calendar on profiles with existing history

Chromium ran on API and frontend source `348d870` against two separate
synthetic profiles with 23-day-old plans and two earlier workouts each.
After completing a new V5.6 session, the browser reloaded Plan and checked
its current-week date range, the 1/2 counter and the availability message.

| Profile local day | Three-day availability date | Current-week Plan message |
|---|---|---|
| Moscow, Thursday 19 November 2026 | Sunday 22 November | «Доступно с 22 ноя» |
| Kiritimati, Friday 20 November 2026 | Monday 23 November | «Не успеть на этой неделе · старт с 23 ноя» |

The Plan spacing record and the successor occurrence reported the same
date as the independently checked calendar. Live v2 rejected an early
start with HTTP 409 `too_early` and that date. The legacy HTTP endpoint
returned the same date. Switching to the next week did not expose an
early start. Both old Journal cards remained identical, the new workout
kept one credit, and no active session was created by the rejected start.

**Moscow — 1 passed in 7.0 s. Kiritimati — 1 passed in 7.5 s.** The
initial Moscow request omitted the required client session ID and got
HTTP 422 from validation. The corrected request reached the rest gate.
Both synthetic databases were removed after ownership and zero-client
checks. Manual K3 flagging and native devices remain outside this check.

### J11 first allowed day on a fresh profile

On the executable tree of protected `209bfc7`, Chromium enrolled a fresh
synthetic profile and completed V5.6 A. The harness modelled the rest days
by changing only the performed date of that new session in the isolated
database. The API and browser used the same current Moscow date throughout.

With A dated two days earlier, Plans showed tomorrow's start date and
no Start button. A direct request for that occurrence returned 409
`too_early` with the same date, created no active session and left one
completed Journal card.

With A dated three days earlier, the same occurrence became available.
Chromium started B through Plans and completed it. Plans showed 2/2
with separate credits for A and B, and A's prescription, results and
credit stayed intact.

**Result — 1 passed in 15.2 s.** The synthetic database was removed after
verifying ownership and zero clients.


### J11 retrospective main-session spacing flag (K3)

The [J11 HTTP regressions](../../tests/test_web/test_v2_plan_occurrences.py)
use synthetic PostgreSQL. On `27b9852`, the two cases that expected a
violation failed because the stored flag was false. The two boundary
controls passed.

With the fix, the Wednesday live start after a Monday main workout
still returns 409. A retrospective Wednesday main workout saves with
`spacing_violation=true`, while Thursday saves with false. Both checks use
Monday's workout with Friday's already recorded in history. Replaying
the same request returns one Journal entry and leaves its plan item empty.
Legacy Workout history yields a violation at 23:59 and allows the session
with a false flag at the next local midnight across a week and month rollover.

The four cases passed within 89 focused backend checks. This receipt
covers the supported complete-course API and stored flag. Device
acceptance is tracked separately.

### J11 K3 and the existing Journal recording form

On protected `aeefc39`, four HTTP checks passed in 10.34 s. They exercised
the early and allowed course dates and both sides of local midnight with
legacy history. These requests use `source=plan` and a program inclusion.

In a separate 5.9 s Chromium run, «Тренировку из моих» sent
`source=backdated` with the selected workout and its entered results.
The Journal showed the new card and kept both existing cards. The Plan
matched its original response. PostgreSQL confirmed that the new record
had no course inclusion or plan credit and its `spacing_violation` flag
was false. The Journal form exercises the owned-workout recording path.
Course-specific retrospective recording is covered by the HTTP checks.

Both synthetic databases were removed after verifying ownership and zero
clients.

## J5 pause and deadline on a profile with old plan history

Chromium ran against API and frontend source `8efcbd2` on an isolated synthetic
PostgreSQL database. The fixture had a 23-day-old plan and two earlier Journal
cards. The browser started a two-set Builder workout through the plan. The
timer advanced it into the first set. Pausing during rest preserved the
server-reported remaining time through a reload. After resuming and closing
the tab, reopening returned to the second set of the same session. The Journal
retained the two earlier cards and recorded the new results of five and four.

**Result — 1 passed in 16.0 s.** The first attempt read the Journal before the
server acknowledged completion. The passing run waited for that acknowledgement.
The database was removed after verifying ownership and zero clients. This covers
browser tab reopening and reload on one aged profile. Native Telegram background
return and audible cues still need device evidence.

### J5 reopening after the rest between two blocks

One Chromium run on protected runtime `27b9852` used a synthetic profile
with two earlier Journal cards. After recording three repetitions, the
browser confirmed that the server had entered a six-second block rest.
It closed the tab and waited until that server deadline expired.

The same session reopened during the five-second prep of the second
block. The server anchored prep to the preceding rest deadline, and the
visible timer matched the remaining time within one second. The plank
then ran and saved five seconds automatically. The Journal retained both
earlier cards and saved the new results in one card. The Plan reported
exactly one credited occurrence and the active session cleared.

**Result — 1 passed in 21.0 s.** The synthetic database was removed
after verifying ownership and zero clients.

### J5 paired browser return after inter-block rest

Chromium ran the same inter-block scenario on both profiles using the
executable tree of protected `a55fb13`. The fresh profile started with an
empty Journal. The 23-day-old profile started with two Journal cards.
After the first result of three repetitions, the server reported a
six-second rest between blocks. Chromium closed the tab through that
deadline and reopened during the five-second prep for the plank.

The server returned the same session and anchored prep to the exact rest
deadline. In both runs the visible countdown matched the remaining
server time within one second. The plank saved five seconds automatically.
The Journal gained one completed card, the aged profile kept both earlier
cards, the Plan credited exactly one occurrence and the active session
cleared on both profiles.

**Result — 2 passed, 21.7 s each.** Both synthetic databases were removed
after verifying ownership and zero clients. Native Telegram background
return, audible cue timing and watch behavior remain open.

### J5 paired browser return after 60 seconds hidden

On the executable tree of protected `a55fb13`, Chromium kept the training
tab mounted on a fresh profile and on a 23-day-old profile with two prior
workouts. After the first set, the server reported a rest deadline. The
scenario set document visibility to hidden for 60 real seconds and then
dispatched a visibility event to return to the workout.

The refreshed server state showed the same session in its second set,
with the start of that set aligned to the original rest deadline. The
instrumented Web Audio oscillator recorded cancellation of the scheduled
rest cue when the page was hidden. The cue stayed cancelled on return.
Both profiles recorded five and four repetitions in one Journal card
with one plan credit. The aged profile retained its two earlier cards.

**Result — 2 passed, 1.2 min each.** Both synthetic databases were removed
after verifying ownership and zero clients. This was a Chromium
visibility simulation with a real server clock. Telegram device
backgrounding, audible cue timing and watch behavior remain open.

### J5 offline interval pause on a profile with history

Chromium used the executable tree of protected `b70ac98` on a 23-day-old
profile with two earlier workouts. It paused the first interval while
offline, closed the tab and waited 25 real seconds. On reopening, the
client sent the saved pause before projecting the session. A separate
browser context saw the same paused session and remaining time.

After resuming, the interval finished once and Plan retained a single
credit. The Journal added one card and preserved both earlier cards.
The queue contained no unsent work on the optional review screen. Its
storage key cleared after saving the review. The first harness assertion
checked for deletion while the optional review screen was still open.

**Result — 1 passed in 51.5 s.** The synthetic database was removed after
verifying ownership and zero clients.

### J5 audio timeline and phase-end playback

The shared engine vector verifies rest warning, countdown and rest-end
timestamps, including their order at the next work start. It also verifies
an empty timeline during pause. On protected `901d94b`, the Python suite
passed 36 cases and the TypeScript suite passed 34. The phase-end Web Audio
unit test passed one case covering timing, cancellation and volume.

The session API exposes hook timestamps from the engine. The current
live screen plays the existing phase-end tone based on the server deadline
and cancels it while hidden. The paired Chromium simulation above verifies
cancellation and return without replay for that tone. Physical Telegram
backgrounding, actual audio timing on the device and watch behavior still
require device evidence.

### J5 live API timestamps across pause and resume

Chromium drove a real 30-second rest on the executable tree of protected
`901d94b` with a synthetic profile and two earlier workouts. The live API
returned `warn_10s`, `count_3`, `count_2` and `count_1` at the expected
offsets before the server deadline. `rest_end` and the next `work_start`
shared the deadline in that order.

The API returned an empty timeline on pause and preserved the remaining
time through reload. After resume, the six timestamps aligned with the
new server deadline. Instrumented Web Audio observed one scheduled
phase-end tone within one second of that deadline. The rest expired
naturally, and the Journal recorded five and four repetitions with one
plan credit and both earlier cards intact.

**Result — 1 passed in 39.4 s.** The synthetic database was removed after
verifying ownership and zero clients.

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
removed after ownership and zero-client checks.

### Browser edit on a profile with existing history

Chromium ran against API and frontend built from protected main
`348d870fe3d41b3fad9680e39e2fd5182c023057`. The isolated profile had a
23-day-old plan and two completed course workouts. A two-set Builder workout
was started from the plan and completed on Live Engine v2 with more than a
minute of server-measured time.

The Journal form changed the date to Monday of the previous week and the
first result from five to eight. The card moved to the new day and showed
eight and four. The Analytics weekly chart moved the workout to the previous
week. Its API moved the measured minutes with it, preserved the totals, and
reported 12 repetitions for the exercise. The browser showed the same
repetition total. The edited record retained its ID, measured duration,
prescription and plan item. Both earlier Journal cards stayed identical.

**Result — 1 passed in 1.3 min**, including the real timer wait. The first
attempt expected the edited set result in isolation. The detail view showed
both results, and the corrected browser assertion checks both. The synthetic
database was removed after ownership and zero-client checks.

### J10 paired browser edit on fresh and aged profiles

On the executable tree of protected `9f092be`, Chromium ran the same
plan-started v2 edit on a fresh profile without history and a 23-day-old
profile with two earlier workouts. On both, the Journal moved the workout
to the prior week and showed the edited result of eight and four. The
Analytics weekly chart and API moved the workout and its measured minutes
to the same week while keeping aggregate totals unchanged. The exercise
panel showed 12 repetitions. The record ID, measured duration, prescription,
definition version and single plan credit stayed the same. The two earlier
cards on the aged profile also matched their originals.

**Result — 2 passed, 1.3 min each.** Both isolated databases were removed
after verifying ownership and zero clients. Native Telegram remains open.

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
| §6 in-flight v1 and cached old clients | TARGETED_PASS for a synthetic direct v1 session at `32c9a1a` and a planned v1 session on a legacy aggregate at `e15bd69` through aged plan convergence and API replay. Historical-bundle Chromium confirms an open planned v1 session with a pending offline set on `10e5b41`, plus offline completion both within a week and across weekly rollover. | Actual cached Telegram WebView and cutover rehearsal remain open. Keep v1 until separate acceptance. |
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

### Follow-up at `a46ec0e`: paired mixed history, archived workout and plan credit

Two synthetic users replayed the same events on protected main: a legacy
workout on September 30, a 25-minute manually logged workout on October 1
whose definition was then archived, and a 40-minute course workout on
October 5. Both users used the same course version. The aged profile had
one legacy copy without a key and a course credit linked through an old
weekly aggregate. The current profile retained its existing keyed copy and
per-occurrence link.

A dry run predicted one legacy binding only for the aged profile and left
its copy unkeyed. Apply bound the old copy. Plan convergence restored the
course credit to the same occurrence on both profiles. The two current-week
projections matched at 1/3 and the following week at 0/3. A second apply
for both history and plan convergence reported zero mutations.

The archived Journal card on each profile kept its title, prescription,
results and duration. The Journal list, calendar, Profile, Analytics and
canonical storage each counted three workouts. Analytics reported 65
measured minutes and one workout with unknown duration. Both profiles had
two workouts and 25 measured minutes in the week of September 28, then one
workout and 40 minutes in the week of October 5. Exercise panels and
distribution matched after removing synthetic exercise IDs.

**Result — 5 passed in 14.31 s**, including the focused pair, both existing
archived-history calendar cases and both existing current/aged plan cases.
The isolated database was removed after ownership and zero-client checks.

### Mixed history when its former workout definition is absent

The paired check was repeated on the same runtime with the older
synthetic profile's archived definition absent. Journal still displayed
the frozen title, recipe, results and 25-minute duration. The views
still counted three workouts and 65 measured minutes. The older
course credit converged to the same occurrence as the current profile.

The missing definition removed the proof needed for safe deletion.
The card reported deletion unavailable and the real endpoint refused
the request with HTTP 409 and the same reason. The first test had
expected that permission to stay available. The corrected run asserts
the documented protection and compares the remaining historical facts.

**Result — 3 passed in 8.47 s**, including the focused variant and two
adjacent workout-link tests. The isolated database was removed after
ownership and zero-client checks.

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

### J2 cohort reads before and after Plan convergence

On protected `7016323`, the real HTTP routes read Journal lists, calendar,
Profile and the complete Analytics response on six synthetic profiles.
The reads used one 56-day range and covered the baseline, dry run, apply
and second apply. Each profile returned identical JSON at all four stages.
Journal, calendar and Profile counts agreed with both Analytics totals
and with the sums of Analytics weekly and category counts.

| Profile | Workouts on every read surface |
|---|---:|
| Fresh with a Plan | 0 |
| Aged, current-format Plan | 2 |
| Aged, legacy inclusion snapshot | 2 |
| Expired trial | 2 |
| Active, no Plan | 0 |
| Active with a synthetic Stars subscription | 2 |

The dry run predicted 24 changes without writing any rows. Apply made
the same 24 changes: one snapshot repair, 15 weeks and eight Plan items.
The second apply and final dry run both reported zero changes. All eight
historical sessions and 72 set results remained identical, along with
subscription rows and expiry values, program access and session credit
links. The Stars row was created in the synthetic fixture without a
payment provider. This check covered Plan convergence with native
training rows. The mixed legacy/v2 history check above covers the
separate history convergence path.

**Result — passed on a migration-only synthetic PostgreSQL database.**
The first harness attempt expected live-session titles on fixtures
written by the historical logger without Plan item links. The passing
check compares the returned titles and all other response fields before
and after convergence. The database was removed after verifying ownership
and zero clients. Staging rehearsal, restore and physical-device evidence
remain open.

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
