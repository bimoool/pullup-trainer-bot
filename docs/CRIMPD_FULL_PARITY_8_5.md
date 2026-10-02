# Crimpd 8.5.x — full functional parity matrix

**Mandate (owner, 2026-10-02).** Crimpd 8.5.x is the full functional UX reference. Replicate
user-visible capabilities where technically possible, adapted to our training domain. Differences
require an explicit documented domain/platform reason. (Also in `CLAUDE.md`-referenced skills
`crimpd-reference`, `product-reference`, `docs/plan-and-specs.md`, `docs/IMPLEMENTATION_PLAN.md`.)

**Evidence.** Black-box only — `~/android-ref-lab/` on Crimpd 8.5.3 (Android, single WebView), no
decompilation. Short refs: **PR** `CRIMPD_PRODUCT_REFERENCE.md`, **RM** `REF_MAP.md` §, **FI**
`FLOW_INDEX.md` F#, **HO** `HOME_OBSERVATIONS.md`, **N1** `flows/notes_part1.md`, **d/x**
`REF_2_1/dumps_sanitized/x` (UI text dumps), **LED** `TEST_DATA_LEDGER.md`. Capability ids (H1, W3, …)
follow the campaign inventory. Items marked *(unobserved)* were not seen in Crimpd — the target is
ours, not copied.

**Status:** DONE (user can reach and use it today) · PARTIAL · MISSING · DOMAIN-EQUIVALENT (mapped
to our domain on purpose, reason given) · PLATFORM-IMPOSSIBLE (Telegram Mini App / web cannot do it).
A row becomes DONE only with automated evidence (`crimpd-parity.spec.ts` block or named spec).

**Tester.** Parity suite = `webapp-frontend/e2e/scenarios/crimpd-parity.spec.ts` (baseline + the
first task blocks) + one file per later task in `webapp-frontend/e2e/scenarios/parity/` (helpers:
`e2e/fixtures/parity.ts`; serial `parity` Playwright project — appending to one shared file made
stale branches conflict). The worker's deterministic gate runs the full Playwright suite before
any merge into `develop/current`.

## Home

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Sticky header with search pill + «+» | H1, G4; HO 2; RM §0 | HomeScreen.tsx sticky header (search pill + «+») | DONE | — | sticky «Что потренируем сегодня?» + «+» | #254 | crimpd-parity.spec.ts «Home» |
| Search screen: live filter, «FOUND N», clear | S1, S4; RM §3; FI F4 | SearchScreen.tsx (client-side) | DONE | — | search over programs, own workouts, exercises | #254 | crimpd-parity.spec.ts «Home»; tests/homeDiscovery.test.ts |
| Search filters: category / equipment / favorites / home-only / tests-only | S2–S3; d/search_filter_all | category + «Избранное» chips on Search | PARTIAL | equipment: DOMAIN — exercises have no equipment field | category chips (#254, done), favorites chip (#272, done) | #254, #272 | crimpd-parity.spec.ts «Home» (category chips), «Favorites» (chip) |
| Category rows (horizontal carousels, «N Workouts») | H2–H4, H13; HO 3 | program rows grouped by category («Другое» for none) | DONE | — | programs grouped by `Program.category` rows | #254 | crimpd-parity.spec.ts «Home»; tests/homeDiscovery.test.ts |
| Category screen (info, Featured / All) | H4; d/category_all_tab | none | MISSING | — | category row → filtered search (Featured tab: DOMAIN — no editorial flag yet; collections cover curation) | #254, #271 | — |
| Featured playlists carousel | H5; HO 4 | none | MISSING | no collections model | «Подборки» row from curated collections | #271 | — |
| «Create Custom Workouts» banner | H6 | «Создать» button on Главная | DONE | — | — | — | home-discovery.spec.ts |
| My Workouts grid | H7 | «Мои тренировки» list | DONE | — | — | — | home-discovery.spec.ts, crimpd-parity Baseline |
| «Log Cross-Training» banner / entry | H8 | Журнал «+ Записать» → «Другую активность»; «+» sheet на Главной → «Записать в журнал» | DONE | — | — | #263 | crimpd-parity.spec.ts «Journal log»; tests/test_web/test_v2_journal_log.py; tests/journalLog.test.ts |
| Favorite Workouts row | H9 | «Избранное» row on Главная (workouts + programs; hint only if never favorited) | DONE | — | — | #272 | crimpd-parity.spec.ts «Favorites»; tests/test_web/test_v2_favorites.py |
| «Start Open Climbing Session» banner | H10; J9 | — | DOMAIN-EQUIVALENT | climbing-specific | free activity logging + Start from Workout Detail cover it | #263, #273 | — |
| Assessment Tests carousel | H11 | «Тесты» row on Главная → hub (cards: last result, trend) | DONE | — | — | #260 | crimpd-parity.spec.ts «Tests»; tests/test_web/test_v2_assessments.py; tests/assessmentsFormat.test.ts |
| «+» sheet (session / log / create / cancel) | H12; d/plus_sheet; FI F2 | «+» sheet in Home header: create / today / «Записать в журнал» / cancel | DONE | — | — | #254, #263 | crimpd-parity.spec.ts «Home» (create / today / cancel), «Journal log» (Главная → «+» → шторка записи) |
| No plan/streak widget on Home | H14 | Home has no week widget | DONE | — | (our skill once planned a week widget; Crimpd has none — Plans tab owns the week) | — | crimpd-parity Baseline |

## Workout Detail

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Read-only detail separate from editor | W1–W2, W7, W10; d/41_workout_detail, d/custom_workout_detail | WorkoutDetailScreen (card on Главная / «Мои тренировки» opens it; editor via «Редактировать») | DONE | — | — | #255 | crimpd-parity.spec.ts «Workout Detail» |
| Duration / equipment / description | W7, W10 | «≈ N мин» only when every item is time_sets/interval, otherwise no estimate | DONE | equipment: DOMAIN (not modelled) | estimate from stored protocol only, never a guess | #255 | crimpd-parity.spec.ts «Workout Detail», workoutDetailFormat.test.ts |
| Exercise rows with sets·reps·rest | W8 | detail + editor rows (shared formatters) | DONE | — | — | #255 | crimpd-parity.spec.ts «Workout Detail», builder-ux.spec.ts |
| Start Workout | W3, W9; X1 | start only from Plans card | MISSING | no ad-hoc start | «Начать» → freeform live session | #273 | — |
| Log Workout | W3, W6 | Журнал «+ Записать» → «Тренировку из моих» (source=backdated) | DONE | — | — | #263 | crimpd-parity.spec.ts «Journal log»; tests/test_web/test_v2_journal_log.py; tests/journalLog.test.ts |
| Favorite (instant toggle) | W3–W4 | ♡/♥ on Workout Detail and Program Detail, optimistic, reverted on error | DONE | — | — | #272 | crimpd-parity.spec.ts «Favorites» (toggle, reload, error revert) |
| Add to Plan (2-step sheet: new / existing plan) | W5; d/add_to_plan_sheet; FI F8 | AddToPlanScreen (day picker), round button on detail | DOMAIN-EQUIVALENT | — | one active plan → add to plan + day directly (no «new plan» step) | #255 (entry on detail) | plans-add-exercise.spec.ts, crimpd-parity.spec.ts «Workout Detail» |
| Logged Workouts history (range, load previous) | W11 | Workout Detail «История» (`GET /api/v2/workouts/{id}/sessions`; no range / load-more yet) | DONE | — | — | #255 | test_v2_workout_sessions.py, crimpd-parity.spec.ts «Workout Detail» |
| Hero photo / Overview video | W1 | none | MISSING | no media for user workouts; videos blocked on content (#3) | system/program media when MediaAsset content exists | #3 (owner content) | — |
| Edit / delete workout | C11 | editor: «Удалить тренировку» (inline confirmation, soft-archive, history/Journal preserved, manual plan items removed) + «Дублировать» («… (копия)») | DONE | — | — | #261 | crimpd-parity.spec.ts «Workout delete/duplicate»; tests/test_web/test_v2_workout_delete_duplicate.py; home-discovery.spec.ts (edit) |

## Custom Workouts (builder)

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Create / edit workout | C1, C9–C10 | WorkoutEditorScreen | DONE | — | — | — | builder-ux.spec.ts, home-discovery.spec.ts |
| Delete workout | C11 | no route/UI | MISSING | — | confirm, keep history | #261 | — |
| Exercise search + «Create Exercise: <query>» | C3–C4 | ExercisePickerScreen | DONE | — | — | — | builder-ux.spec.ts |
| Exercise edit / delete in workout | C12 | edit, delete, move ↑↓ | DONE | — | — | — | builder-ux.spec.ts |
| Sets/reps steppers, rest, rep timer, notes | C5–C6 | ProtocolForm (4 protocols, steppers, mm:ss) | DOMAIN-EQUIVALENT | per-rep timer / tempo not modelled | our protocols reps/time/max/interval; per-set targets one static value (UX_REFERENCE_AUDIT data-model facts) | — | builder-execution.spec.ts |
| Precise durations (mm:ss) | C5 | time rows mm:ss | DONE | — | — | — | builder-ux.spec.ts |
| Wizard: type → category → sub-focus | C2, C7–C8 | single form | DOMAIN-EQUIVALENT | user workouts have no category field | category derived from exercises; wizard steps not needed | — | — |
| Total time in header | C5 | preview per item + whole-workout estimate on detail | DONE | — | — | #255 | crimpd-parity.spec.ts «Workout Detail», workoutDetailFormat.test.ts |
| Duplicate workout | (not in Crimpd builder; Clone Log/Plan exist) | none | MISSING | — | «Дублировать» | #261 | — |

## Training Plans

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| In Progress / Upcoming / Completed tabs | P2–P5; N1 | «Сейчас \| Завершённые» tabs: current-plan card (week of fixed-length courses, «N из M» this week) + week view; completed = removed programs with date range | DONE | — | — | #266 | parity/plans-overview.spec.ts «Plans overview»; tests/test_web/test_v2_plan_overview.py; plansOverview.test.ts |
| Plan card «Week n of N», progress | P3 | none | MISSING | — | «Сейчас» card with week + progress | #266, #258 | — |
| Create blank plan (name, duration, start, goal) | P8 | one plan auto-exists | DOMAIN-EQUIVALENT | one active plan by design (architecture §1; Crimpd also allows one active) | plan exists; programs are added | — | plans-plan-week.spec.ts |
| Skill Templates grid | P6 | «Курсы» on Главная; programs of the plan on the «Сейчас» card | DONE | — | — | #266 | parity/plans-overview.spec.ts «Plans overview» |
| Template detail: level, hours/week, week schedule, phases | P7; d/plan_template_schedule | ProgramDetailScreen: schedule from ProgramItem (phase chips, per-day/pool rows, STEP start targets); description only when no items | PARTIAL | no level / hours per week (not in program data, not invented) | level selector only if present in program config | #266 | parity/plans-overview.spec.ts «Plans overview»; test_v2_plan_overview.py |
| Add template/workout to plan | P7, W5 | program-inclusions, plan-items | DONE | — | — | — | golden-journey.spec.ts, plans-add-exercise.spec.ts |
| Week stepper with phase chip and dates | P9 | one-week view with ‹ Неделя N · даты › + phase chip | DONE | — | — | #258 | crimpd-parity.spec.ts «Plans week», planWeekNav.test.ts |
| Per-row done counters «0/1», week progress | P3, P9–P10 | `done_count` in GET /api/v2/plan (derived, no column); «N из M» header | DONE | — | — | #258 | crimpd-parity.spec.ts «Plans week», tests/test_web/test_v2_plan_done_counts.py |
| Schedule future weeks | P9 «Schedule» (unobserved beyond label) | current week only | MISSING | — | up to 4 weeks ahead | #275 | — |
| Flexible rescheduling (move day) | RM §4 | MovePlanItemScreen (manual items) | PARTIAL | no move across weeks | move across weeks | #275 | plans-plan-week.spec.ts |
| Completed / skipped state | P10 | counters «сделано/план»; past weeks read-only, unfinished stays as is | DONE | — | — | #258 | crimpd-parity.spec.ts «Plans week» |
| Clone plan incl. schedule | P11 (menu label only) | none | MISSING | — | copy week schedule → next week (one-plan model) | #275 | — |
| Edit plan / change start date / delete plan | P11 | «Убрать курс из плана» (confirmation, is_active=false, history kept → «Завершённые») | DOMAIN-EQUIVALENT | single open-ended plan; start-date change out of scope | — | #266 | parity/plans-overview.spec.ts «Plans overview»; test_v2_plan_overview.py |
| Crimpd+ upsell on plans | P1 | our subscription (Robokassa) elsewhere | DOMAIN-EQUIVALENT | our own paywall model | — | — | — |

## Live Workout

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Full-screen player, big timer, state label | X1–X3 | SessionLiveScreen / IntervalLiveScreen | DONE | — | — | — | builder-execution.spec.ts |
| Timer phases (get ready → work → rest → done) | X3, X8 | phases get_ready/go/rest/between/done | DONE | — | — | — | builder-execution.spec.ts, session-complex.spec.ts |
| Set / rep display «1/3 SET» | X5 | «Подход n/N · Цель» | DONE | — | — | — | builder-execution.spec.ts |
| Logging during session (per set) | X5 | «Внести подход» value + note | DONE | — | — | — | builder-execution.spec.ts |
| Per-set effort «How hard was this set?» with words | X5, X12 | chips «1»…«5» + words (Очень легко…Предел) | DONE | — | — | #257 | crimpd-parity.spec.ts «Live effort»; tests/effortScale.test.ts |
| Workout effort + additional notes at end | X10 | review step on finish → /complete effort+comment, shown in Journal | DONE | — | — | #257 | crimpd-parity.spec.ts «Live effort»; tests/test_web/test_v2_live_session_review.py |
| Logging panel follows timer (collapsed work / expanded rest) | SKILL rule 3; Crimpd shows manual toggle X5–X6 *(auto rule unobserved)* | work: value + «Готово» (effort/note via toggle); rest ≥ 20 s: auto-expanded edit of the just-logged set (same `set_index`); short rest: collapsed + «Изменить» | DONE | — | — | #265 | crimpd-parity.spec.ts «Live logging panel»; webapp-frontend/tests/liveLoggingPanel.test.ts |
| GET READY in final 10 s *(unobserved in Crimpd; owner target)* | X13 | «Приготовься · N» under the rest timer in the last 10 s; existing end-of-phase beep | DONE | — | — | #265 | crimpd-parity.spec.ts «Live logging panel»; webapp-frontend/tests/liveLoggingPanel.test.ts |
| Add Set beyond prescribed | X10 | «+ Ещё подход» after the last planned set → `sets:batch` `is_extra` | DONE | — | — | #264 | crimpd-parity.spec.ts «Live extra set & pause»; tests/test_web/test_v2_live_session_extra_set.py |
| Pause / resume | X7 | «Пауза»/«Продолжить» on get-ready/rest, kept in local snapshot (interval: not offered) | DONE | — | — | #264 | crimpd-parity.spec.ts «Live extra set & pause»; webapp-frontend/tests/livePauseExtra.test.ts |
| Skip rest / next set | X7–X8 | «Пропустить отдых» | DONE | — | — | — | builder-execution.spec.ts |
| Resistance ± kg per set | X5, X10 | not modelled for builder sets (bands in legacy STEP) | DOMAIN-EQUIVALENT | weight per set not stored in v2 | our bands/weighted progression lives in programs | — | — |
| Auto log review after DONE | X9–X11 | Summary screen | DONE | — | — | — | session-summary-exit.spec.ts |
| Background / reopen reconciliation | N5 *(unobserved)* | IndexedDB snapshot, /live/active | PARTIAL | countdown/phase contract after background not pinned | timestamp reconciliation, no double transition | #269 | session-recovery.spec.ts |
| Exactly-once completion, offline | — (ours) | sets:batch, idempotent complete | DONE | — | — | — | session-offline.spec.ts, session-back-button.spec.ts |
| Audio cues | N6 (settings only) | single beep at phase end | PARTIAL | no settings, replay after background | volume in Settings; no replay | #268, #269 | — |
| Wake lock / keep awake | X13 *(unobserved)* | NoSleep.js | PARTIAL | not re-acquired on resume | re-acquire on visible | #269 | — |

## Logbook (Журнал)

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Month bar + expandable calendar with dots | J1–J2; d/logbook_month_picker; FI F5 | JournalCalendar (month bar, Mon-first grid, dots, day select) + `GET /api/v2/journal/days` | DONE | — | month bar + calendar | #256 | crimpd-parity.spec.ts «Journal calendar»; tests/test_web/test_v2_journal_calendar.py |
| Week / day grouping, infinite scroll | J3 | JournalTimeline: week bands + day headers, per-month «Показать ещё» paging | DONE | — | week bands + day headers | #256 | crimpd-parity.spec.ts «Journal calendar»; journal-v2.spec.ts (paging) |
| Log card stats (intensity, completion, TUT, duration, workload) | J4 | v2 cards: plan vs fact, effort, comment | DOMAIN-EQUIVALENT | TUT/workload not stored | our per-protocol results; duration after #259 | #259 | journal-v2.spec.ts |
| Log detail sheet (session + exercise details) | J5; d/logbook_ref_sheet | JournalV2Detail | DONE | — | — | — | journal-v2.spec.ts |
| View Workout from log | J5 | none | MISSING | — | link to Workout Detail | #255 | — |
| Edit Log | J5, J7 *(form unobserved)* | «✏️ Изменить» in Journal detail (sets value/effort/note, workout effort/comment, date ≤ today) via `PATCH /sessions/{id}`; only when `can_edit` (delete predicate), else hidden / 409 | DONE | program-backed/STEP sessions not editable (owner decision) | — | #262 | crimpd-parity.spec.ts «Journal edit/clone»; tests/test_web/test_v2_session_edit_clone.py; webapp-frontend/tests/journalEdit.test.ts |
| Clone Log | J5, J7 *(form unobserved)* | «⧉ Повторить (клонировать)» with date picker (default today) via `POST /sessions/{id}/clone`, `source=backdated`, no progression | DONE | same predicate as edit | — | #262 | crimpd-parity.spec.ts «Journal edit/clone»; tests/test_web/test_v2_session_edit_clone.py |
| Delete Log with confirm | J6; LED | safe delete (`can_delete`, 404/409) | DONE | — | — | — | journal-v2.spec.ts, golden-journey.spec.ts |
| Backdated logging | W6 | «Тренировку из моих»: своя Workout, дата ≤ сегодня, подходы, усилие, заметка; без побочных эффектов прогрессии | DONE | — | — | #263 | crimpd-parity.spec.ts «Journal log»; tests/test_web/test_v2_journal_log.py; tests/journalLog.test.ts |
| Notes | J4–J5 | set notes + session comment shown | PARTIAL | session note not enterable | review step | #257 | journal-v2.spec.ts |
| Cross-training / free activity | J8 | «Другую активность»: тип из 8, длительность ч:мм (1 мин–12 ч), усилие 1–5, заметка; карточка с типом/длительностью; минуты Analytics из `duration_seconds` | DONE | — | — | #263 | crimpd-parity.spec.ts «Journal log»; tests/test_web/test_v2_journal_log.py; tests/journalLog.test.ts |
| History per workout | W11 | none | MISSING | — | Workout Detail «История» | #255 | — |

## Analytics

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Workout count | A2 | metric «Тренировки» × range, weekly | DONE | — | — | #259 | crimpd-parity.spec.ts «Analytics metric»; tests/test_web/test_v2_analytics_metrics.py |
| Training minutes (Duration) | A1–A2 | metric «Минуты», `completed_at`, honest exclusions («без данных о времени: N») | DONE | — | — | #259 | crimpd-parity.spec.ts «Analytics metric»; test_v2_analytics_metrics.py; test_v2_live_session_review.py |
| TUT / Workload | A1–A2 | not stored | DOMAIN-EQUIVALENT | no rep tempo / load-intensity model | per-protocol metrics (reps, work time, PB) instead | — | analytics-v2.spec.ts |
| Range 1 Mo / 3 Mo / Custom | A3 | tabs 1 мес / 3 мес / Свой (+ «Применить») | DONE | — | — | #259 | crimpd-parity.spec.ts «Analytics metric» |
| Weekly chart | A5 | weekly SVG bars (Monday-labelled) for metric × range | DONE | — | — | #259 | crimpd-parity.spec.ts «Analytics metric»; analytics-v2.spec.ts |
| Distribution by type (sunburst) | A4 | none | MISSING | — | SVG donut by category | #274 | — |
| Multi-month summary table | A6 | none | MISSING | — | summary table + TOTAL | #274 | — |
| Exercise trends / personal bests | (ours beyond Crimpd) | per-exercise panels, PB markers | DONE | — | — | — | analytics-v2.spec.ts |
| Info (i) definitions | A1 | ⓘ sheet with both metric definitions | DONE | — | — | #259 | crimpd-parity.spec.ts «Analytics metric» |
| Export CSV | A7 | none | MISSING | — | CSV download | #267 | — |
| Live recompute on log add/delete | A8 | computed per request | DONE | — | — | — | golden-journey.spec.ts |

## Profile / Settings

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Current attributes (name, age, gender, height, weight) | R1–R2, R11 | ProfileScreen + ProfileEditForm | DONE | — | — | — | crimpd-parity Baseline |
| Attribute history | R2 *(target screens unobserved)* | single values | MISSING | — | weight/height history with trend | #270 | — |
| Edit / delete historical metrics | — | none | MISSING | — | edit/delete entries | #270 | — |
| Grade chart (boulder/route) | R3 | GTO / WSF cards | DOMAIN-EQUIVALENT | no climbing grades | our norms (GTO/WSF) | — | — |
| Assessments (primary / additional, last result, sparkline) | R4–R5 | «Тесты» card on Профиль (3 seeded protocols, last result, mini-trend ≥2) | DONE | no primary/additional split | — | #260 | crimpd-parity.spec.ts «Tests»; tests/test_web/test_v2_assessments.py; tests/assessmentsFormat.test.ts |
| Test detail: chart, history | R6, R8 | description, SVG trend, history (newest first), record / edit / delete own results | DONE | — | — | #260 | crimpd-parity.spec.ts «Tests»; tests/test_web/test_v2_assessments.py; tests/assessmentsFormat.test.ts |
| Peer Insights | R7 | leaderboard (legacy data) | MISSING | — | percentile vs cohort, ≥20 users or honest «мало данных» | #276 | — |
| Units (kg/lb, cm/in) | R11 | hard-coded metric | MISSING | — | display units | #268 | — |
| Timezone | R11 | ProfileEditForm timezone | DONE | — | — | — | — |
| Theme Light / Dark / Auto | R13 | follows Telegram only | PARTIAL | no override | «Как в Telegram / Светлая / Тёмная» | #268 | mobile-layout.spec.ts (both themes) |
| Timer settings (volume, vibrations) | R14 | API exists, UI hidden | PARTIAL | unreachable | Settings «Таймер» | #268 | — |
| Subscription management | R10, R17 | SubscriptionScreen | DONE | — | (in Settings too) | #268 | — |
| Data export (Download Logbook) | R15 | none | MISSING | — | Settings → CSV | #267, #268 | — |
| Delete account | R16 *(not tapped)* | none | MISSING | irreversible data operation | **needs owner decision** (retention, legal) — not in campaign | — (owner) | — |
| Change password | R10 | Telegram auth | DOMAIN-EQUIVALENT | no passwords (Telegram identity) | — | — | — |
| Settings screen with Cancel / Save | R9 | scattered forms | MISSING | — | Settings screen | #268 | — |

## Content discovery

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Curated playlists (creator, description, workouts) | D1; d/playlist_detail | none | MISSING | — | curated collections (author «Турникмэн», no social links) | #271 | — |
| Category collections (sub-focus cards) | D3 | programs not grouped | MISSING | — | category rows | #254 | — |
| Templates (levels, phases) | D4 | Programs (structure types) | PARTIAL | no preview | schedule preview | #266 | — |
| Progressions (lettered / % variants) | D5 | programs + auto-progression (ours) | DOMAIN-EQUIVALENT | our progression model | — | — | session-progression-edit.spec.ts |
| Tests discoverable from Home + search filter | D6 | none | MISSING | — | Tests row + search | #260, #254 | — |

## Platform

| Crimpd feature | Reference evidence | Our current screen/API | Status | Missing behavior | Target behavior | GitHub issue | Automated test evidence |
|---|---|---|---|---|---|---|---|
| Dark / light | R13, N7 | Telegram theme mapping | DONE (override in #268) | — | — | #268 | mobile-layout.spec.ts |
| Responsive widths | — | mobile layout 320–390 | DONE | — | — | — | mobile-layout.spec.ts, crimpd-parity Baseline |
| Background timer | N5 *(unobserved)* | timestamp-based phases | PARTIAL | contract not pinned | reconciliation on resume | #269 | session-recovery.spec.ts |
| Notification permission / push for timer | N1–N2 | bot reminders (ours) | PLATFORM-IMPOSSIBLE | a Mini App cannot post native local notifications | Telegram bot messages for reminders | — | — |
| Live Activities / Dynamic Island / lock-screen controls | N3 (iOS-native) | none | PLATFORM-IMPOSSIBLE | Telegram Mini App is a WebView inside Telegram: no ActivityKit, no lock-screen media session for timers, no background execution | accurate resume (#269) + bot reminders | — | — |
| Home-screen widgets | N4 | none | PLATFORM-IMPOSSIBLE | no widget API for Mini Apps | — | — | — |
| Background audio while app hidden | N6 | beep only while visible | PLATFORM-IMPOSSIBLE | WebView suspends timers/audio when Telegram is backgrounded | no replay of missed cues (#269) | #269 | — |
| Health / wearable integrations | N8 (none in Crimpd) | none | DONE (parity: none) | — | — | — | — |
| Hamburger drawer (Help / Settings / Logout) | G2 | bottom tabs + Telegram menu | DOMAIN-EQUIVALENT | Telegram owns app chrome; no logout | Settings via Profile gear (#268) | #268 | — |
| PWA-equivalent behaviour | — | Telegram Mini App (PWA planned, product-reference) | PARTIAL | web/PWA build is a later phase | — | — | — |

## Totals (2026-10-02)

| Status | Count |
|---|---|
| DONE | 25 |
| PARTIAL | 20 |
| MISSING | 54 |
| DOMAIN-EQUIVALENT | 14 |
| PLATFORM-IMPOSSIBLE | 4 |
| **Total capabilities** | **117** |

(Counted by the `Status` column above; a row with "DONE (override in …)" counts as DONE.)

## Campaign issues

P0: #254 Home discovery · #255 Workout Detail · #272 Favorites (after #255) · #273 Start/Log from
detail (after #255, #263).
P1: #256 Journal calendar · #257 Live effort · #258 Plans week · #259 Analytics metric/range ·
#260 Tests hub · #261 Workout delete/duplicate · #262 Journal edit/clone · #263 Journal log ·
#264 Extra set & pause · #265 Logging panel / GET READY · #266 Plans overview · #267 CSV export ·
#268 Settings · #269 Background timer · #270 Body metrics · #274 Analytics distribution (after
#259) · #275 Plans schedule (after #258).
P2: #271 Collections · #276 Peer Insights (after #260).
QA: #277 Full parity sweep (last).

Dependent issues stay `status:backlog` and are promoted to `status:ready` when their
dependencies are done. Owner decisions outside the campaign: account deletion; exercise/program
media content (#3).
