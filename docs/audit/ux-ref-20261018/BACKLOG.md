# Evidence backlog — UX reference audit 2026-10-18 (cloud pass + local reference pass)

One list, stable IDs (UX-01…UX-23 unchanged from the cloud pass; UX-24… added by the local pass). Evidence = files in
`artifacts/` (ours, cloud), `artifacts-local/` (ours, local pass), `reference/` (real Crimpd 8.5.3).
Scripts in `harness/`, `harness-local/` reproduce our-side artifacts; reference steps are in `reference/notes-raw.md`.
Item bodies below are the cloud-pass text; the **local pass adds a «Ref» status for every item** in the table
right after this header and the new items at the end.
Status: **CONFIRMED** (reproduced independently) · **OBSERVED** (seen once) · **WITHDRAWN** ·
**DECIDED** (answered by an existing requirement — see `DECISIONS.md`; no owner action) · **PROPOSAL** (default stated in `DECISIONS.md`, work proceeds on the default unless vetoed: Q1, Q2, Q3). No item blocks on a repeated owner decision.

Priority: P1 = blocks or misleads a core journey · P2 = wrong/inconsistent information or avoidable friction ·
P3 = polish/copy/a11y.

## Reference status of every item (local pass)

| ID | Ref | What the real Crimpd shows (evidence) | Effect on the item |
|---|---|---|---|
| UX-01 | n/a (our rule) | no min-rest rule exists; every action offered is startable (R-5) | stays P1, reference-independent |
| UX-02 | **OBSERVED** supports | future weeks open and schedulable; future-dated slots start/log from detail (`p2_09`, `p1_47`) | stays P1 |
| UX-03 | **OBSERVED** | no 0:00; but durations are **estimates** of the prescription (`p1_72`) — contradicts our spec | stays P1; **DECIDED**: spec = active engine time, 0 = «без длительности» |
| UX-04 | OBSERVED supports | metrics are named and separate (Workouts Logged / Duration / TUT / Estimated Workload, `p1_82`) | label the tile, as proposed |
| UX-05 | UNKNOWN (no onboarding in ref) | — | **DECIDED** by spec + default in `DECISIONS.md` (Q1) |
| UX-06 | partly | Add to Plan = 2-step plan chooser; result screen UNKNOWN (`p2_10`) | stays P2 |
| UX-07 | n/a | ref player asks only grade/effort per set | **DECIDED**: record must stay complete (V5.6 §8); UX = pickers + reuse |
| UX-08, 09 | n/a | — | unchanged |
| UX-10 | **OBSERVED** supports | Plans = one plan object with In Progress / Upcoming / Completed (`p1_01`) | stays P2 → UX-27 |
| UX-11 | **OBSERVED** | «Today» block exists on the plans list («No workouts scheduled for today»), not inside the week view | **downgrade to P3 / intended**; remove only the duplicate inside the week view |
| UX-12 | **OBSERVED** strongly supports | weekly quantity steppers (0.5 step), per-week totals + hours, per-week phase (`p1_15`, `p1_18`) | stays P2 → implemented through UX-24 |
| UX-13 | **OBSERVED** | unscheduled bucket is called «THIS WEEK» (`p2_07`) | rename «Свободный пул» |
| UX-14 | **OBSERVED** supports | every card always shows TUT and Est. Duration (`p1_72`) | stays P2 |
| UX-15 | **OBSERVED** | any log can be deleted with an action sheet, plan reverts at once (`p1_60`–`p1_62`) | **DECIDED**: ours differs by domain rule (spec §safe delete); remaining defect = `window.confirm` + card format |
| UX-16 | OBSERVED supports | search heading «FOUND 263 WORKOUTS» (neutral) | stays P3 |
| UX-17 | UNKNOWN | — | unchanged |
| UX-18 | UNKNOWN | — | unchanged (verify in Telegram client) |
| UX-19, 20, 21 | n/a | — | unchanged |
| UX-32…34 | n/a (owner's original complaints, `COMPLAINTS.md`) | reference has no equivalent of the 3 vs 2 schedule version; electives/collections are ours | see items below |
| UX-23 | **OBSERVED** supports | «Log Workout» opens from any workout's detail, catalogue included (`p1_48`) | list catalogue workouts too |

---

### UX-01 · P1 · CONFIRMED — Plan offers «Начать» that cannot succeed (min rest), wrong row state
- **Scenario:** course «Подтягивания» in plan, first main session done today (or course added on the last day of the week). Планы → current week.
- **Ref:** HISTORICAL rule 4 (`crimpd-reference`): never offer an action that is guaranteed to fail. Spec: ACCEPTANCE J11 «plan shows the next main occurrence «доступно с <date>»».
- **Actual:** second occurrence shows «Не успеть на этой неделе» **and** «Начать»; tapping it opens a screen «Нужно два полных дня отдыха … доступна с 21 окт.» with the single CTA «Перейти в обычную "Тренировку"». Before any session the row also shows «Не успеть…» + «Начать».
- **Impact:** dead end in the main journey; contradicts J11.
- **Evidence:** `p1-j1b-03-plans-with-course.png`, `p1-j11-01-plans.png`, `p1-j11-02-after-start.png`, `p1-j11.log`; pass 2 `p2-b-*` (`UX-01 plan row`, user 8800201).
- **Recommendation:** row state from the same availability rule the server enforces: «Доступно с 21 окт» (no start button) when spacing blocks; «Не успеть на этой неделе» only when no valid day remains, without a start CTA.
- **AC:** J11 E2E: after a main session, plan row shows «Доступно с <date>», no «Начать»; no screen reachable from the plan that only says «нельзя».
- **Deps:** none (rule exists server-side). **Confidence:** high.

### UX-02 · P1 · OBSERVED — Future weeks: stale «Доступно с 21 окт», course occurrences not startable
- **Scenario:** same user; Планы → «Следующая неделя» ×4.
- **Ref:** ACCEPTANCE J12 «a future-week course occurrence starts (no 422) when spacing/access allow»; HISTORICAL R-J4 week stepper.
- **Actual:** weeks 2–5 all show both occurrences «Доступно с 21 окт», including weeks starting 26 окт/2 ноя/9 ноя; no «Начать» on course rows in any future week (custom-plan rows in future weeks do have «Начать»).
- **Impact:** user cannot pre-train a future occurrence; dates are wrong for weeks after 21 окт.
- **Evidence:** `p1-j12-0{1..4}-week-*.png`, `p1-j12.log`; contrast `p1-j6g-*` (custom rows startable).
- **Recommendation:** compute per-occurrence availability per week; show start when allowed.
- **AC:** J12 E2E on weeks +1…+4. **Deps:** UX-01 (same availability presentation). **Confidence:** high.

### UX-03 · P1 · CONFIRMED — Duration shown as 0:00 / inconsistent across Summary, Session, Analytics
- **Scenario:** complete (or finish early) a live session lasting ≥30 s.
- **Ref:** ACCEPTANCE cross-cutting «no «0:00» fake values»; HISTORICAL Logbook card shows duration.
- **Actual:** Summary «Тренировка завершена · 0:30 в работе»; Session detail «Длительность: 0:00»; Analytics «Минуты 1». Early finish after ~40 s: detail again «0:00», summary shows no duration.
- **Impact:** history shows a false value; Analytics minutes untrustworthy.
- **Evidence:** `p1-j1d.log`/`p1-j1e-02-summary.png`, `p1-j1f-00-session-detail-full.png`, `p1-an-00-analytics-full.png`; pass 2 `p2-b.log` (`UX-03 detail`).
- **Recommendation:** one duration definition — **DECIDED**: active engine time, pauses excluded, 0 s = «без длительности» (`PROJECT_SPEC` §Live) — used by Summary, Session detail, Journal card and Analytics; never render 0:00 for a session with logged sets.
- **AC:** J1/J10 E2E: the same duration in all four places; no «0:00» with ≥1 set. **Deps:** none (label decided). **Confidence:** high.

### UX-04 · P2 · CONFIRMED — Journal and Analytics disagree on reps/sets of the same session
- **Scenario:** one course session, 9 sets, 60 reps (last volume set is AMRAP).
- **Actual:** Journal card «Подходы 9 · Повторы 60»; Analytics → Подтягивания «Всего повторений 53 · Подходов 8» (+ «Максимум повторений: 1 попытка, 7»). After a second session: 93 vs 100.
- **Impact:** user sees two different totals for the same history; trust in Analytics.
- **Evidence:** `p1-j1e-05-journal.png`, `p1-j1f.log` (analytics), `p1-an-00-analytics-full.png`, `p2-c-j10.log`.
- **Recommendation:** either include max/AMRAP sets in «Всего повторений» or label the tile «Повторения в рабочих подходах» and show the split.
- **AC:** for any session, Journal totals = Analytics totals, or the difference is labelled on screen. **Deps:** none. **Confidence:** high.

### UX-05 · P2 · CONFIRMED + PROPOSAL (Q1) — Onboarding max is not a «Максимум подтягиваний» test; ГТО hint after a workout
- **Actual:** after onboarding Замер (6) Profile/Tests show «Максимум подтягиваний — Ещё не проходили»; after a completed course workout ГТО still says «Внеси первую тренировку, чтобы узнать свой разряд ГТО».
- **Evidence:** `p1-j1-06-empty-Профиль.png`, `p1-j1f.log` (`profile-after`), `p2-recheck.log`, `p1-home.log` (tests).
- **Recommendation (PROPOSAL Q1, default):** a separate labelled line «Стартовый замер: 6 (из анкеты)» on the Tests card — **not** a test result, never in the test history (spec: test results do not touch the baseline); ГТО hint text must match the condition it actually needs (pure text defect, no decision).
- **AC:** fresh user after onboarding sees the Замер value in Tests; ГТО hint changes after the first qualifying workout or names the exact missing condition. **Deps:** none. Semantics are decided by the spec (baseline ≠ test result); only the presentation is a proposal. **Status:** CONFIRMED; Q1 default applies.

### UX-06 · P2 · CONFIRMED — «Добавить в план» on Program Detail has no next step
- **Actual:** button turns into «В плане»; no link to the plan / start. Onboarding promised «→ «Добавить в план» → «Начать»».
- **Ref:** OBSERVED (local pass): «Add to Plan» = 2-step «New / Existing plan» chooser; the result screen is UNKNOWN (`reference/screens/p2_10_add_to_plan.png`).
- **Evidence:** `p1-j1b-01-after-add.png`, `p2-recheck.log` (`UX-06 after add`). Contrast custom workout: «Добавить в план» lands on Планы (`p1-j6e-01-after-add-plan.png`).
- **Recommendation:** after adding, offer «Открыть план» / «Начать» (consistent with custom-workout flow).
- **AC:** J1 from Program Detail reaches the first live set without returning to Home. **Confidence:** high.

### UX-07 · P2 · DECIDED — First course start requires 9 free-text fields
- **Actual:** pre-start asks reps with volume band + 4 text fields per band × 2 (model, colour, attachment, foot/knee). No pickers, no reuse hint on first run.
- **Evidence:** `p1-j1b-04-pre-start.png`, `p1-j1c-00-prestart-full.png`, `p1-j1c.log` (FIELDS).
- **Domain reason exists and the rule is decided** (V5.6 §8: a setup is ready only when complete — model, colour, attachment, foot/knee; no kilograms for bands). Only the control is open → design default: structured pickers, prefill from «Мои резины» / the other block when the band is the same, same completeness check.
- **AC:** a band setup cannot be saved incomplete and offers choices (not free text); on a second block/session the previous band is pre-selected. **Deps:** none.

### UX-08 · P2 · OBSERVED — Two course occurrences look identical; A/Б not distinguishable
- **Actual:** both rows «Подтягивания 0/1»; Summary says «Следующая тренировка B»; session detail shows «ОБЪЁМ A».
- **Evidence:** `p1-j1b-03-plans-with-course.png`, `p1-j1e-03-post-summary-0.png`.
- **AC:** plan rows name the session (e.g. «Подтягивания · A объём» / «· Б сила») consistently with Summary/Journal. **Deps:** UX-09.

### UX-09 · P3 · OBSERVED — Latin «B» vs Cyrillic «Б» in course copy
- «блок Б» (catalogue) vs «A и B по очереди» (Program Detail) vs «Следующая тренировка B» (Summary).
- **Evidence:** `p1-j1-07-program-detail.png`, `p1-j1e.log`. **AC:** one spelling everywhere.

### UX-10 · P2 · OBSERVED — Plans mixes «Свои планы» and course «Текущий план»; phase «База» without a course
- **Actual:** user with only a custom plan sees «СВОИ ПЛАНЫ …», then «Текущий план — Курсов в плане нет. Добавьте курс на Главной.», then «Неделя 1 · … · База». Same on seeded stepper profile.
- **Evidence:** `p1-j6g-01-after-create.png`, `p1-aged-990001-Планы.png`.
- **Recommendation:** one plan header; phase label only when a course is active; empty-course card hidden when another plan is active.
- **Deps:** none — mandate «Crimpd = functional reference» (`DECISIONS.md`): one plan header, as in the reference.

### UX-11 · P3 · OBSERVED — Same item listed twice («СЕГОДНЯ» block + day row)
- **Evidence:** `p1-j6e-01-after-add-plan.png`. **Status:** downgraded — the reference also has a «Today» block on the plans list (not inside the week view); keep it, remove only the duplicate row.

### UX-12 · P2 · OBSERVED — Custom plan: weekly volume typed as free text; past days of current week offered
- **Actual:** «Тренировок по неделям: 2 2 0 2 2 0» text field; after creating on Sunday, Mon/Thu rows of the current week show «Начать» with no «пропущено» state; W3 shows «На эту неделю пока ничего не запланировано» although 0 was chosen.
- **Ref:** OBSERVED (local pass): per-workout weekly `−/+` steppers, per-week totals and phases (`reference/screens/p1_15_tap_cell.png`, `p1_18_plan_vol.png`) — see UX-24.
- **Evidence:** `p1-j6f-*`, `p1-j6g-*`.
- **AC:** per-week steppers; past days marked; W=0 week says «Неделя отдыха по плану». **Deps:** reference observation (layout).

### UX-13 · P3 · OBSERVED — Jargon in plan week: «СВОБОДНЫЙ ПУЛ», «+ Добавить упражнение» in a course week
- **Evidence:** `p1-j1b-03-plans-with-course.png`. **Deps:** reference wording.

### UX-14 · P2 · OBSERVED — Journal cards for timed exercises show only dashes
- **Actual:** seeded «Планка» sessions: «Подходы — · Повторы — · Усилие —».
- **Evidence:** `p1-aged-990001-Журнал.png` (seeded stand 8001). **AC:** timed sets show total time / sets. **Confidence:** medium (seed data).

### UX-15 · P1 · DECIDED (presentation only) — Legacy course records: different card, destructive «Удалить» via `window.confirm`
- **Actual:** legacy (pre-v2) course record renders as text («Объём (резина): 10, 10, 10, максимум 11, следующая цель 11 …») with «Изменить / Удалить»; «Удалить» opens a native `confirm` «Это пересчитает цели всех следующих тренировок. Отменить это будет нельзя.» v2 course cards instead say «нельзя удалить, чтобы не нарушить прогрессию».
- **Impact:** inconsistent deletion policy for progression-critical history (CLAUDE.md invariant; PROJECT_SPEC §3); `window.confirm` is blocked in Telegram Web (`docs/incidents.md`, Journal not migrated yet).
- **Evidence:** `p2-legacy-00-journal-full.png`, `p2-legacy.log` (DIALOG text), `p1-aged-900018-Журнал.png`.
- **Policy is decided** (`PROJECT_SPEC` §safe delete; legacy writers stay until the Wave-4 freeze). **AC:** no `window.confirm` — in-app sheet naming the consequence; v2/legacy cards keep the rule «only provably safe deletion, reason shown»; one card format after the Wave-4 freeze. **Deps:** none for the dialog.

### UX-16 · P3 · OBSERVED — Search lists catalogue workouts under «Мои тренировки»
- **Evidence:** `p1-home.log` (`search`). **AC:** heading «Готовые тренировки» (as on Home).

### UX-17 · P3 · OBSERVED — Session detail omits band/assistance; Summary «Упражнений 2» counts blocks
- **Evidence:** `p1-j1f-00-session-detail-full.png`, `p1-j1e-03-post-summary-0.png`.

### UX-18 · P3 · OBSERVED (environment-dependent) — Telegram dark scheme without themeParams → unreadable text
- **Actual:** with `colorScheme=dark` and empty `themeParams`, titles are white on a light background. In-app «Тёмная» override renders correctly (pass 2).
- **Evidence:** `p1-n320-dark-Планы.png` vs `p2-theme-dark-override-Планы.png`.
- **Status:** real clients normally send themeParams → verify on Telegram Web/Desktop before fixing.

### UX-19 · P3 · OBSERVED — Exercise picker rows are buttons with `role="listitem"`
- Screen readers announce a list item, not a button. **Evidence:** `p1-j6c.log` (`ROW role=BUTTON role=listitem`).

### UX-20 · P3 · OBSERVED — Blocked-start CTA copy «Перейти в обычную "Тренировку"»
- Straight quotes, internal term. **Evidence:** `p1-j11-02-after-start.png`. Superseded if UX-01 removes the screen from the plan path.

### UX-21 · P3 · OBSERVED — Analytics «Показать все (+2)» with no visible hint of what is hidden
- **Evidence:** `p1-an-00-analytics-full.png`.

### UX-23 · P2 · CONFIRMED — «Тренировку из моих» for a user without own workouts: form with «Сохранить» and nothing to pick
- **Actual:** «У тебя пока нет своих тренировок — создай её на Главной.» above Date / effort / note / «Сохранить». Catalogue workouts are not offered here (they can be recorded from Workout Detail «Записать»).
- **Evidence:** `p2-b.log` (`J8 picker`). **AC:** either list catalogue workouts too, or show only the empty state with a link, no Save.

---

### Withdrawn in pass 2
- **UX-22 (was: empty custom workout can be added to plan from the editor)** — WITHDRAWN: editor disables «Добавить в план» for 0 exercises (`p2-e12.log`).
- «, выполнено» seen in the visible-text dump of Summary — screen-reader-only text, not visible (`p1-j1e-03-post-summary-0.png`).
- Missing in-page Back on Session pre-screen — Telegram native BackButton is used (`useBackButton.ts`); not visible in this harness.

### Passing journeys (no backlog item)
J5 interval auto-transitions · J7 direct start does not credit the plan · J9 external activity · J10 date and set edit converge · reload mid-live resumes · early-finish dialog · 320 px layout without overflow · empty states on all five tabs for a fresh user.

---

## New items from the local reference pass

### UX-24 · P1 · OBSERVED (ref + ours-L) — No weekly plan editor: quantity per workout per week, phases, totals, week operations
- **Reference (O):** plan form (name, duration, start week, goal); per-workout `−/+` quantity per week; per-week phase (Base/Build/Rest/Peak); totals «sessions per week» + hours; insert/delete week; plan-level menu (`REFERENCE.md` R-1, R-3).
- **Ours (O cloud + ours-L):** one text field «2 2 0 2» for the whole plan, workouts rotate «по очереди», same day pattern every week, no duration/start/goal, no week insert/delete, phase fixed; «Добавить в план» from a workout adds one item to the current week only.
- **Impact:** weekly distribution — the core of plan building — is not controllable per workout/week; two unrelated entry points.
- **Recommendation:** one editor reachable from both entries: per-workout weekly quantity (**PROPOSAL Q2**: whole sessions only; 0.5 only if the owner asks), week phases, totals, insert/delete week with confirmation (UX-28).
- **Evidence:** `reference/screens/p1_15…p1_24`; `artifacts-local/l5-01-form.png`, `l3-02-after-add-Ср.png`, `l3-03-next-week.png`.
- **AC:** E2E: create 4-week plan, set 2/2/0/1 for workout A and 1/1/1/1 for B, totals row matches, insert and delete a week with confirmation, reload → identical. **Deps:** plan-before-code (data model for per-workout weekly quantity; CLAUDE.md schema rule). **Confidence:** high.

### UX-25 · P1 · OBSERVED (ref + ours-L) — Day placement per week and repeating a workout in one day are hidden
- **Reference (O):** «Week N Schedule»: «+ N» pill = sessions still to place, 7 day circles, per-day totals; tapping the same day again adds another session (cycle 0→N→0); quota spent → silent ignore (`p1_27`, `p1_43`, `p1_44`).
- **Ours-L (O):** the same workout can be put twice on one day only by running «Добавить в план» twice (two identical rows «L Тяга 0/1» under ПОНЕДЕЛЬНИК); no «×2», no per-day total; also accepted for a past day (see UX-31).
- **Impact:** a supported capability (repeat in one day) cannot be found or verified; no overview of load per day.
- **Recommendation:** week schedule view with remaining-count pill, per-day totals and explicit stepper (+/−) per day instead of tap-cycling; when the quota is spent show «все занятия размещены» (do not copy the silent ignore).
- **Evidence:** `reference/screens/p1_27_schedule.png`, `p1_44_after3.png`; `artifacts-local/l3-01-after-add-Пн.png`.
- **AC:** E2E: workout with quantity 2 placed twice on Tuesday, shows «×2» and day total 2; moving one to Thursday updates both totals. **Deps:** UX-24. **Confidence:** high.

### UX-26 · P3 · OBSERVED — Plan progress is shown as a bare counter
- **Reference (O):** per-category rings (done/planned) and green «1/1 ✓» on the card; credit derived from logs by date + workout; deleting a log reverts at once (`p1_51`, `p1_52`, `p1_62`).
- **Ours:** «Текущая неделя · 0 из 3» and «0/1» per row. **Credit rule stays as specified** (J7: a direct start does not credit a course occurrence) — only the presentation is a gap.
- **AC:** card shows a done state; week header shows progress per category; consistent after deleting a Journal entry.

### UX-27 · P2 · OBSERVED — Plan lifecycle: Upcoming plans, start date, clone, delete, empty states
- **Reference (O):** In Progress / Upcoming / Completed; start-week calendar with overlapping days disabled; Change Start Date; Clone; Delete with confirm; empty Upcoming text (`p1_01`, `p1_38`, `p1_41`, `p1_79`, `p1_80`).
- **Ours:** «Сейчас / Завершённые», «Остановить план»; no future plan, no start date, no clone.
- **Recommendation:** adopt Upcoming + start date + clone; overlapping start dates disabled **with a visible reason** (the reference gives none).
- **AC:** create a plan starting next week → appears under «Предстоящие»; picker blocks days of the active plan with a message; clone creates an identical draft.

### UX-28 · P2 · OBSERVED — Destructive plan edits must confirm (intentional difference from the reference)
- **Reference (O):** Delete Week (with its volume), Remove From Plan, un-scheduling are immediate and unconfirmed (`p1_23`, `p1_24`, `p1_77`).
- **Ours:** remove already confirms inline; the future week/plan operations of UX-24/27 must do the same.
- **Documented reason for the difference:** irreversible loss of user-entered data; Telegram WebView.
- **AC:** every delete of a week/workout/plan has an in-app confirmation naming what is lost; Cancel restores nothing to change.

### UX-29 · P3 · OBSERVED — Per-week notes
- **Reference (O):** «Week N Notes» sheet (`p2_06`). Ours: none. Candidate feature; low priority.

### UX-30 · P3 · OBSERVED (ref) / INFERRED (ours) — Analytics metric switch
- **Reference (O):** dropdown {Workouts Logged, Duration (min), Time Under Tension (min), Estimated Workload}, periods 1 Mo./3 Mo./Custom (`p1_82`). Ours: fixed tiles (O cloud). Depends on UX-03/04 (what «Duration» means).

### UX-31 · P2 · OBSERVED (ours-L) — Row actions inconsistent; move into the past accepted silently; Move screen without in-page Back
- **Actual:** in the current week rows only have «Начать»; in future weeks rows have «⋯» (Перенести / Редактировать тренировку / Убрать из плана). Moving a session to Mon 12 Oct when today is 18 Oct succeeds with no message and the row keeps «Начать» (four Monday sessions in the past). Move screen shows only week/day pickers and «Сохранить»; Escape does nothing (Telegram BackButton not rendered in the harness — UNKNOWN in the real client).
- **Evidence:** `artifacts-local/l4-01-week1.png`, `l5-03-week2.png`, `l6-01-row-sheet.png`, `l6-02-move-screen.png`, `l7.log` (`after-move-to-past`, `week1-after`).
- **Recommendation:** same «⋯» on every row of an editable week; past days disabled or marked «пропущено»; visible «Отмена» on the sheet.
- **AC:** E2E: a past day cannot be chosen (or is labelled), current-week rows expose the same actions, Cancel leaves the plan unchanged. **Deps:** none. **Confidence:** high for the observed behaviour, medium for «real client».

### Not to copy (documented in `REFERENCE.md`)
Estimated durations (spec: active time) · future-dated logs mis-filed in the current month (spec: 422) · silent tap-ignore when the quota is spent · no confirmation on destructive plan edits · no resume after a killed player.

## Original owner complaints (added at the final audit step; evidence in `COMPLAINTS.md`)

### UX-32 · P1 · OBSERVED (production, read-only) — Course shows 3 sessions per week for an older course connection; nothing explains why
- **Scenario:** owner account (`telegram_id 65107390`, users.id 1) → Планы → current week 12–18 Oct, course «Подтягивания».
- **Actual (prod data):** inclusion #13 has a **legacy snapshot** (strategy `step`, no frozen `slots`, no `schedule`); catalogue `frequency.sessions_per_week = 3`; plan items 63/64/65 = `main` occurrences 1–3, occurrence 1 already done on 17 Oct (session 74). The owner sees «1 из 3» and two open rows, expecting 2 per week.
- **Why (requirement):** `PULLUPS_V5_6` §schedule — only a *new* V5.6 inclusion is frozen at 2/week; older snapshots keep their schedule, history is not rebuilt. So the number is correct by rule; **the product never says so and offers no way to change it**. Together with the 3-day minimum spacing (OD-2) the third occurrence is the one shown as «Не успеть на этой неделе» (UX-01).
- **Impact:** the owner reads the plan as wrong; trust in every other number drops.
- **Recommendation (PROPOSAL Q3):** (a) the course card and plan header state the schedule version in words («Расписание вашей версии курса: 3 занятия в неделю»); (b) an explicit opt-in «Перейти на 2 занятия в неделю» that changes only future weeks and leaves history, progression state and `completed_main_sessions` untouched; (c) the third row of a week that cannot be placed is labelled, never offered as startable (UX-01). No production change is part of this audit.
- **Evidence:** `COMPLAINTS.md` §1 (queries and code references).
- **AC:** E2E on a **legacy-snapshot inclusion fixture** (not a fresh profile): card names the schedule and the reason; after the opt-in, current/future weeks show 2 occurrences, the done one stays done, history identical, repeat convergence = 0 changes. **Deps:** UX-01 (row states); Q3 default. **Unknown:** how many other prod users carry a legacy snapshot (one read-only count before the block starts).

### UX-33 · P1 · OBSERVED (code + prod data) — Free electives exist but cannot be found
- **Actual:** no switch exists; electives are always on (limit 2 per rolling 7 days, rotation without repeat), free by owner decision 2026-10-17. The only UI is `ElectiveScreen` inside the legacy `WorkoutScreen`, which left the bottom navigation (issue #175) and opens only through «Перейти в обычную "Тренировку"» on blocked-start screens. Home/Plans/Journal never mention electives. Owner has 0 electives in prod.
- **Impact:** a promised free feature is invisible; the rest-day status (issue #94) that offers it is itself unreachable from the main path.
- **Recommendation:** an entry in the course/plan context — on the plan when the next main session is not available («Сегодня отдых — можно факультатив»), on the course card («Факультативы: 0 из 2 на этой неделе»), and in Home «+» menu; one explanatory line on the card: free, up to 2 per week, never affects progression. Reuse `ElectiveScreen` and `/api/v2`/`/api/elective/*` as they are.
- **AC:** E2E: from the course card and from the rest-day plan state a user reaches the elective form in ≤2 taps, submits, sees it in Journal as «факультатив», the weekly counter becomes 1/2, a third attempt shows the limit message; no subscription gate. **Deps:** UX-01 (rest-day state), UX-20 disappears. **Unknown:** whether the Journal elective card shows the type clearly (not re-checked).

### UX-34 · P2 · UNVERIFIED — «Подборки» layout reported broken in real Telegram
- **Verified:** with production-identical content (1 collection) Chromium and WebKit at 320/360/390, light/dark: no overflow, nothing clipped, collection screen fine. Cosmetic observations only: lone card at ~2/3 width with an empty gutter; «ПОДБОРКА» label tight against the cover edge; earlier audits: late-load shift (fixed in `7500c37`) and ellipsised protocol lines at 375.
- **Not verified (specific):** rendering in a real Telegram WebView (safe-area, `--tg-*` variables at first paint, device fonts). Not replaced by the Chromium/seed result.
- **Needed to close:** a screenshot/recording from the owner's device (device + OS), or the Mini App console output from it; then one targeted fix.
- **Recommendation meanwhile (low risk):** let a single collection card span the row width; reserve the row height before the data loads; keep `min-width:0` on card text. **AC:** the owner's screenshot reproduces, then the same view passes on Telegram Web + one real client. **Deps:** the owner's screenshot; none technical.
