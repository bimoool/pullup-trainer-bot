# TRACE — B-fresh-catalog (times UTC 2026-10-05; full raw event logs: `artifacts/{onb,j1,j2,j3,j4,j8,empty,search,dark}.log`)

Environment: DB `pullup_audit_d` = migrations + SYSTEM CONTENT (1 program «Подтягивания», 8 exercises, 3 protocols, empty collection; see PROFILES.md). Viewport 390×844, light. Auth: signed initData, `BOT_TOKEN=audit-token`.

## Onboarding through the UI (profile audit_fresh_active, tg 7200001)  — PASS
```
06:01:39 OPEN /                 VISIBLE «Привет, Audit! | Замер | … | Далее»                      OK (new user starts in onboarding)
06:01:55 TAP Далее (8) → «Всё верно? | Записал: 8 повторений»                                   OK
06:02:07 TAP Да → POST /api/onboarding/baseline 200 → «Уровень зафиксирован … 5 коротких вопросов»
         (reload before «Да» → returns to «Замер»; after «Да» a reopen skips straight to «Анкета Шаг 1 из 5»)
06:03:37 questionnaire Вес 78 → Рост 180 → Пол (native <select>) → Дата рождения → Часовой пояс → «Готово» → POST /api/onboarding/questionnaire 200
06:03:38 VISIBLE Home «Что потренируем сегодня? … Подтягивания … Своя программа … Мои тренировки … Создать тренировку …»   OK
06:03:40 RELOAD → same Home                                                                       OK
```
No e2e_seed injection needed.

## JOURNEY J1 — Zero-to-Workout   PROFILE audit_fresh_active (tg 7200001)   START STATE S0: onboarded, trial, no plan, no workouts   — PASS (with F-02, F-04, F-14 side findings)
```
06:03:50 OPEN Планы (tab)        EXPECT empty-state   ACTUAL «Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной»   OK (E1)
06:03:51 TAP card «Подтягивания" EXPECT Program Detail ACTUAL «PULL_UPS | Подтягивания | … | РАСПИСАНИЕ НЕДЕЛИ | База | Блок A — 3 раза в неделю (старт: 10 повт. × 3 подх.) | Блок Б — 3 раза в неделю (старт: 3 повт. × 4 подх.) | Добавить в план»  OK (F-05 slug, F-14)
06:03:59 TAP «Добавить в план»   POST /api/v2/program-inclusions 200   ACTUAL button → «В плане»   OK
         DOMAIN: training_plans 1, program_inclusions 1, plan_weeks 1 (5 окт), plan_items 2 (block A ×3, block B ×3, plan_week_id=1)
06:04:06 OPEN Планы   EXPECT active plan, current week, >=1 actionable workout
         ACTUAL «Подтягивания | На этой неделе: 0 из 3 | Неделя 1 · 5 окт – 11 окт | База | Текущая неделя · 0 из 3 | СВОБОДНЫЙ ПУЛ | Подтягивания 0/3 | Начать»   OK
06:04:08 RELOAD → app returns to Home (tab not persisted), Home card now «В плане»; Планы again shows the same row   OK
06:04:18 TAP «Начать» → «ГОТОВЫ К СТАРТУ | Подтягивания | ЦЕЛЬ 1: 10 ПОВТОРЕНИЙ | 3 рабочих подхода · собственный вес | ЦЕЛЬ 2: 3 ПОВТОРЕНИЙ | 4 рабочих подхода · собственный вес | Начать»   OK
06:04:28 TAP «Начать» → POST /api/v2/sessions/live 200 → Live «1 / 3 … Подход 1/3 · Цель: 10 повт. | ПРИГОТОВЬСЯ 0:05 | Готов | Пауза»   OK
06:04:37 RELOAD mid-Live → identical Live state                                                  OK (J8)
06:04:43 TAP «Готов» → «ПОШЁЛ … ВНЕСТИ ПОДХОД | Повторений | Готово»
06:04:51 set1 reps=8 → /phase/next + /sets:batch 200 → «ОТДЫХ 1:30 | Подход 1: 8 повт. | Пропустить отдых»; RELOAD → «ОТДЫХ 1:28» same        OK
06:05:04 set2 reps=8; 06:05:06 set3 reps=7 → block switch «1 / 1 … Цель: 3 повт.»; 06:05:08 set4 reps=3
06:05:09 ACTUAL «ГОТОВО | Все подходы плана выполнены — можно завершить сессию. | Завершить | + Ещё подход»
         EXPECT 4 sets in strength block   ACTUAL 1                                              FAIL F-02 (not blocking)
06:05:24 TAP «Завершить» → «Как прошла тренировка? 1–5, Заметка»; RPE «3 Средне» → «Сохранить и завершить» → POST …/complete 200
06:05:33 ACTUAL «Тренировка завершена | Подтягивания | 4 Подходов | 2 Упражнений | — 3/3 , выполнено | Подход 1: 8 повт. … | — 1/1 , выполнено | Новая цель 10 → 10 | 3 → 3 | Закрыть»   FAIL F-04 (blank names)
06:05:35 RELOAD → Home                                                                           OK
06:05:45 Журнал: «Пн, 5 октября | По плану | Подтягивания | 09:04 | Подходы 4 | Повторы 26 | Усилие 3»   OK (8+8+7+3=26)
06:05:46 Аналитика: «1 Тренировок за 30 дней … pull_ups 1 · 100% … block_a 0.5 / block_b 0.5»   OK (F-05 slugs)
06:05:47 Планы: «На этой неделе: 1 из 3 … Подтягивания 1/3 Начать»                              OK
06:05:57 NEW BROWSER CONTEXT same initData → Журнал entry still present; tapping it opens sheet «Открыть | Отмена»    OK
```
DOMAIN after: training_sessions 1 completed (source=plan); set_logs 4 rows (8,8,7,3).

J1 «every program» table: only one program (F-03).
| Program | add → week 1 rows | week 2+ |
|---|---|---|
| Подтягивания | 1 pool row (0/3) | 0 rows (F-08) |

## JOURNEY J2 — Custom workout from nothing   PROFILE audit_fresh_active (tg 7200002)   S0: onboarded, no plan, no workouts   — PASS for create/start/complete; plan step FAIL F-01 on first add
```
06:06:15 TAP «Создать тренировку» → «Новая тренировка | НАЗВАНИЕ | Сначала название… | Создать и добавить упражнения»
06:06:22 name «Моя тренировка спины» → POST /api/v2/workouts 200 → «Редактировать тренировку … Пока пусто. Добавьте первое упражнение… | + Добавить упражнение | Добавить в план | Дублировать | Сохранить | Удалить тренировку»   OK (E6)
06:06:47 + Добавить упражнение → library: Факультатив ×4, Планка, Отжимания (F-11)
06:06:58 search «подтягивания» → 3 «Факультатив…» + «Создать своё: «подтягивания»»
06:07:00 search «Австралийские подтягивания» → «Ничего не найдено | Создать своё: «Австралийские подтягивания» +»   OK create path exists
06:07:11 TAP Создать своё → POST /api/v2/exercises 200 → protocol sheet «Повторения | Время | Максимум | Интервалы … Подходы 3, Повторения 10, Отдых 1:00»
06:07:35 reps 8, Добавить → «УПРАЖНЕНИЯ · 1 | Австралийские подтягивания | 3 × 8 повторений | Отдых между подходами 1:00»; Сохранить → PATCH 200 → detail
06:07:38 RELOAD → Home «Моя тренировка спины | 1 упражнение · 3 × 8»                              OK
06:07:48 open → «Начать» → «ГОТОВЫ К СТАРТУ | … 3 × 8 повторений» → Начать → Live → sets 8,7,6 → Завершить → RPE → summary
06:08:13 «Тренировка завершена | Моя тренировка спины | 3 Подходов | 1 Упражнение | Австралийские подтягивания — 3/3 , выполнено …»   OK
06:08:15 Журнал «Свободная | Моя тренировка спины | 09:07 | Подходы 3 | Повторы 21 | Усилие 3»; RELOAD same   OK
06:08:16 Аналитика «user 1 · 100%», minutes 0, exercise block «Австралийские подтягивания 21 повторений…»   OK (F-05, F-06)
06:08:35 «Добавить в план» → Ср → «Добавить» → POST /api/v2/plan-items 200
         EXPECT row in Планы   ACTUAL «Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано.»  (also after RELOAD)   FAIL F-01
         DOMAIN (after failure): plan_items id3 plan_week_id NULL, day_of_week 2, complex_id 1
06:09:09 2nd «Добавить в план» → Ср → ACTUAL «Текущая неделя · 0 из 1 | СРЕДА | Моя тренировка спины | 0/1 | Начать» (RELOAD same)   OK
06:09:21 Планы → Начать (plan row) → complete (9,8,7) → summary «Прогрессия не пересчитана — нет активного курса со ступенчатой стратегией для этих упражнений.»
06:09:37 Планы «Текущая неделя · 1 из 1 | СРЕДА | Моя тренировка спины | 1/1 | Ещё раз»; Журнал «По плану | … 09:09» + «Свободная | … 09:07»   OK
```

## JOURNEY J3 — Free workout without plan   PROFILE audit_fresh_active (tg 7200002; same free run as J2 06:07:48)   — PASS
Workout Detail → Начать → pre-session → Live → 3 sets → complete → Журнал «Свободная» → Аналитика: see J2. Empty-workout variant (tg 7200002 «Пустая»):
```
06:09:50 Detail «Пустая | Своя тренировка | Пока без упражнений | Начать | Записать | Добавить в план | Изменить»
         TAP «Начать»  EXPECT start or explanation   ACTUAL button disabled (data-testid workout-detail-start), no text        FAIL F-07 (P3)
06:10:08 «Добавить в план»(Свободный пул) → 422 «У выбранной тренировки нет упражнений» shown in sheet    (guard OK, late)
```

## JOURNEY J4 — Plan lifecycle   PROFILE audit_fresh_active (tg 7200001 after J1)   — PASS with F-08/F-09/F-12
```
06:10:34 TAP › (next week, from last week) → POST /api/v2/plan/weeks 200 → «Неделя 2 · 12 окт – 18 окт | 0 из 0 | На эту неделю пока ничего не запланировано. | + Добавить упражнение»   FAIL F-08 (plan exists, week has 0 workouts)
06:11:17 Действия: Текущий план → «Скопировать неделю 1 → 2» → confirm «Скопировать» → POST …/copy-to-next 200 → «Скопировано: 0, пропущено дублей: 0»
06:11:19 TAP › → creates «Неделя 3», later «Неделя 4» (F-09); persists after reload
06:11:40 + Добавить упражнение → sheet (6 exercises + День) → Планка, Среда → «Текущая неделя · 1 из 4 | СРЕДА | Планка | 0/1 | Начать | СВОБОДНЫЙ ПУЛ …» ; RELOAD same   OK
06:12:12 Действия: Планка → Перенести → Неделя 2, Пт → PATCH /plan-items/5 200 → disappears from week 1; week 2 «ПЯТНИЦА | Планка | 0/1» (RELOAD same)   OK
06:12:30 copy week 2→3 → «Скопировано: 1, пропущено дублей: 0»; week 3 shows Планка; prev/next navigation OK
06:12:50 add Планка Понедельник → Начать → pre «ГОТОВЫ К СТАРТУ | Планка | Начать» → Live «Планка | 1/3 | 3 подхода», input «Секунды», set 40 с → rest
06:14:04 Планы «СЕГОДНЯ | Планка | 1/1 | Ещё раз» after a 1-of-3-sets run (F-12)
06:14:24 Убрать из плана (inline confirm «Убрать «Планка» из плана?») → DELETE 204; RELOAD gone   OK
06:14:39 Действия: Подтягивания → «Убрать курс из плана» → «Убрать курс «Подтягивания» из плана? История сохранится.» → POST …/deactivate 200
06:14:40 Планы «Курсов в плане нет … Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано.»  (plan without program, week 0 rows)   OK
06:14:44 Журнал: both sessions still listed (Планка titled «Тренировка», F-06); Аналитика still 2 trainings; Home program card back to «Добавить в план» state   OK (history/templates not deleted)
06:14:56 Планы → Завершённые: «Подтягивания | 5 окт 2026 – 5 окт 2026»                            OK
06:15:00 re-add program → «0 из 3» again (F-12)
```

## JOURNEY J7 — Persistence   — PASS
Reload / new context / navigate away-back verified for: onboarding (reload → Home), program inclusion + pool row, live session phase/timer/set, finished session in Журнал (new browser context), custom workout (name, exercise, protocol 3×8), user exercise (re-appears in picker), plan items (manual, moved, copied), weeks (2, 3, 4), program removal. FAIL only for F-01 orphan item (never visible).

## JOURNEY J8 — Live resilience (tg 7200001, session 4, Планка)   — PASS (BackButton UNTESTED)
```
06:13:13 OFFLINE ON, Секунды 40 → Готово → «Нет сети — подходы сохраняются локально и уйдут батчем при подключении. | ОТДЫХ 1:30 | Подход 1: 0:40»
06:13:17 OFFLINE OFF → POST phase/next 200, POST sets:batch 200 → state unchanged, set_logs row value 40 time    OK
06:13:25 RELOAD mid-rest → «ОТДЫХ 1:23 | Подход 1: 0:40»                                          OK
06:13:34 browser back → about:blank (harness: no SPA history). Telegram BackButton during Live: UNTESTED
06:13:54 double-tap «Сохранить и завершить» → single POST …/complete 200 → «Планка — 1/3 , не выполнено»; DB session 4 completed once   OK
```

## Empty-state matrix: see EMPTY_STATES.md.
