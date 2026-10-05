# Functional reachability tree: Wave 1 (#295)

Built from Wave 1 evidence (`docs/audit/wave1/{B-fresh-clean,B-fresh-catalog,C-existing}/REACHABILITY.md` + traces). Defect ids are listed in
`docs/FUNCTIONAL_AUDIT_WAVE_1.md` §6. Everything here is **LOCAL only**; staging was not reachable.

Legend: ✅ works and survives reload, and it enables the next action · ❌ FD-id failing · ⛔ BLOCKED BY FD-id · ? untested · n/a not applicable.
Columns: **clean** = `alembic upgrade head` only · **catalogue** = clean + `backfill_multi_program.py` + `seed_exercise_library.py` ·
**existing** = bot-era users after the real backfill (C profiles).

## Goal: FIRST COMPLETED WORKOUT

| Node | clean | catalogue | existing |
|---|---|---|---|
| Open Mini App as a new user → UI onboarding (Замер → Анкета → trial) → Главная | ✅ | ✅ | n/a (no re-onboarding ✅) |
| **A. Program path** | | | |
| A1 Главная shows a course card | ❌ FD-01 («Каталог курсов появится здесь позже.») | ✅ (FD-19 raw «pull_ups») | ✅ «В плане» |
| A2 Program Detail | ⛔ BLOCKED BY FD-01 | ✅ | ✅ |
| A3 «Добавить в план» → «В плане» (+reload) | ⛔ FD-01 | ✅ | already included ✅ |
| A4 Планы: current week has an actionable row | ⛔ FD-01 | ✅ «СВОБОДНЫЙ ПУЛ · Подтягивания 0/3 · Начать» | ✅ (week transition auto-created ✅) |
| A5 Pre-screen matches Live | ⛔ FD-01 | ❌ FD-09 (block Б 4 → 1 set) | ❌ FD-09; ❌ FD-10 for gap users |
| A6 Live → finish → summary | ⛔ FD-01 | ✅ (❌ FD-16 names, P2) | ✅ |
| A7 Too-early day | n/a | ? | ❌ FD-18 (text dead end) |
| → FIRST WORKOUT via program | **⛔ BLOCKED BY FD-01** | **✅** | **✅** |
| **B. Custom path** | | | |
| B1 «Своя программа» / «Создать тренировку» → name → editor | ✅ | ✅ | ? (not run) |
| B2 Picker offers an exercise without typing | ❌ FD-04 (only «Ничего не найдено») | ❌ FD-07 (only «Факультатив…», Планка, Отжимания; no pull-up exercise) | ? |
| B3 Type a name → «Создать своё: «X»» → protocol → «Добавить» | ✅ (FD-23 P3) | ✅ | ? |
| B4 «Сохранить» → detail → reload | ✅ | ✅ | ? |
| B5 Zero-exercise workout → way forward | ❌ FD-04 (Начать disabled, no reason; «Изменить» only) | ❌ FD-04 | ? |
| B6 Detail → «Начать» → Live → finish | ✅ | ✅ | ? |
| → FIRST WORKOUT via custom | **✅ but needs the hidden typing affordance (FD-04)** | **✅** | ? |
| **C. Free path (no plan)** | | | |
| C1 A workout exists without building one (system workout) | ❌ FD-07 / D2 (0 complexes) | ❌ FD-07 / D2 (0 complexes) | ❌ same |
| C2 Own workout → «Начать» without a plan → Журнал «Свободная» | ✅ | ✅ | ? |
| → FIRST WORKOUT via free | **✅ (only through B)** | **✅** | ? |

## PLAN

| Node | clean | catalogue | existing |
|---|---|---|---|
| E1 empty Планы → «Выбрать курс на Главной» resolves | ❌ FD-03 (loop with «Откройте план дня») | ✅ | n/a |
| First «Добавить в план» (no TrainingPlan yet) visible in the current week | ❌ FD-02 | ❌ FD-02 | n/a (plan exists) |
| Add when a plan exists → day / pool → reload | ✅ | ✅ | ? |
| «+ Добавить упражнение» from Планы | ❌ FD-01 (library empty; works once an own exercise exists ✅) | ✅ | ? |
| Move day / pool / other week (+reload) | ✅ | ✅ | ? |
| Copy week (manual rows) | ✅ «Скопировано: 1» | ✅ / course rows ❌ FD-08 «Скопировано: 0» (by spec) | ? |
| Future course week shows course rows | n/a | ❌ FD-08 (by spec; unexplained) | ? |
| › past the last week | ✅ (creates empty week silently, FD-08 P3) | same | ? |
| Week rollover (returning user) | ? | ? | ✅ (upstream S0 injected) |
| Remove manual row (template kept) | ✅ / ❌ FD-12 (Журнал title lost) | ✅ / ❌ FD-12 | ? |
| Remove course → «Завершённые» → re-add | ⛔ FD-01 | ✅ (FD-21 counter reset) | ? |
| Start from a plan row → «1/1 · Ещё раз» | ✅ (FD-21 partial counted done) | ✅ | ✅ «1 из 3» |

## LIVE

| Node | clean | catalogue | existing |
|---|---|---|---|
| Ready → Начать → Готов → reps → rest → skip | ✅ | ✅ | ✅ |
| Time protocol (Планка, «Секунды») | ? | ✅ | ? |
| Max / interval protocols | ? | ? | ? |
| Reload mid-Live (phase + timer + sets) | ✅ | ✅ | ✅ |
| Close context and reopen mid-rest | ? | ? | ✅ (❌ FD-25 chip lost, P3) |
| Offline set → reconnect → batch | ? | ✅ | ✅ |
| Double-tap «Сохранить и завершить» → 1 session | ? | ✅ | ✅ |
| Browser Back during Live | ? | harness → about:blank | ✅ reopen resumes |
| Telegram BackButton during Live | ? | ? | ? |
| Strength block set count as promised | ⛔ FD-01 | ❌ FD-09 | ❌ FD-09 |

## JOURNAL

| Node | clean | catalogue | existing |
|---|---|---|---|
| Completed session listed («Свободная» / «По плану») + new context | ✅ | ✅ | ✅ |
| Open entry → detail with names | ? | sheet «Открыть / Отмена» ✅ | ❌ FD-16 («Упражнение»), ❌ FD-14 (no edit/clone/delete) |
| Backdate activity («Другую активность») + reload | ? | ? | ✅ |
| Edit activity (rating/comment) | ? | ? | ✅ (FD-24 duration not editable) |
| Clone activity | ? | ? | ❌ FD-15 |
| Delete activity → Аналитика −1 | ? | ? | ✅ |
| Legacy workout edit + reload | n/a | n/a | ✅ |
| Legacy workout delete | n/a | n/a | ✅ in Журнал / ❌ FD-13 in Аналитика |
| Backfilled elective card | n/a | n/a | ✅ visible (❌ FD-26 «Подходы 1») |
| Title stable after the plan row is removed | ❌ FD-12 | ❌ FD-12 | ? |
| «+ Записать → Тренировку из моих» with 0 workouts | ? | ? | ? |
| Backdate a pull-up course workout | ? | ? | ⛔ no v2 path for a plan course; legacy BackdateForm ? |

## ANALYTICS

| Node | clean | catalogue | existing |
|---|---|---|---|
| Counters reflect a new session | ✅ (FD-19 «user») | ✅ (FD-19 «pull_ups», «block_a 0.5») | ✅ |
| Recompute on delete | ? | ? | ✅ activity / ❌ FD-13 legacy |
| Per-exercise panel | ✅ «Подтягивания 14 повторений» | ✅ | ? |
| CSV export | ? (button visible) | ? | ? |

## SUBSCRIPTION

| Node | clean | catalogue | existing |
|---|---|---|---|
| Trial user trains | ✅ | ✅ | ✅ (rested) / ❌ FD-18 too-early UX |
| Paid (Stars) user trains | n/a | n/a | ✅ |
| Expired: course «Начать» → subscription screen (§14) | ⛔ FD-01 (no course) | ? | ❌ FD-05 (starts and completes) |
| Expired: free/custom workout allowed (§14) | ✅ (allowed) | ? | ? |
| Expired: status shown correctly | ❌ FD-11 (stale «пробный период (осталось 0 дн.)») | ? | ❌ FD-11 |
| Expired: pay action reachable from the Mini App | ❌ FD-11 («Оплата картой временно недоступна.», no button) | ? | ❌ FD-11 (banner says «в боте», no link) |
| Admin grant (bot handler) → banner gone, state kept, trains | n/a | n/a | ✅ |

## PERSISTENCE

| Node | clean | catalogue | existing |
|---|---|---|---|
| Onboarding resumes after reload | ✅ | ✅ | n/a |
| Workouts / exercises / protocol after reload | ✅ | ✅ | ? |
| Plan rows (manual / moved / copied), weeks after reload | ✅ | ✅ | ✅ |
| First add-to-plan row ever visible | ❌ FD-02 (stored, invisible) | ❌ FD-02 | n/a |
| Course inclusion and removal persist | ⛔ FD-01 | ✅ | ✅ |
| Finished session in Журнал across contexts | ✅ | ✅ | ✅ |
| User exercise only after confirm | ❌ FD-23 | ? | ? |

## Blocked-node summary

- **clean**: the program path (A2–A6), course removal and course E11 are ⛔ BLOCKED BY FD-01. Subscription "course gated" is ⛔ FD-01.
- **catalogue**: nothing is fully blocked. Failing nodes: FD-02, FD-04, FD-07, FD-08, FD-09, FD-12, FD-16.
- **existing**: nothing is blocked. Failing nodes: FD-05, FD-09, FD-10, FD-11, FD-13, FD-14, FD-15, FD-18.
