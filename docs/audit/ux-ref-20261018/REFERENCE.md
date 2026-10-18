# Reference (real Crimpd 8.5.3) — observed journeys

Local session, 2026-10-18, Sonnet 5.5. **Every OBSERVED line below was seen on the real app**
(Crimpd `com.crimpd.ui` 8.5.3 / 8050300, Play-installed, on AVD `ref_pixel6_play`, driven with adb +
uiautomator; scripts `reference/a.sh`, `reference/texts.sh`). Evidence: `reference/screens/*.png`
(downscaled), `reference/dumps/*.txt` (full visible-DOM text per step), `reference/notes-raw.md`
(chronological step log, ids `P1-nn` = pass 1, `P2-nn` = pass 2). Nothing here comes from the Crimpd
website or from earlier notes.

Tags: **OBSERVED** (seen now) · **INFERRED** (deduced from observed behaviour) · **UNKNOWN** (not seen).

## Method and data safety

- Account on the emulator is signed in and holds pre-existing data (a plan in progress, 22 own workouts,
  166 log entries). Rule kept: additive only, every object prefixed `REF TEST`, ledger in
  `reference/test-data-ledger.md`, own objects deleted afterwards; existing items opened read-only
  (Cancel/Back only, never Save). Final check: Plans → In Progress unchanged («Week 4 of 6 · 0/7»), Upcoming
  empty, Logbook has no leftover entries.
- Created and deleted: plan «REF TEST Plan», two logs of «1 On 1 Off» (dated 2 Nov and 18 Oct).
- Screens with the owner's own log/plan names appear in `p1_57`, `p1_72`, `p2_07`; they are in a private repo.
- Calendar date in the emulator: Sun 18 Oct 2026.

## The reference plan model (summary)

1. A **plan** = name + duration (weeks) + start week + optional goal. One active plan at a time.
2. Plan **weeks** carry a phase label (Base / Build / Rest / Peak) and a start date.
3. Workouts are added to a plan **with 0 sessions/week**; the user then sets a **weekly quantity per workout
   per week** with a `−/+` stepper (**step 0.5**).
4. Days are chosen **afterwards, per week**, in a «Week N Schedule» modal: every workout has a «+ N» pill
   (sessions still to place) and seven day circles; each tap places one session on that day.
5. Progress is **derived from the Logbook by date + workout**; there is no «complete this occurrence» action.

## Journeys

### R-1 Create a plan
| # | Action | Result (OBSERVED) | Evidence |
|---|---|---|---|
| 1 | Training Plans tab → «+» (top right) | opens «Create Training Plan» directly (no intermediate sheet) | p1_01, p1_02 |
| 2 | Form fields | Plan Name (default «November 2026»), Plan Duration (native wheel, default 6 weeks), Starting Week, Training Goal (optional, 0/512) | p1_02 |
| 3 | Starting Week | default = first free week after the active plan (Nov 2); static note «Only one training plan may be active concurrently.» | p1_02 |
| 4 | Starting Week picker | calendar; **every day covered by the active plan (and the past) is greyed out**, no per-date explanation | p1_41 |
| 5 | Save with empty goal | allowed; lands in the plan editor; weeks auto-labelled Base, Base, Rest, Base (4 weeks); totals row 0 / 0.00 Hours; buttons «Add Workouts», «Add Skill Templates» | p1_10 |

### R-2 Add workouts
| # | Action | Result | Evidence |
|---|---|---|---|
| 1 | «Add Workouts» | sheet with tabs Workouts / Skill Templates, search, filters Category / Equipment / My Workouts; rows show name, expand chevron, equipment icons, minutes | p1_11, p1_12 |
| 2 | Tap row | expands (description); blue «+» adds; after adding the control becomes a red «−» (toggle). The same workout cannot be added twice here; the sheet stays open for multi-add | p1_12, p1_13 |
| 3 | Close sheet | each added workout is a row with a colour bar by category, a pencil, and a per-week cell: **all 0** («0.00 Hours» totals) — nothing is scheduled yet; FAB «+» for more | p1_14 |
| 4 | Workout Detail → «Add to Plan» | 2-step sheet «Add To New Plan» / «Add To Existing Plan», existing-plan step lists plans with «Add To Training Plan». Not confirmed (would change the owner's plan) — result screen UNKNOWN | P2-10 |

### R-3 Distribute across weeks
| # | Action | Result | Evidence |
|---|---|---|---|
| 1 | Tap a workout's per-week cell / pencil | «Weekly Volume» sheet: workout card, text «Adjust the total number of sessions to complete each week.», table Week / Date / Phase / Quantity with `−  value  +` per week, red «Remove From Plan» | p1_15 |
| 2 | Tap `+` | **step 0.5** (3 taps → 1.5); a «Rest» week accepts a quantity too (no block); Save | p1_17, p1_18 |
| 3 | Plan overview | per-week totals «TOTAL SESSIONS SCHEDULED PER WEEK» 1.5 / 0.5 / 0.5 / 0 with hours (1.5 × 20 min = 0.50 h; 0.5 × 20 min displays 0.25 h — rounding rule INFERRED: up to 0.25 h) | p1_18 |
| 4 | Week chip → sheet | Delete Week / Edit Week Phase / Insert Week Before / Insert Week After / Cancel; «Edit Weeks» = per-week Base/Build/Rest/Peak segmented control | p1_19, p1_20 |
| 5 | Insert Week After | new empty week (Base 5), plan end date +1 week; week strip shows 4 weeks per page and scrolls horizontally | p1_21, p1_22 |
| 6 | Delete Week | **immediate, no confirmation**, also for a week that holds volume: the volume disappears with it, later weeks shift earlier, plan shortened (end Nov 16) | p1_23, p1_24 |

### R-4 Place on days, repeat in one day, move, delete
| # | Action | Result | Evidence |
|---|---|---|---|
| 1 | Plan detail → Week tab → «Schedule» | modal «Week N Schedule»: «For each workout, select a day of the week to schedule a session.» + tips link; header MO..SU; row «Total sessions scheduled per day»; per workout «+ N» pill and 7 day circles | p1_27 |
| 2 | Tap a day circle | that day gets the workout (per-day total updates); pill counts down | p1_31 |
| 3 | **Repeat in the same day** | with quantity 2: tap 1 → day total 1, tap 2 → day total 2, pill disappears; **the next tap on the same day resets it to 0** (cycle 0→1→2→0). With remainder 0.5 a tap places 0.5 | p1_43, p1_44 |
| 4 | Quota spent, tap another day | silently ignored (no message) | p1_34 |
| 5 | **Move** a session | deselect the day and select another (week-scoped; there is no cross-week move) | p1_32–p1_34 |
| 6 | Save | Week tab lists day sections «MONDAY 20m», «WEDNESDAY 20m» (day total minutes) with a card per session, badge «0/1»; view toggles card stack / list | p1_46, p1_52 |
| 7 | Unscheduled workouts of a week | listed under heading «THIS WEEK» (also for a future week) | p2_07 |
| 8 | **Delete** a session | deselect the day; a whole workout: «Remove From Plan» in the Weekly Volume sheet — immediate, no confirm; its sessions vanish, week shows «No workouts planned for this week. Enjoy the rest!» | p1_77, p1_78 |
| 9 | Plan menu «⋯» | Edit Training Plan (= volume editor) / Change Plan Start Date (= the create form) / Clone Training Plan / Delete Training Plan | p1_38, p1_39 |
| 10 | Delete Training Plan | action sheet «Are you sure you want to delete this training plan?» [Delete Training Plan] [Cancel]; Upcoming then shows «You do not have any upcoming training plans…» + «Create Training Plan» | p1_79, p1_80 |
| 11 | Week header | pencil → «Week N Notes» (free text); week stepper arrows; current week has a yellow dot; ring per category (done/planned) | p2_06, p2_07 |

### R-5 Execute
| # | Action | Result | Evidence |
|---|---|---|---|
| 1 | Plan card → Workout Detail | Start Workout / Log Workout / Favorite / Add to Plan; **no occurrence-specific screen**, works for future-dated slots too | p1_47 |
| 2 | Start Workout | full-screen player: collapse chevron, quick-log clipboard icon, exercise name + (i), big countdown, «UP NEXT / REST / DONE», SET x/y and REP x/y, transport |< SET, << REP, Play, >> REP, >| SET | p1_63 |
| 3 | Ten reps skipped (~2 min wall clock) | player stays on «DONE 10/10»; nothing is saved automatically | p1_67, p1_69 |
| 4 | Clipboard icon | opens a prefilled «Log Workout» (date today); Save → back to the player; user collapses it with the chevron | p1_69–p1_71 |
| 5 | First Play | native notification-permission dialog | P2-03 |
| 6 | **Process killed mid-set**, relaunch | Home; no resume offer; no partial log (Logbook «18 Sun» empty) | p2_03 |

### R-6 History
| # | Action | Result | Evidence |
|---|---|---|---|
| 1 | Logbook | «Training History», month header `‹ October 2026 ⌄ ›` (right arrow disabled for future months), calendar icon, flat list grouped by day, today row highlighted | p1_53 |
| 2 | Card | category icon + name, Intensity (Easy/Hard/Very Hard), Completion %, Grade (climbing), Time Under Tension, **Est. Duration**, Workload (number or «-»); no per-set detail on the card | p1_72 |
| 3 | Durations of the saved test log | TUT 10m, Est. Duration 20m — equal to the **prescribed** values; the real session took ~2 min. **The reference never shows a measured duration** | p1_72 |
| 4 | Tap card | bottom sheet: title, date, time («12:00 AM» for a manual log, real time for a session log), View Workout / Edit Log / Clone Log, Session Details, Exercise Details per set, red «Delete Log» | p1_58 |
| 5 | Edit Log | date, Completion Percent (25/50/75/100), Effort, per-set edit, Add Set, notes, Delete Log | p1_59 |
| 6 | Delete Log | action sheet «Are you sure you want to delete this workout log?» [Delete Workout Log] [Cancel]; **the plan week reverts at once** (ring 1/2 → 0/2, card 1/1 → 0/1) — progress is derived from logs | p1_60–p1_62 |
| 7 | Log dated in the plan's week | credited by date + workout: that day's card turns green «1/1 ✓», category ring 1/2, other day stays 0/1 | p1_51, p1_52 |
| 8 | Log with a **future** date | accepted (calendar enabled); shown inside the *current* month list after the today row as «2 Mon» with no month label — November cannot be reached with the arrows | p1_49, p1_57 |
| 9 | Analytics | metric dropdown {Workouts Logged, Duration (min), Time Under Tension (min), Estimated Workload}; periods 1 Mo. / 3 Mo. / Custom; donut by type + weekly bars | p1_81, p1_82 |

## Reference behaviours that must NOT be copied (documented reasons)

| Behaviour | Why we differ |
|---|---|
| Durations are estimates of the prescription | Spec: duration = active engine time, 0 s = «без длительности»; «не выдумываем длительность» (`PROJECT_SPEC` §Live) |
| Future-dated logs accepted, mis-placed in the current month | Spec: date in the future → 422 |
| Delete Week / Remove From Plan / un-schedule without confirmation | Data-loss safety; ours already confirms «Убрать из плана?» |
| Silent ignore of taps when the quota is spent | Accessibility; show «все занятия размещены» |
| Killed player: no resume | Ours resumes a live session after reload (cloud pass 2 PASS) — keep |
| Logs credit plans by date alone | Our rule: direct start/free log does not credit a course occurrence (J7); custom-plan crediting is a design question (UX-26) |

## UNKNOWN (not observed)

- Result screen after «Add To Training Plan» (not confirmed to protect the owner's plan).
- What happens when logging a plan day that is already past in the current week; whether past days are blocked in Week Schedule.
- Skill Templates flow (tab present, not opened beyond the list entry); Crimpd+ gating of plan creation (the banner «Use Crimpd+ to build your own personalized training plans» was shown but creation worked on this account).
- Exact rounding of «Hours»; behaviour of fractional quantities across weeks.
- Reference onboarding / first-run (account already onboarded; a fresh install needs a new Play account).
