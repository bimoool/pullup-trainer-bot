# A-reference — coverage of Crimpd golden traces

Counts are by the **leading tag of each step** in `GOLDEN_TRACES.md` (most OBSERVED steps also carry an embedded `UNKNOWN` sub-detail, listed in the right column). Evidence is secondhand only (no Crimpd lab, no dumps/screenshots in the repo).

| Intent | OBSERVED | INFERRED | UNKNOWN | Main embedded unknowns |
|---|---|---|---|---|
| R-J1 fresh user -> plan -> workout -> log -> Logbook -> Analytics | 10 | 2 | 1 | first-run/onboarding; template add dialog (start date); how plan row starts a workout; plan counter update; review sheet dismissed without Save |
| R-J2 custom workout -> exercise -> save -> start -> plan | 9 | 1 | 0 | wizard's 6 steps; Create-Exercise form; zero-exercise Save; day picker in Add to Plan |
| R-J3 free workout without plan | 3 | 1 | 1 | Logbook distinction plan vs free; plan counter when started from Home |
| R-J4 plan lifecycle | 5 | 0 | 4 | empty Plans tab; removal semantics; zero-workout week; new week; copy week (not observed in Crimpd) |
| R-J5 Logbook | 6 | 0 | 0 | Edit/Clone forms (explicitly unobserved); backdate form fields; analytics treatment of cross-training |
| R-J7/J8 persistence, resume, back | 2 | 0 | 3 | Back during live session; resume after kill; set retention |
| E1-E12 empty states (12 rows) | 1 (E4) | 3 (E3, E9, E12) | 8 | every verbatim message |

Verdict: structure of screens/actions is well documented; behaviour in edge/empty/error states is almost entirely undocumented.

## Observations to make in the real Crimpd lab (priority for J1-J4)

Record each with screenshot + uiautomator dump (`snap.sh <pair-id>`), test-data prefix `REF TEST -`.

### J1 (discover -> plan -> start)
1. Fresh install / new account: every screen from launch to Home (onboarding questions, default plan or content, paywall at launch). Is anything pre-added?
2. Training Plans tab on a brand-new account: verbatim empty text, all CTAs, whether Crimpd+ upsell shows (E1).
3. Skill Templates grid -> template detail -> add: every dialog (start date? plan name? level choice?), then the resulting In Progress card ("Week n of N") and which week is current.
4. Plan week view after add: are there workout rows with a Start button, or only rows opening Workout Detail? Does tapping Start from a plan row tick "0/1" -> "1/1" after completion?
5. Review sheet at DONE: dismiss without Save — is the session logged?
6. Logbook and Analytics immediately after one completed session (card fields, metric values, sunburst).

### J2 (custom workout/exercise)
7. Create Custom Workouts wizard: screenshot all 6 steps in order; can it be saved with zero exercises (E12) and what shows.
8. Add-exercise screen on a clean account: size/content of list (system library?), sort, filters; search a nonsense string and record the exact "Create Exercise: ..." row text.
9. Tap "Create Exercise": the full form (fields, type/metric choice), Save, and whether the new exercise then appears in an unfiltered list and in later searches.
10. After workout save: landing screen (detail vs My Workouts); Start from there; Add to Plan sheet step 2 (does it ask day/week?), then Start from plan.

### J3 (free workout)
11. Start a catalogue workout never added to a plan: confirm no plan prompt; check the Logbook card and whether any plan counters change when the same workout is in a plan.

### J4 (plan lifecycle)
12. Create blank plan: fields, validation, resulting empty week (E10, E11) — message and CTA for a week/plan with zero workouts.
13. Week stepper: marking of current week, behaviour at first/last week, "Schedule" action meaning, moving a workout to another day (mechanism).
14. Plan menu: "Clone plan", edit, change start date, delete — confirmation text; after deletion check Workout Detail "Logged workouts", Logbook entries, My Workouts (history/templates preserved?).
15. Upcoming vs In Progress: can several plans coexist, and how many can be active (resolves the PAR:92 vs PAR:94 ambiguity).
16. Expired/free-tier state: which actions hit the Crimpd+ paywall and its wording (E9).

### Lower priority (J7/J8, other empty states)
17. Press Back / switch app / kill app during a live session; reopen — record the result and any resume prompt.
18. Empty Logbook (E5), Analytics (E6), assessments (E7), favourites (E8) on a clean account.
