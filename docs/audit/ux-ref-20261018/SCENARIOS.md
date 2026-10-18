# Scenario map — reference journeys ↔ our journeys (2026-10-18)

Reference side: **not observed in this audit** (no access, see `INVENTORY.md`). The reference column
quotes only HISTORICAL notes (`docs/audit/wave1/A-reference/GOLDEN_TRACES.md`, `.claude/skills/crimpd-reference`)
as hypotheses to verify. Our side: OBSERVED on local `main@e2ed40e` (clean stand 8002 unless noted).

| ID | Scenario (preconditions) | Reference (Crimpd) — status | Ours — pass 1 | Ours — pass 2 | Backlog |
|---|---|---|---|---|---|
| S-J1 | Fresh user → onboarding → course → plan → first live → Journal → Analytics → reload | HISTORICAL R-J1 (10 OBSERVED-secondhand steps, onboarding/first-run UNKNOWN) | Completed end-to-end, with friction and inconsistencies | Rechecked on new user 8800201: same | UX-01, 03, 04, 05, 06, 07, 08, 09 |
| S-J5 | Automatic prep/rest/interval transitions, no taps | HISTORICAL: logging during rest (rule 3) | PASS (interval workout auto-advances, round reps logged during rest) | — | — |
| S-J6 | Custom workout → weekly volume plan (2,2,0,2) → start | HISTORICAL R-J2 (6-step wizard, Add-to-Plan day picker) | Builder works (2-step); plan volume as free text; W3 empty shown | E12 rechecked: editor disables «Добавить в план» for an empty workout | UX-10, 11, 12, 19 |
| S-J7 | Direct start of a ready workout that is not the plan occurrence | HISTORICAL R-J3 | PASS: plan counter unchanged, Journal «Свободная» | — | — |
| S-J8 | Post-factum record of an existing workout | HISTORICAL R-J5 (backdate form UNKNOWN) | «Тренировку из моих» lists only own workouts | Rechecked: user with none sees a form with «Сохранить» and nothing to pick | UX-23 |
| S-J9 | External activity | HISTORICAL R-J5 (cross-training) | PASS: Journal «Бег · 0:45», Analytics +1 / +45 min, category «Другая активность» | — | — |
| S-J10 | Edit session (date, set) → Journal + Analytics converge | HISTORICAL: Edit form UNKNOWN | Date move PASS | Set value edit PASS (40→42, Analytics 93→95) | — |
| S-J11 | Min rest between main course sessions | — (ours only) | **FAIL**: row «Не успеть на этой неделе» + «Начать» → dead-end screen «доступна с 21 окт» | Reproduced on new user | UX-01 |
| S-J12 | Future weeks visible / startable | HISTORICAL R-J4 (week stepper) | **FAIL**: weeks 3–5 show stale «Доступно с 21 окт», course rows have no start | — | UX-02 |
| S-E | Empty states (fresh user, every tab) | HISTORICAL E1–E12 mostly UNKNOWN | Present on every tab; no impossible action offered except UX-01/UX-23 | — | UX-23 |
| S-L | Live robustness: reload mid-set, early finish | HISTORICAL R-J7/J8 UNKNOWN | — | Reload resumes rest timer; early finish dialog explicit (save / back / cancel) | UX-03 |
| S-H | History: legacy (pre-v2) course record in Journal | — | Seeded 900018: different card format, «Удалить» | Delete uses native `window.confirm` and offers destructive recalculation, unlike v2 course cards («нельзя удалить») | UX-15 |
| S-N | Narrow 320 px, light/dark | HISTORICAL none | No horizontal overflow; one 42 px target | In-app «Тёмная» override readable; Telegram-dark with empty themeParams unreadable | UX-18 |
| S-S | Home search / «Все ›» / Tests | HISTORICAL Home search «что потренируем сегодня» | Works; ready workouts headed «Мои тренировки»; Tests ignore onboarding max | — | UX-05, UX-16 |

## Reference journeys still to observe (blocked)

The wave-1 list in `docs/audit/wave1/A-reference/COVERAGE.md` § «Observations to make in the real Crimpd lab»
(items 1–13) remains the exact capture plan; add for this audit: plan row states when a workout cannot be done
this week, future-week start, duration shown in Logbook/Analytics, how total reps are counted, timed-exercise
Logbook cards, deletion of logged plan workouts.


## Local pass — reference column now OBSERVED

See `REFERENCE.md` (R-1…R-6) and `COMPARISON.md`. Scenario ids from the cloud pass map as: S-J6 → R-1…R-4,
S-J10/S-J8 → R-6, S-J12 → R-4/«future weeks», S-L → R-5 (kill mid-set), S-E → empty states in `PASS2-LOCAL.md`.
New scenarios added by the local pass: **S-R1 same workout twice in one day**, **S-R2 move a session**,
**S-R3 delete a session / week / plan**, **S-R4 plan credit after logging and after deleting a log**,
**S-R5 reopen after leaving the editor**. Our-side runs: `artifacts-local/l1…l7`.
