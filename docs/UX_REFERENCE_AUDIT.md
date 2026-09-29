# UX-1 — Reference audit (Crimpd 8.5.3 vs. staging Mini App)

Temporary working document. Black-box only. Evidence: sanitized reference in
`~/android-ref-lab/` (CRIMPD_PRODUCT_REFERENCE.md, FLOW_INDEX.md, `screens_shareable/`) and our
app captured with `webapp-frontend/e2e/scenarios/ux-capture.spec.ts` at 390/320 px (label `before`).
Classes: **A** good difference · **B** UX gap · **C** data-model difference · **D** unknown.
Evidence tags: OBSERVED / INFERRED / UNKNOWN.

## Backend truth that constrains the Builder (class C, not to be faked)

| Protocol | Stored fields | Consequence for UI |
|---|---|---|
| reps_sets | `sets`, `reps` (one static target for all sets), `rest_seconds` | No per-set targets. Show ONE reps value; never render "Подход 1 — 8 / Подход 2 — 6". |
| time_sets | `sets`, `duration_seconds`, `rest_seconds` | 3 fields. |
| max_effort | `attempts`, `rest_seconds` | No target. Rest exists (C4b-1.5). |
| interval | `total_duration_seconds`, `work_seconds`, `rest_seconds`, `starts_with` | **No "rounds" field**: rounds are derived from total time. UI keeps total time as the input and shows derived rounds. |

## Screen-by-screen

| # | Screen | Reference (OBSERVED) | Ours | Class | Verdict / action |
|---|---|---|---|---|---|
| 1 | Home | Sticky search, category carousels, CTA banners, My Workouts grid, "+" sheet | Programs + My Workouts + "Создать" (G3) | A/C | Different content model (programs, not catalog). Keep G3. Check density/CTA only. |
| 2 | My Workouts | Compact tiles: title, 1-line desc, duration | Cards with count · "3 × 8" · names | A | Fine. Card summary must use the shared human summary. |
| 3 | Create entry | Wizard 6 steps, pager n/6, ← and ✕ | Single form: only "Название", Save, then editor | B | Step is a dead-end: user must Save an empty workout before adding exercises; nothing says so. Add helper text + primary CTA "Создать и добавить упражнения". |
| 4 | Workout editor | Detail list: exercise name + "3 sets · 15 reps · 00:07 per rep / Rest 01:00 per set", "…" menu, "+ Add Exercise" | Name + grey summary + **4 tiny buttons per row** (Редактировать ↑ ↓ Удалить), all visually equal | B | Whole row tappable to edit; ↑/↓ as compact icon buttons; delete behind "…"/confirm; "+ Добавить упражнение" as text-button at list end; full-width Save. |
| 5 | Add exercise | Search + alphabetical list, "Create Exercise: Xxx" row on no match | Search + list of plain buttons + separate "Создать своё" form | B (minor) | Selected state + chevrons; "Создать «query»" row on empty result; sticky title. |
| 6 | Protocol picker | (Crimpd has one type per wizard; no protocol concept) | 4 tabs "Повторения / Время / Максимум / Интервалы", no explanation | B/C | Replace by 4 selectable cards with 1-line explanation each. |
| 7 | Reps config | **Label left + −/N/+ stepper right**; mm:ss row for rest; live "clock 02:00" total in header; blue "Add Exercise" | Three bordered inputs with small grey floating labels; "Повторения" (per set? total?) ambiguous; "Отдых" no unit | B | Stepper rows: «Подходы», «Повторений в подходе», «Отдых между подходами» + unit. Preview "3 × 8 повторений · отдых 1:00". |
| 8 | Time config | (n/a) | Same three-input layout | B | «Подходы / Работа в подходе / Отдых между подходами» + preview. |
| 9 | Max config | (n/a) | "Попытки" + "Отдых" | B | «Количество попыток» + «Отдых между попытками», sentence "В каждой попытке — максимум". |
| 10 | Interval config | (n/a; Crimpd rep-timer is the closest: Rep Duration/Rest) | "Общее время / Работа / Отдых" + start segmented + "N рабочих интервалов" | B | Grouped: Работа / Отдых / Общее время / Начать с. Preview "6 раундов · 0:30 работа / 0:30 отдых". |
| 11 | Numeric affordance | Steppers are blue outlined circles (44 px), disabled at min; time rows are grey pills with value on the right | Inputs look like text fields but nothing says number vs. time (`мм:сс` only as placeholder) | B | Steppers for counts; time rows show unit and open the existing mm:ss input. |
| 12 | Save/CTA | One bold full-width primary at bottom, Cancel = ✕ in header | Primary + outlined "Отмена" of equal weight | B | Primary "Добавить упражнение"/"Сохранить"; secondary as text link. |
| 13 | Back | Back preserves wizard state | Back in protocol form drops entered values; picker→form→back loses nothing else | B (minor) | Keep protocol draft while switching type (already local state) — verify + test. |
| 14 | Workout detail | Hero, 4 actions (Start / Log / Fav / Add to plan), exercise rows, "Logged workouts" | Our "detail" *is* the editor; no Start here | C/B | Start is plan-scoped in our model (no standalone start from Builder). Intentional — **INTENTIONAL DIFFERENCE**. Add "Добавить в план" as clear secondary action (exists). |
| 15 | Add to plan | Sheet: New / Existing plan | Screen (AddToPlanScreen) | A | Not reworked (out of scope unless evidence of gap in QA). |
| 16 | Pre-start | Player pre-state "UP NEXT" | SessionPreScreen | D | Review wording only. |
| 17 | Active session | Big timer + state label + set card + transport | "Живая тренировка / название / фаза / «Упражнение · Подход 1/2 · Цель: 8 повт.» / Готов" | A/B | Structure is right. Gap: name of the current exercise is small grey; phase word ("Приготовься") competes with title. Improve hierarchy only, not logic. |
| 18 | Block transition | n/a (Crimpd auto-advances) | BlockTransition.tsx | D | Review copy. |
| 19 | Summary | Log review sheet: effort + set table + Save | SessionSummary | A | Untouched. |
| 20 | Journal/Analytics | Month calendar; metric dropdown, sunburst | JournalV2 / AnalyticsV2 | A | Product-specific, not in scope for this phase beyond spot check. |

## Top gaps to fix (priority order)

1. **B1** Protocol choice has no explanations (segmented tabs of one word each).
2. **B2** Config rows unlabelled/ambiguous: "Повторения" without "в подходе", "Отдых" without "между подходами", no units, no −/+ steppers.
3. **B3** No preview of the resulting workout before saving an exercise.
4. **B4** Editor row: four equal micro-buttons; row not tappable; delete/move visual weight = edit.
5. **B5** Create form dead-ends into an empty editor without explanation.
6. **B6** Exercise picker: no selected/empty-search affordance.
7. **B7** Active-session header hierarchy (current exercise/target).

## Acceptance ledger (filled in UX-D)

| Gap | Status |
|---|---|
| B1–B7 | TBD |
