# Evidence backlog — UX reference audit 2026-10-18

One list, stable IDs. Evidence = files in `artifacts/` (screenshot + `<script>.log` with the visible text and
network calls of every step); scripts in `harness/` reproduce them. **Ref** is the reference status: no item
has OBSERVED reference evidence (access blocked); HISTORICAL = secondhand note, to verify.
Status after pass 2: **CONFIRMED** (reproduced independently) · **OBSERVED** (seen once) · **WITHDRAWN** ·
**NEEDS-OWNER** (product/spec decision before any fix).

Priority: P1 = blocks or misleads a core journey · P2 = wrong/inconsistent information or avoidable friction ·
P3 = polish/copy/a11y.

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
- **Recommendation:** one duration definition (start→complete minus pauses, or work time — owner picks label) used by Summary, Session detail, Journal card and Analytics; never render 0:00 for a session with logged sets.
- **AC:** J1/J10 E2E: the same duration in all four places; no «0:00» with ≥1 set. **Deps:** label decision (work time vs elapsed). **Confidence:** high.

### UX-04 · P2 · CONFIRMED — Journal and Analytics disagree on reps/sets of the same session
- **Scenario:** one course session, 9 sets, 60 reps (last volume set is AMRAP).
- **Actual:** Journal card «Подходы 9 · Повторы 60»; Analytics → Подтягивания «Всего повторений 53 · Подходов 8» (+ «Максимум повторений: 1 попытка, 7»). After a second session: 93 vs 100.
- **Impact:** user sees two different totals for the same history; trust in Analytics.
- **Evidence:** `p1-j1e-05-journal.png`, `p1-j1f.log` (analytics), `p1-an-00-analytics-full.png`, `p2-c-j10.log`.
- **Recommendation:** either include max/AMRAP sets in «Всего повторений» or label the tile «Повторения в рабочих подходах» and show the split.
- **AC:** for any session, Journal totals = Analytics totals, or the difference is labelled on screen. **Deps:** none. **Confidence:** high.

### UX-05 · P2 · CONFIRMED — Onboarding max is not a «Максимум подтягиваний» test; ГТО hint after a workout
- **Actual:** after onboarding Замер (6) Profile/Tests show «Максимум подтягиваний — Ещё не проходили»; after a completed course workout ГТО still says «Внеси первую тренировку, чтобы узнать свой разряд ГТО».
- **Evidence:** `p1-j1-06-empty-Профиль.png`, `p1-j1f.log` (`profile-after`), `p2-recheck.log`, `p1-home.log` (tests).
- **Recommendation:** show the Замер as the first max result (or say «Стартовый замер: 6» in Tests); ГТО hint text must match the condition it actually needs.
- **AC:** fresh user after onboarding sees the Замер value in Tests; ГТО hint changes after the first qualifying workout or names the exact missing condition. **Deps:** owner: is Замер a test result? (Profile text: «Результаты тестов не влияют на прогрессию и стартовый замер»). **Status:** CONFIRMED + NEEDS-OWNER (semantics).

### UX-06 · P2 · CONFIRMED — «Добавить в план» on Program Detail has no next step
- **Actual:** button turns into «В плане»; no link to the plan / start. Onboarding promised «→ «Добавить в план» → «Начать»».
- **Ref:** HISTORICAL R-J1: template add → «In Progress» card (dialog UNKNOWN).
- **Evidence:** `p1-j1b-01-after-add.png`, `p2-recheck.log` (`UX-06 after add`). Contrast custom workout: «Добавить в план» lands on Планы (`p1-j6e-01-after-add-plan.png`).
- **Recommendation:** after adding, offer «Открыть план» / «Начать» (consistent with custom-workout flow).
- **AC:** J1 from Program Detail reaches the first live set without returning to Home. **Confidence:** high.

### UX-07 · P2 · NEEDS-OWNER — First course start requires 9 free-text fields
- **Actual:** pre-start asks reps with volume band + 4 text fields per band × 2 (model, colour, attachment, foot/knee). No pickers, no reuse hint on first run.
- **Evidence:** `p1-j1b-04-pre-start.png`, `p1-j1c-00-prestart-full.png`, `p1-j1c.log` (FIELDS).
- **Domain reason exists** (V5.6: the user's own band, recorded whole; `docs/domain/PULLUPS_V5_6.md`). Options: structured pickers, one shared band, defaults from «Мои резины».
- **AC:** owner decision first. **Deps:** owner.

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
- **Deps:** owner (presentation of «один активный план» model, `crimpd-reference` «Законные отличия»).

### UX-11 · P3 · OBSERVED — Same item listed twice («СЕГОДНЯ» block + day row)
- **Evidence:** `p1-j6e-01-after-add-plan.png`. **Status:** may be intended (today summary) — verify against reference.

### UX-12 · P2 · OBSERVED — Custom plan: weekly volume typed as free text; past days of current week offered
- **Actual:** «Тренировок по неделям: 2 2 0 2 2 0» text field; after creating on Sunday, Mon/Thu rows of the current week show «Начать» with no «пропущено» state; W3 shows «На эту неделю пока ничего не запланировано» although 0 was chosen.
- **Ref:** HISTORICAL Training Plans editor by weeks (`crimpd-reference`).
- **Evidence:** `p1-j6f-*`, `p1-j6g-*`.
- **AC:** per-week steppers; past days marked; W=0 week says «Неделя отдыха по плану». **Deps:** reference observation (layout).

### UX-13 · P3 · OBSERVED — Jargon in plan week: «СВОБОДНЫЙ ПУЛ», «+ Добавить упражнение» in a course week
- **Evidence:** `p1-j1b-03-plans-with-course.png`. **Deps:** reference wording.

### UX-14 · P2 · OBSERVED — Journal cards for timed exercises show only dashes
- **Actual:** seeded «Планка» sessions: «Подходы — · Повторы — · Усилие —».
- **Evidence:** `p1-aged-990001-Журнал.png` (seeded stand 8001). **AC:** timed sets show total time / sets. **Confidence:** medium (seed data).

### UX-15 · P1 · NEEDS-OWNER — Legacy course records: different card, destructive «Удалить» via `window.confirm`
- **Actual:** legacy (pre-v2) course record renders as text («Объём (резина): 10, 10, 10, максимум 11, следующая цель 11 …») with «Изменить / Удалить»; «Удалить» opens a native `confirm` «Это пересчитает цели всех следующих тренировок. Отменить это будет нельзя.» v2 course cards instead say «нельзя удалить, чтобы не нарушить прогрессию».
- **Impact:** inconsistent deletion policy for progression-critical history (CLAUDE.md invariant; PROJECT_SPEC §3); `window.confirm` is blocked in Telegram Web (`docs/incidents.md`, Journal not migrated yet).
- **Evidence:** `p2-legacy-00-journal-full.png`, `p2-legacy.log` (DIALOG text), `p1-aged-900018-Журнал.png`.
- **AC:** owner decides the policy; then one card format and one deletion rule for legacy and v2; no `window.confirm`.

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
