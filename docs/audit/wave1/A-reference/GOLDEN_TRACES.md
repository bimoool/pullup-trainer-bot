# Crimpd 8.5.x golden traces (secondhand reference) — Wave 1 / A-reference

Umbrella: bimoool/pullup-trainer-bot#295. Read-only agent; no Crimpd access.

## 0. Evidence rules and honest limits

- The Crimpd lab (`~/android-ref-lab/`) is **absent** in this container (`ls ~/android-ref-lab` fails). A filesystem-wide search for `*crimpd*`, `REF_MAP.md`, `FLOW_INDEX.md`, `CRIMPD_PRODUCT_REFERENCE.md` found **no reference material** — only our own docs/e2e spec (`docs/CRIMPD_FULL_PARITY_8_5.md`, `docs/CRIMPD_VISUAL_GAP.md`, `.claude/skills/crimpd-reference`, `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` [not read, it is ours]). No dumps, no screenshots of Crimpd exist in the repo (`docs/captures/wave13/` is **our** app).
- Every Crimpd fact below therefore comes from earlier sessions' paraphrases. Tags:
  - `OBSERVED` = secondhand: a repo doc states it as seen in Crimpd 8.5.3 (cites a capability id H/W/C/P/X/J/A/R/N/D, F#, RM §, d/<dump>). Format `(doc:line)`.
  - `INFERRED` = my reasoning from partial evidence or public knowledge of Crimpd; reason given.
  - `UNKNOWN` = not documented.
- Source abbreviations: **PAR** `docs/CRIMPD_FULL_PARITY_8_5.md`; **UXA** `docs/UX_REFERENCE_AUDIT.md` (its "Reference (OBSERVED)" column); **VG** `docs/CRIMPD_VISUAL_GAP.md`; **SKL** `.claude/skills/crimpd-reference/SKILL.md`; **PS** `docs/plan-and-specs.md`; **ARCH** `docs/architecture-multicourse.md`; **CAP** `docs/captures/wave13/INDEX.md`.
- **Caution on provenance.** PAR's first column ("Crimpd feature") + "Reference evidence" column are the only structured Crimpd observations; the other columns describe OUR app and were ignored. PS (dated 2026-09-19) says it was written from "60 screens + APK analysis" (PS:3); later lab work is stated to be "black-box only, no decompilation" (PAR:8). PS sections 10.x are OUR spec "= Crimpd X", mixed with our extensions — used here only as INFERRED, never OBSERVED. Items the docs themselves flag `(unobserved)` are not observed: GET READY last 10 s (X13), background timer (N5), Edit/Clone Log form (J5/J7), plan "Schedule" beyond its label (P9), plan "Clone" beyond menu label (P11), attribute history screens (R2), Delete account (R16, "not tapped").
- Known doc ambiguities: (a) PAR:94 says "Crimpd also allows one active" plan, while PAR:92 lists In Progress / Upcoming / Completed tabs (implies several plans over time). (b) Profile: SKL:24 lists Profile as a bottom tab; CAP:18 says in the reference it is a hamburger menu (G2, PAR:205: Help / Settings / Logout). (c) Home widget: SKL:28 / PS:10.1 once planned a week widget; PAR:57 (H14) records Crimpd Home has **no** plan/streak widget — treated as OBSERVED because it is a Crimpd-side negative recorded under an id.

## 1. Answers to the explicit questions

1. **How do plans relate to workouts?** Workouts are standalone objects (catalogue categories, "My Workouts", favourites; each has a Workout Detail page with Start / Log / Favorite / Add to Plan) — OBSERVED (PAR:63-69, VG:29). A plan is a separate container laid out in weeks (week stepper with dates and a phase chip, per-row done counters "0/1") — OBSERVED (PAR:98-99). A workout enters a plan via "Add to Plan", a **2-step sheet: new plan / existing plan** (PAR:69; W5, F8), or a **Skill Template** (level, hours/week, week schedule, phases) is added to the plan list (PAR:96-97). So: workout ⟂ plan; plan = placement of workouts in weeks/days; template = ready-made plan. How a template is instantiated (start date prompt, copy vs link) is UNKNOWN.
2. **Can a workout start without a plan?** Yes. OBSERVED: Workout Detail has Start (W3, W9; X1) independent of plan membership (PAR:66, UXA:43), custom workouts have their own detail page (d/custom_workout_detail, PAR:63); the Home "+" sheet has a session-start option (H12, PAR:56) and there is a free "Start Open Climbing Session" banner (H10, PAR:54). Whether a free session is recorded identically in the Logbook: INFERRED yes (Logbook shows the logged workout; PAR:135, 141).
3. **How are custom exercises created?** OBSERVED: in the builder's "Add exercise" screen (search field + alphabetical list) a no-match search shows a **"Create Exercise: <query>" row** (C3-C4; UXA:34, PAR:80). The form that follows (fields, type choice, whether the exercise persists into the library) is UNKNOWN. PS:258 (our spec) says "Create Exercise: <name> with choice of metric_type" — not evidence for Crimpd.
4. **What is reflected in history/analytics after completion?** OBSERVED: after DONE a log-review sheet appears (workout effort + set table + Save; X9-X11; UXA:49, PAR:116, 123). Logbook cards show intensity, completion, TUT, duration, workload (J4, PAR:135); entry opens a detail sheet with View/Edit/Clone/Delete (J5, VG:31). Analytics metrics: Workouts, Duration, TUT, Workload (A1-A2); range 1 Mo/3 Mo/Custom; weekly chart; distribution sunburst by type; multi-month summary table; CSV; "live recompute on log add/delete" (A8) (PAR:150-160). Whether completing a workout from a plan updates plan counters: INFERRED (counters exist, P3/P9-P10) but the link is not recorded.
5. **Does Crimpd ship a system exercise library / workouts?** Partly OBSERVED: the exercise picker shows an "alphabetical list" and a screen titled "Exercises" (UXA:34; VG:17); Home has category rows "N Workouts" (H2-H4, PAR:47), curated playlists with a creator (D1, PAR:187), category collections (D3), Skill Templates (D4), Progressions (D5), assessment tests (D6, H11). So system content exists. Exact exercise count / whether the alphabetical list is system-only or includes user exercises: UNKNOWN. Public knowledge (INFERRED): Crimpd is a climbing-training app with a large built-in exercise/workout catalogue and a Crimpd+ subscription.

## R-J1 — Fresh user -> discover a plan -> add/start -> workout -> log sets -> complete -> Logbook -> Analytics

**START STATE:** new account, no plan, no personal workouts, no logs.

- **R1** `UNKNOWN` First launch / onboarding / account creation. Only known: an account with password exists (R10 "Change password", PAR:180) and delete-account exists (R16, PAR:179). No doc describes the first-run flow or default content.
- **R2** `OBSERVED` Lands on **Home** (catalogue), not on a plan; bottom nav of 5 tabs, outline icons + label (VG:20; SKL:24; PAR:57 "Home has no week/streak widget"). Home: sticky header = search pill + round "+" (H1, PAR:44), category rows as horizontal carousels "N Workouts" (H2-H4, PAR:47), featured playlists (H5), banner "Create Custom Workouts" (H6), My Workouts grid (H7), "Log Cross-Training" (H8), Favorite Workouts row (H9), "Start Open Climbing Session" (H10), Assessment Tests carousel (H11) (PAR:44-56; order in VG:28).
- **R3** `OBSERVED` Discover via (a) category row -> Category screen (info, Featured / All tabs; d/category_all_tab, PAR:48); (b) search with live filter, "FOUND N", clear, filters category/equipment/favorites/home-only/tests-only (S1-S4, PAR:45-46); (c) Training Plans tab -> **Skill Templates grid** (P6, PAR:95); (d) playlists (D1, PAR:187).
- **R4** `OBSERVED` Template detail: level, hours/week, week schedule, phases (P7; d/plan_template_schedule, PAR:96). Workout Detail: hero photo, overview video, 4 round actions Start / Log / Favorite / Add to Plan, exercise rows "sets - reps - rest", "Logged workouts" (W1-W11, PAR:63-71; VG:29; UXA:43).
- **R5** `OBSERVED` Add: template / workout -> plan (P7, W5, PAR:97); from Workout Detail it is a 2-step sheet new plan / existing plan (F8, d/add_to_plan_sheet, PAR:69). `UNKNOWN`: does a template ask for a start date; resulting plan name; the sheet's exact wording.
- **R6** `INFERRED` After adding, Training Plans tab > **In Progress** shows the plan (tabs In Progress / Upcoming / Completed, P2-P5, PAR:92). Reason: plan card "Week n of N" with progress exists (P3, PAR:93), but the doc does not trace the add-then-view sequence.
- **R7** `OBSERVED` Plan week view: week stepper with phase chip and dates (P9, PAR:98), rows with done counters "0/1" and week progress (P3, P9-P10, PAR:99), flexible rescheduling = move day (RM §4, PAR:101). `INFERRED` that a template week contains actionable workouts on days (template shows a week schedule, P7) — whether the current week is auto-aligned to today is UNKNOWN.
- **R8** `INFERRED` Start from the plan: tapping a plan row opens Workout Detail whose Start button begins the session (Start exists on detail, W3/W9). Whether a plan row itself carries a Start button: UNKNOWN.
- **R9** `OBSERVED` Pre-start player state "UP NEXT" (exec_prestart, UXA:46; VG:34), then full-screen player: big timer (~112 px), state label, "1/3 SET" counter, set card, transport (X1-X5, PAR:111-113; VG:34). Phases get ready -> work -> rest -> done (X3, X8). Crimpd auto-advances between blocks (UXA:47).
- **R10** `OBSERVED` Logging during session: per-set entry, "How hard was this set?" with words (X5, X12, PAR:114-115); logging panel shown/hidden by a manual toggle (X5-X6; the auto expand-on-rest rule is `UNKNOWN`/ours, PAR:117). Pause/resume (X7), skip rest (X7-X8), Add Set beyond prescribed (X10) (PAR:119-121).
- **R11** `OBSERVED` DONE -> log review sheet: workout effort + additional notes + set table + Save (X9-X11, X10; UXA:49; PAR:116, 123). `UNKNOWN`: what happens if the sheet is dismissed without Save (is the session lost?).
- **R12** `OBSERVED` Logbook tab: month bar + expandable calendar with dots (J1-J2), week/day grouping with infinite scroll (J3), log cards with intensity/completion/TUT/duration/workload (J4) (PAR:133-135). `INFERRED` the new session appears there (the review step is named "Log"; PAR:141 "Log Workout"). Persists after restart: `UNKNOWN`.
- **R13** `OBSERVED` Analytics: metric dropdown (Workouts/Duration/TUT/Workload), 1 Mo/3 Mo/Custom, weekly chart, sunburst by type, multi-month summary, (i) definitions, CSV export (A1-A7, PAR:150-159; VG:32; CAP:17 "Logged by Type/Week"). `OBSERVED` (secondhand, evidence cell A8) it recomputes on log add/delete (PAR:160).

**FINAL RESULT:** a finished session visible in Logbook (card + detail sheet) and counted in Analytics; plan row counter presumably "1/1" (INFERRED).
**STATE CHANGES:** + plan (In Progress) containing the template; + log entry (sets, effort, notes); Analytics counts +1 workout, + duration; Home still catalogue-first.

## R-J2 — Custom workout from nothing -> first exercise -> protocol -> save -> start -> complete -> add to plan/day -> start from plan

**START STATE:** no personal workouts.

- **R1** `OBSERVED` Entry points: Home banner "Create Custom Workouts" (H6) or "+" sheet "create" (H12; d/plus_sheet; F2) (PAR:50, 56).
- **R2** `OBSERVED` Creation is a **wizard, 6 steps with pager n/6**, back arrow and close X (C1-C2; UXA:32); steps include type -> category -> sub-focus (C2, C7-C8; PAR:84). The exact 6 steps and their order: `UNKNOWN`. (PS:258's order "name -> add exercise -> ... -> category" is our spec, not observed; it conflicts in order with C2/C7-C8.)
- **R3** `OBSERVED` Workout editor/detail list: exercise name + "3 sets - 15 reps - 00:07 per rep / Rest 01:00 per set", "..." menu per row, "+ Add Exercise" (C9-C12; UXA:33; PAR:81).
- **R4** `OBSERVED` Add exercise screen: search + alphabetical list; on no match a row **"Create Exercise: Xxx"** (C3-C4; UXA:34; PAR:80). Answer to "no match": yes you can create from the search text. `UNKNOWN`: form shown after tapping it; whether the created exercise appears in later searches; whether the library is empty on a clean install (list exists, size unknown).
- **R5** `OBSERVED` Protocol config: label left + -/N/+ stepper right (blue outlined circles, 44 px, disabled at min), mm:ss rows for rest/durations, live "clock 02:00" total in header, rep timer (rep duration/rest), notes, one bold full-width primary at bottom, cancel = X in header (C5-C6; UXA:36, 40-41; PAR:82-83, 85). Crimpd has **no explicit protocol picker** (one type per wizard) — UXA:37 ("Crimpd has one type per wizard; no protocol concept").
- **R6** `OBSERVED` Save -> workout appears in Home "My Workouts" grid: compact tiles title + 1-line description + duration (H7; UXA:31) and has a detail page (d/custom_workout_detail, PAR:63). That Save lands on the detail page: `INFERRED` (detail exists; landing not recorded).
- **R7** `OBSERVED` Start directly from Workout Detail (Start, W3/W9, PAR:66) -> live player as in R-J1 R9-R11 -> Logbook/Analytics.
- **R8** `OBSERVED` Add to plan: round action "Add to Plan" -> 2-step sheet new / existing plan (W5; F8; PAR:69). `UNKNOWN`: day picker or week picker step, and whether it can target a specific day; our "pick a day" is a domain adaptation (PAR:69).
- **R9** `INFERRED` Start from the plan: via plan row -> detail -> Start (as R-J1 R8). Not recorded.
- **R10** `OBSERVED` Edit/delete workout (C11, PAR:72, 79; "Duplicate workout" is NOT in the Crimpd builder, PAR:86).

**FINAL RESULT:** a personal workout in My Workouts, runnable standalone and from a plan, logged like any workout.
**STATE CHANGES:** + workout, (+ exercise if created), + plan entry; + log on completion.
**Gaps:** custom workout with zero exercises (Save allowed? message?) `UNKNOWN`; limit of exercises, `UNKNOWN`.

## R-J3 — Start a workout without a plan (free workout)

- **R1** `OBSERVED` From Home: open any workout (catalogue or My Workouts) -> Workout Detail -> **Start** (W3/W9, X1) (PAR:66, UXA:43). No plan prerequisite recorded.
- **R2** `OBSERVED` Home "+" sheet offers (session / log / create / cancel) (H12, PAR:56) — a "session" start without a plan; "Start Open Climbing Session" banner (H10, PAR:54, climbing-specific).
- **R3** `OBSERVED` Player and review identical to R-J1 R9-R11; Log Workout is an alternative: log a past/untracked workout without running the timer (W3, W6, PAR:67, 141).
- **R4** `INFERRED` Result goes to Logbook/Analytics like a planned workout (Logbook shows workout logs; nothing ties display to plan membership). `UNKNOWN`: whether Logbook cards distinguish plan vs free.
- **R5** `UNKNOWN` Whether starting a workout that is in the plan but from Home (not from plan row) ticks the plan counter.

**FINAL RESULT:** completed log without plan. **STATE CHANGES:** + log; no plan change (INFERRED).

## R-J4 — Plan lifecycle

- **R1** `UNKNOWN` Empty Training Plans tab text/CTA for a user with no plan. `INFERRED` that the tab still shows entry points: Skill Templates grid (P6), create-blank-plan (P8 name, duration, start, goal), and a Crimpd+ upsell (P1) (PAR:92-95, 105) — their presence for an empty user is not recorded.
- **R2** `OBSERVED` Tabs In Progress / Upcoming / Completed (P2-P5; N1; PAR:92). Create blank plan with name, duration, start date, goal (P8, PAR:94). Skill Templates grid (P6) -> template detail (P7).
- **R3** `OBSERVED` Plan card "Week n of N" + progress (P3); week stepper with phase chip and dates (P9) = prev/next week and current-week indication (PAR:93, 98). `UNKNOWN`: exact visual marking of the "current" week; whether you can step to weeks beyond plan length.
- **R4** `OBSERVED` Row done counters "0/1", week progress (P3, P9-P10); completed/skipped state (P10) (PAR:99, 102). Flexible rescheduling (move a workout to another day) exists (RM §4, PAR:101); mechanism (drag, sheet) `UNKNOWN`.
- **R5** `OBSERVED` Plan menu labels: edit plan, change start date, delete plan, "Clone plan incl. schedule" (P11 — **labels only**, PAR:103-104); "Schedule" label on week view (P9, unobserved beyond label, PAR:100). So a per-week "copy week" function is **not** observed in Crimpd; the closest observed item is "Clone plan".
- **R6** `UNKNOWN` Effect of deleting/removing a plan on workout templates and logged history. `INFERRED` (weak): Logbook is a separate store (J1-J8) and Workout Detail keeps "Logged workouts" (W11), so history likely survives; not observed. "Archive, not delete" in our docs is our policy, not Crimpd's.
- **R7** `UNKNOWN` A plan week with zero workouts: message, CTA, whether the week is skippable, whether it counts toward "Week n of N".
- **R8** `UNKNOWN` Newly created week (blank plan / extended): empty message and CTA ("Schedule" label only).
- **R9** `OBSERVED` Crimpd+ upsell on plans (P1, PAR:105); gating details (which actions) `UNKNOWN`.

**FINAL RESULT:** plans list, weeks, per-row counters; lifecycle controls exist as labels.
**STATE CHANGES:** + plan, + week schedule; delete semantics UNKNOWN.

## R-J5 — Logbook

- **R1** `OBSERVED` Locate: bottom tab "Logbook" (SKL:24; CAP:17 calls it "Training History"). Month bar + expandable calendar with dots (J1-J2; d/logbook_month_picker; F5), week/day grouping, infinite scroll (J3) (PAR:133-134).
- **R2** `OBSERVED` Open: tap a card -> bottom sheet/detail with session + exercise details (J5; d/logbook_ref_sheet), with actions View / Edit / Clone / Delete (VG:31; PAR:136-140), "View Workout" jumps to the workout (J5, PAR:137).
- **R3** `OBSERVED` Edit Log, Clone Log exist as actions (J5, J7); **the forms were not observed** (PAR:138-139 "form unobserved"). Fields editable/cloned date default: `UNKNOWN`.
- **R4** `OBSERVED` Delete with confirmation (J6; LED) (PAR:140).
- **R5** `OBSERVED` Backdate: "Log Workout" (W3, W6) from Workout Detail and a Log Cross-Training entry (H8, J8) (PAR:52, 67, 141, 143); form fields beyond "effort + notes" `UNKNOWN`. PS:229 lists date/type/effort/duration/notes for cross-training = our spec.
- **R6** `OBSERVED` Analytics recompute on log add/delete (A8, PAR:160). `UNKNOWN`: whether cross-training logs count in the Workouts metric / sunburst.

## R-J7/J8 — Persistence, resume, back navigation in a live session

- **R1** `OBSERVED` Player is full-screen with its own transport (X1-X8). No documented Android Back behaviour.
- **R2** `UNKNOWN` Back during a live session (confirm dialog? pause? lose data?). Only builder Back is documented: "Back preserves wizard state" (UXA:42).
- **R3** `UNKNOWN` Resume after app kill / device lock. N5 background reconciliation is explicitly `(unobserved)` (PAR:124, 199). Settings on notification permission/push for timer (N1-N2) and iOS Live Activities (N3) exist (PAR:200-201) — they indicate a native background timer, `INFERRED` that Crimpd keeps the timer alive in background as a native app (ARCH:275 asserts "Crimpd is a native app and can hold the timer" — owner statement, not black-box).
- **R4** `UNKNOWN` Whether sets logged before an abnormal exit are retained.
- **R5** `OBSERVED` Within the session: previous-set editing is not documented for Crimpd; per-set effort and the manual log-panel toggle are (X5-X6, X12).

## Empty states E1-E12

Tag column is the evidence level for the whole row. Messages are `UNKNOWN` verbatim unless quoted.

| # | State | Screen | Message | CTA | Resolves? | Tag | Source / note |
|---|---|---|---|---|---|---|---|
| E1 | No active plan | Training Plans > In Progress | UNKNOWN | INFERRED: Skill Templates grid, create blank plan | INFERRED yes (templates/blank plan create a plan) | `UNKNOWN` | PAR:92-95; presence for empty user not recorded |
| E2 | Active plan, nothing this week | Plans week view | UNKNOWN | UNKNOWN | UNKNOWN | `UNKNOWN` | week stepper P9 only |
| E3 | No personal workouts | Home My Workouts | UNKNOWN (grid empty/hidden?) | OBSERVED: banner "Create Custom Workouts" (H6), "+" sheet create | INFERRED yes | `INFERRED` | PAR:50-51, 56 |
| E4 | Empty library / no matching exercise | Add-exercise search | UNKNOWN text | OBSERVED: row "Create Exercise: <query>" | UNKNOWN (form unobserved) | `OBSERVED` | UXA:34; PAR:80 |
| E5 | No Logbook history | Logbook | UNKNOWN | UNKNOWN | UNKNOWN | `UNKNOWN` | calendar/list only documented populated |
| E6 | No Analytics data | Analytics | UNKNOWN | UNKNOWN | UNKNOWN | `UNKNOWN` | PAR:150-160 populated only |
| E7 | No assessment results | Profile > assessments / Home tests | UNKNOWN ("last result" shown when present, R4-R5) | UNKNOWN | UNKNOWN | `UNKNOWN` | PAR:170 |
| E8 | No favourites | Home Favorite Workouts row (H9) | UNKNOWN (row hidden or empty) | UNKNOWN | UNKNOWN | `UNKNOWN` | PAR:53 |
| E9 | Expired subscription | Plans upsell "Crimpd+" (P1); account settings (R10, R17) | UNKNOWN | OBSERVED: upsell exists; INFERRED: Crimpd+ is a paid tier (public knowledge, freemium) | UNKNOWN | `INFERRED` | PAR:105, 177; which content locks is UNKNOWN |
| E10 | Newly created week | Plans week view | UNKNOWN | "Schedule" label (P9) | UNKNOWN | `UNKNOWN` | PAR:100 |
| E11 | Program/template yields no workouts | Template detail / plan | UNKNOWN | UNKNOWN | UNKNOWN | `UNKNOWN` | not documented |
| E12 | Custom workout with zero exercises | Workout editor | UNKNOWN | OBSERVED: "+ Add Exercise" is the list's tail control | INFERRED yes | `INFERRED` | UXA:33; whether Save is allowed UNKNOWN |

## Summary notes for the Judge

- Crimpd's observed model is **catalogue-first, plan-optional**: Home catalogue + Workout Detail with Start means no plan is needed to train; plans are a scheduling layer.
- The builder offers search-and-create exercise inline and has no protocol-type picker; our four-protocol picker is a domain difference (UXA:37).
- Crimpd's "Home" has no week widget (PAR:57); Plans tab owns the week.
- No empty-state text of Crimpd survives in the repo. Any comparison for E1-E12 against Crimpd is a comparison against the principle (SKL rule 4, PS "no dead ends"), not against recorded Crimpd behaviour.
