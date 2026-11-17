# Crimpd black-box audit — 2026-11-10

Bounded pass executed on **Crimpd 8.5.3 (8050300)**. This supersedes the initial
blocked checkpoint. Historical DONE rows are not evidence of this pass.
No product code, deploy or production data changes. Crimpd supplies UX evidence,
not progression formulas.

## Provenance

Read AGENTS.md, CLAUDE.md, constitution, project spec/implementation plan,
product-reference and crimpd-reference skills, CRIMPD_FULL_PARITY_8_5.md,
FUNCTIONAL_AUDIT_WAVE_1.md, and wave1/A-reference COVERAGE.md / GOLDEN_TRACES.md.
All requested files exist. Baseline: `7c89ce622749608fc4c9c27daa0062272f3efccb`.
Prior pushed work was preserved; separate branch `codex/crimpd-blackbox-20261110`.

**OBSERVED** = exercised here; **INFERRED** = interpretation with its basis;
**UNKNOWN** = not established. Every case below uses **8.5.3 (8050300)**,
verified through package-manager fields before and after testing. Google Play
installer; no APK extraction/decompilation.

The existing `ref_pixel6_play` AVD was started without wipe/install/data clear.
Window control returned `Invalid app` twice; the owner explicitly authorized
ADB input, UI inspection and screenshots. No new environment, account, token,
subscription or acceptance of terms.

Initial emulator DNS failed: cached catalog, unloaded images, workout-type
wizard spinner. One graceful restart of the same AVD retaining userdata, with
the host's existing DNS resolver, restored loading. This is an environment
incident, not an established Crimpd defect. Final device check: connected.

The existing signed-in account was retained. Other workouts, plans, profile
attributes and history were not edited. Clean-account states remain UNKNOWN
under the no-reset/no-new-account restriction.

Published proof is limited to visually reviewed synthetic/public screenshots
and sanitized observations below. Raw XML, general journal screens,
account-derived catalog fields and emulator logs remain outside the repository.
XML sometimes included hidden controls or lagged behind a sheet transition;
screenshots determined visible state. Reproduce by labels, not coordinates.

## Executed scenarios

All rows: **8.5.3 (8050300)**. Unique data prefix: `REF TEST - 20261110`.
Proof links are relative to this report. OBSERVED facts are scoped to this
account and route, not every Crimpd configuration.

| Case / old gap | Initial state and reproducible steps | OBSERVED result | Sanitized proof | Remaining UNKNOWN |
| --- | --- | --- | --- | --- |
| C01 / R-J2 R2,R4; E4,E12 | Home → + → Create Custom Workout → Custom Workout → search `REF TEST - 20261110 - Exercise` → Create Exercise | No-match row reads `Create Exercise: REF TEST - 20261110 - Exercise`. Opens **Adjust Sets/Reps directly**. Defaults: 2 sets, 1 rep, 01:00 between sets; Rep Timer and Log Resistance off. No separate metric-type form on this route. | [Form](evidence/c01-create-exercise.png) | Later library persistence; zero-exercise Save; clean-account library contents; other types |
| C02 / R-J2 R6 | C01 → enable Rep Timer (00:03) and Log Resistance (Free Weight) → Add Exercise → Conditioning → Upper Body → Edit Workout Details → name `REF TEST - 20261110 - A` → Save → pencil → append ` - Edited` → Save; later reopen from plan/journal | Save lands on **Workout Detail**, with Start / Log / Favorite / Add to Plan. Exercise: 2 sets × 1 rep × 00:03; 01:00 rest per set. Edited name persists across navigation and background return. | [Reopened detail behind mini-player](evidence/c08-back-live.png) | Protocol edit after initial save; process-death persistence |
| C03 / R-J3 R1 | Home → Aerobic Capacity → Featured → 1 On 1 Off → Start → Play → Pause → Android Back → mini-player X | Starts without a plan prompt. UP NEXT precedes GET READY; pause shows red PAUSED. Back exposes mini-player; X removes it. Catalog trial not saved. | [Home](evidence/c03-home.png), [category](evidence/c03-category.png); player transcription only, to exclude account-derived grade defaults | Entire 20-minute protocol; free/planned distinction in journal |
| C04a / R-J7/J8 R3; N5 | C02 session after first 3-second work, rest paused 00:59.3 → Android Home → wait 5 s → foreground | Still **PAUSED 00:59.3**, same set panel. | [Before](evidence/c04-pause.png), [after](evidence/c04-paused-return.png) | Lock, process kill, long background intervals |
| C04b / N5; set retention | Same session → Set 1 Free Weight + once, synthetic 1 kg → resume → screenshot → Home → wait 8 s → foreground → wait 2 s → screenshot → pause | **REST 00:21.7 → REST 00:11.2**, weight 1 kg retained. Displayed reduction 10.5 s includes command/foreground overhead. Short-background advancement observed; implementation not inferred. | [Before](evidence/c04-before-bg.png), [after](evidence/c04-after-bg.png) | Reconciliation mechanism; abnormal-exit retention |
| C05 / R-J1 R11 | Same session in rest → Next Set (skip remaining rest) → second-set UP NEXT → Play → final 3-second work → Log Workout review → X → player down-chevron → own Logged Workouts | DONE opens review automatically: date, effort, both sets/reps/weight, notes, Save. X returns to DONE without confirmation. Own history then explicitly says no workout logged in this time frame. | [Review](evidence/c05-done.png), [empty own history](evidence/c05-log-area.png) | Server-side drafts; duplicate prevention. Rest was skipped, so this is not an uninterrupted protocol trial |
| C06 / R-J1 R12; R-J5 R3 | C05 empty own history → Log Workout → Save → own entry → Edit → Cancel → reopen entry → Clone → Cancel → leave detail → Logbook → exact synthetic entry → Home/foreground | Form retains 1 kg after C05 dismissal. Save creates one entry: Easy, 100%, +1 kg, TUT 6 s, Est. Duration 3 m, Workload `-`. Edit exposes date, completion presets 25/50/75/100%, effort, per-set reps/weight/effort, Add Set, exercise/additional notes, Delete. Clone has same values and Save/Cancel; no copy saved. Entry opens from Logbook and remains after background return. | [Own entry](evidence/c06-entry.png), [Edit](evidence/c06-edit-form.png), [Clone](evidence/c06-clone-real.png); general journal screenshot withheld | Clone date default across dates (source/today both Nov 10); Save from automatic DONE review; cold restart; analytics |
| C07 / R-J4 R1,R7,R8; E2,E10 | Own workout → Add to Plan → Create Training Plan → name `REF TEST - 20261110 - Plan`; retain Nov 16 start and 6 weeks → Save → later open Week 2 | In this state Add to Plan opens creation directly. Defaults: November 2026, 6 Weeks, Nov 16. Text: “Only one training plan may be active concurrently.” Save opens weekly-volume overview, own workout at zero. Week 2 (Nov 23–29) has 0/0 category bars and “No workouts planned for this week. Enjoy the rest!” No Schedule button there; pencil and Plan tab remain. | [Create](evidence/c07-add-plan.png), [empty week](evidence/c07-week2.png) | Truly empty Plans tab; current active week marking; multiple-plan enforcement; plan without any member |
| C08 / R-J2 R8,R9; R-J4 R3–R5 | C07 → Weekly Volume pencil → first-week + once → Save → leave/reopen Training Plans/Upcoming → Schedule → Monday → Save → Schedule → deselect Monday/select Tuesday → Save → own row → Start → Play → Android Back → mini-player X | One + changes **0 → 0.5**. Schedule opens **Week 1 Schedule**, seven-day grid. Monday gets 0.5; row changes THIS WEEK → MONDAY. Re-selection moves row to TUESDAY. Row opens Workout Detail, then Start opens player. Back leaves running mini-player; X removes it without confirmation. Tuesday verified on return to plan. | [Volume](evidence/c08-volume.png), [Schedule](evidence/c08-schedule.png), [Monday saved](evidence/c08-schedule-save.png), [live Back](evidence/c08-back-live.png) | Completion-to-plan-credit; fraction semantics/limits; repeated allocations/week boundaries |

C01→C02 actual wizard route: **Select Workout Type → Select Exercise → Adjust
Sets/Reps → Select Category → subcategory → Edit Workout Details → Save**.
No `n/6` pager was visible on inspected screens. This qualifies the historical
description; it does not establish every type's flow.

C05 empty-history text: “You have not logged this workout during this time frame.
Once you have completed this workout, select the 'Log Workout' button to record
your results.” This is the new synthetic workout's own history, not an empty
account or proof of server-side deletion.

In C04 details were collapsed before start and expanded by paused rest; Next
Set collapsed them again. A catalog-workout pause during GET READY also showed
an expanded panel. **UNKNOWN:** whether phase, pause or another transition
triggers expansion. An “only on rest” auto-expansion rule is not established.
Audible final-ten-second cues were not tested.

## Differences from prior assumptions

- Save → Detail, plan row → Detail → Start, and saved log → Logbook now have
  direct observations, scoped to the tested routes.
- Create Exercise leads directly to set/rep configuration; the old unobserved
  form description cannot support a separate metric-type dialog.
- Short native background countdown advancement is observed. Our PWA was not
  tested; the native result does not establish our app's behavior.
- Dismissing review differs from saving: no entry appeared, while a later form
  retained inputs. Backend draft storage and crash recovery remain UNKNOWN.
- Schedule is a separate day-allocation grid after weekly volume, including
  an observed 0.5 quantity; this is not evidence for drag-and-drop.
  [Tuesday after rescheduling](evidence/c08-tue-save.png).
- Empty-week wording and absence of Schedule are now observed. The old statement
  that no verbatim empty-state text survives is historical.

These qualify the reference documentation, not a fresh verdict on our product's
parity. No product comparison run or formula extraction was performed.

## Unexecuted scope and ledger

C09 Skill Template instantiation and C10 completion-to-plan-credit comparison:
**NOT RUN / UNKNOWN**. Also unknown: zero-exercise Save, exercise-library
persistence, clean-account onboarding/empty states, subscription expiry, delete
semantics, process-kill recovery and audio cues. No purchases/new terms or edits
to old history were used to close gaps. No continuous monitoring configured.

Retained synthetic objects:

- Exercise `REF TEST - 20261110 - Exercise`.
- Workout `REF TEST - 20261110 - A - Edited`.
- One explicitly saved log, Nov 10: 2 × 1 at 1 kg. No Clone copy saved.
- Future six-week plan `REF TEST - 20261110 - Plan`, Nov 16 start, first-week
  volume 0.5 assigned Tuesday. Trials dismissed/cancelled are not this saved log.

No automatic deletion of retained test evidence. Final state: Home, no
Return-to-workout mini-player; emulator connected, version unchanged.

Validation: documentation/screenshots only; `git diff --check` and local
proof-link/PNG checks. Product tests not run: product code untouched.
Next bounded audit: later-library/zero-exercise validation, explicit DONE-review
Save plus plan-credit test on retained synthetic objects, then C09 if free of
purchase/terms gates. None of these should be inferred from this report.
