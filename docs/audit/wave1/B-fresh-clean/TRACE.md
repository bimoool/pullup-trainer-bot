# TRACE — B-fresh-clean (pure clean install)

Env: uvicorn :8091, DB `pullup_audit_b` (alembic head only), Redis db 1, viewport 390x844 (iPhone-like), light theme (dark only in the empty-state pass), `BOT_TOKEN=audit-token`.
Raw machine logs: `artifacts/trace-*.log` (identical lines, un-collapsed), screenshots `artifacts/*.png`, Playwright traces `artifacts/pw/*/trace.zip` (Playwright wipes the output dir per invocation, so only the last invocation per spec is retained: J4 and J6 here; J1/J2/empty-state evidence is the trace logs + screenshots).
Timestamps are the VM clock at execution time. ACTUAL = visible text of the screen (innerText with " | " between blocks, cut at 700 chars; full text is in the screenshot).
`OK` / `FAIL F-...` closes each EXPECT/ACTUAL pair; an EXPECT/ACTUAL pair without a marker is a purely informational snapshot (counted OK where it carries no verdict).
RELOAD = `page.reload()`; "REOPEN in new context" = a brand-new browser context with the same signed initData (J7).
Code was read only after a FAIL (DIAG: lines).
Why some specs were re-run: the shared VM runs other agents' playwright/chromium; two of my runs were killed from outside ("Target page, context or browser has been closed") and the DB was reset (scripts/audit/b_fresh_clean_reset.py) between runs. J2 was re-run on a new user (tg 7100072, `AUDIT_UID_OFFSET=60`); the final browser binary is a renamed copy of the same Chromium 1194 (`/tmp/bfc/chrome-linux/bfcbrowser`) so it is not hit by other agents' `pkill chrome`. No behavioural difference.

Summary of verdicts

| Journey | Verdict | First failing step |
|---|---|---|
| J1 Zero-to-Workout | **BLOCKED / FAIL** | Home: "Каталог курсов появится здесь позже." (no program to discover) -> F-01; Планы CTA loops -> F-02 |
| J2 Custom workout from nothing | **PASS to first run; FAIL at the plan step** | "Добавить в план" from nothing: item lost (F-03); also picker CTA hidden until typing (F-04) |
| J3 Free workout without plan | **PASS** (reachable only through J2's custom workout: no system workout exists) | — |
| J4 Plan lifecycle from empty | **FAIL** (add program BLOCKED BY F-01) | empty Планы CTA loop (F-02); first add-to-plan lost (F-03) |
| J6 expired part | **FAIL** (no paywall; no crash) | Subscription screen shows stale "пробный период", no pay CTA; all tabs usable (F-05, F-08) |
| J7 Persistence | **PASS** for everything that was created (see J2) except F-03 / F-06 | — |
| Empty-state matrix | see `EMPTY_STATES.md` | E1 FAIL, E9 FAIL, E10 BLOCKED |

## JOURNEY J1 — Zero-to-Workout   PROFILE audit_fresh_active (tg 7100011)
START STATE S0: DB = alembic head only (0 users, 0 programs, 0 exercises, 0 workouts); new Telegram user, no row.
```
06:40:19 OPEN Mini App (new user)
06:40:19 UI ONBOARDING (no injection): TAP "Далее" > "Да" > "Продолжить" > "Далее" > "Далее" > "Далее" > "Далее" > "Готово"  [baseline 'Замер' -> 'Да' -> 'Продолжить' -> анкета 5 шагов -> 'Готово']
06:40:29 EXPECT Home after onboarding (UI onboarding possible)
06:40:29 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Соберите свою тренировку из упражнений и протоколов. | Создать тренировку | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:40:29 OPEN Home -> look for a program to discover
06:40:29 EXPECT Home shows >=1 program card in the catalogue
06:40:29 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Соберите свою тренировку из упражнений и протоколов. | Создать тренировку | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-01 (empty catalogue)
06:40:29 TAP "Планы"
06:40:30 EXPECT Планы: active plan, current week, >=1 workout
06:40:30 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-02
06:40:30 TAP "Выбрать курс на Главной"
06:40:31 EXPECT CTA 'Выбрать курс на Главной' leads to a course to choose
06:40:31 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Соберите свою тренировку из упражнений и протоколов. | Создать тренировку | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-02
06:40:31 TAP "Баннер: открыть план дня"
06:40:32 EXPECT 'Откройте план дня' opens a day plan with a workout
06:40:32 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-02
06:40:32 RELOAD after dead-end loop
06:40:34 J1 steps 4..N (Program Detail, add program, Start, Live, Finish, Журнал, Аналитика, reopen): BLOCKED BY F-B-FRESH-CLEAN-01
06:40:34 SUMMARY FAIL ["F-B-FRESH-CLEAN-01 (empty catalogue): Home shows >=1 program card in the catalogue","F-B-FRESH-CLEAN-02: Планы: active plan, current week, >=1 workout","F-B-FRESH-CLEAN-02: CTA 'Выбрать курс на Главной' leads to a course to choose","F-B-FRESH-CLEAN-02: 'Откройте план дня' opens a day plan with a workout"]
```
VISIBLE STATE at the end: Планы "Курсов в плане нет. Добавьте курс на Главной." ; Home "Каталог курсов появится здесь позже."
DOMAIN STATE (read-only SQL after FAIL): programs=0, exercises=0, complexes=0, program_items=0; user has subscription trial (14 d) and 0 plans/sessions.
DIAG: `webapp-frontend/src/HomeScreen.tsx:420` renders that text when `catalog.programs.length === 0`; `webapp-frontend/src/DashboardScreen.tsx:863` renders "Выбрать курс на Главной" with a handler that only switches to Home. Nothing in migrations inserts programs (`alembic upgrade head` ships only 3 assessment_protocols and 1 collections row).
J1 steps after "discover a program" (Program Detail, add/start, Планы active plan, Live, Finish, Журнал, Аналитика, reopen): **BLOCKED BY F-B-FRESH-CLEAN-01**. Same flow through a custom workout is exercised in J2/J3.

## JOURNEY J2 (+J3, J7) — Custom workout from nothing, run it, plan it   PROFILE audit_empty_library (tg 7100072; first attempt 7100012 gave the same results)
START STATE S0: clean install, brand-new user, library empty (0 exercises), 0 workouts, no plan.
```
06:43:58 OPEN Mini App (new user)
06:43:58 UI ONBOARDING (no injection): TAP "Далее" > "Да" > "Продолжить" > "Далее" > "Далее" > "Далее" > "Далее" > "Готово"  [baseline 'Замер' -> 'Да' -> 'Продолжить' -> анкета 5 шагов -> 'Готово']
06:44:07 EXPECT Home after onboarding (UI onboarding possible)
06:44:07 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Соберите свою тренировку из упражнений и протоколов. | Создать тренировку | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:44:07 TAP "Баннер: собрать свой комплекс"
06:44:08 TAP "Создать и добавить упражнения"
06:44:09 EXPECT Editor 'Редактировать тренировку' with empty list and a way forward
06:44:09 ACTUAL Привет, Audit! | Редактировать тренировку | НАЗВАНИЕ | УПРАЖНЕНИЯ | Пока пусто. Добавьте первое упражнение и настройте, как его выполнять. | + Добавить упражнение | Добавить в план | Дублировать | Сохранить | Удалить тренировку   OK
06:44:10 TAP "+ Добавить упражнение"
06:44:11 EXPECT Exercise picker on empty library offers a visible 'create exercise' CTA without typing
06:44:11 ACTUAL Привет, Audit! | Добавить упражнение | Выберите упражнение — на следующем шаге настроите подходы и отдых. Нет нужного? Введите название, и появится «Создать своё». | Ничего не найдено   FAIL F-B-FRESH-CLEAN-04 (CTA only after typing; hint text only)
06:44:12 TAP "Создать своё: «Подтягивания»"
06:44:13 EXPECT Protocol screen (type/sets/reps/rest)
06:44:13 ACTUAL Привет, Audit! | УПРАЖНЕНИЕ | Подтягивания | ТИП РАБОТЫ | Повторения | Несколько подходов с заданным количеством повторений | Время | Несколько подходов на время | Максимум | Несколько попыток на максимум | Интервалы | Работа и отдых по таймеру | ПАРАМЕТРЫ | Подходы | Сколько раз повторить | − | + | Повторения в подходе | Одинаково в каждом подходе | − | + | Отдых между подходами | − | + | мин:сек | ТАК БУДЕТ В ТРЕНИРОВКЕ | 3 × 10 повторений | Отдых между подходами 1:00 | Добавить | Отмена   OK
06:44:13 TAP "Добавить"
06:44:14 TAP "Сохранить"
06:44:15 EXPECT Workout detail with 1 exercise, 3 × 10
06:44:15 ACTUAL Привет, Audit! | Мои подтягивания | Своя тренировка | 1 упражнение | Начать | Записать | Добавить в план | Изменить | Упражнения | Подтягивания | 3 × 10 повторений · отдых 1:00 | История | Вы ещё не выполняли эту тренировку   OK
06:44:15 RELOAD after save
06:44:17 EXPECT Home 'Мои тренировки' lists the workout after reload
06:44:17 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Создать | Мои подтягивания | 1 упражнение · 3 × 10 | Подтягивания | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:44:17 TAP "workout card"
06:44:18 TAP "Начать"
06:44:19 EXPECT Live ready screen
06:44:19 ACTUAL ГОТОВЫ К СТАРТУ | Мои подтягивания | 1 упражнение | Подтягивания | 3 × 10 повторений | Начать   OK
06:44:19 TAP "Начать (live)"
06:44:20 TAP "Готов"
06:44:21 TAP "Готово (8)"
06:44:22 EXPECT Rest phase with 'Подход 1: 8 повт.'
06:44:22 ACTUAL ЖИВАЯ ТРЕНИРОВКА | Мои подтягивания | Завершить | Подтягивания | 1 / 3 | ПОДХОД | 10 | ПОВТ | Подход 1/3 · Цель: 10 повт. | ОТДЫХ | 1:00 | Подход 1: 8 повт. | Изменить | Пропустить отдых | Пауза   OK
06:44:23 RELOAD mid-session (J7)
06:44:25 EXPECT Live session resumes after reload (rest)
06:44:25 ACTUAL ЖИВАЯ ТРЕНИРОВКА | Мои подтягивания | Завершить | Подтягивания | 1 / 3 | ПОДХОД | 10 | ПОВТ | Подход 1/3 · Цель: 10 повт. | ОТДЫХ | 0:57 | Подход 1: 8 повт. | Изменить | Пропустить отдых | Пауза   OK
06:44:25 TAP "Пропустить отдых"
06:44:26 TAP "Готов"
06:44:27 TAP "Готово (6)"
06:44:28 TAP "Завершить"
06:44:29 TAP "3 Средне"
06:44:30 TAP "Сохранить и завершить"
06:44:31 EXPECT Summary 'Тренировка завершена' with sets 8 and 6
06:44:31 ACTUAL Тренировка завершена | Мои подтягивания | 2 | Подходов | 1 | Упражнение | Подтягивания — 2/3 | , не выполнено | Подход 1: 8 повт. | Подход 2: 6 повт. | Закрыть   OK
06:44:31 RELOAD after summary
06:44:33 TAP "Журнал"
06:44:34 EXPECT Журнал shows the workout (Свободная, 2 sets, 14 reps)
06:44:34 ACTUAL Привет, Audit! | Журнал | + Записать | ‹ | Октябрь 2026 | › | 5–11 ОКТ. | Пн, 5 октября | Свободная | Мои подтягивания | 09:44 | Подходы | 2 | Повторы | 14 | Усилие | 3 | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:44:34 TAP "Аналитика"
06:44:35 EXPECT Аналитика: 1 тренировка, 14 повторений
06:44:35 ACTUAL Привет, Audit! | Аналитика | Тренировки | Программа | Тренировки | Минуты | 1 мес | 3 мес | Свой | 1 | Тренировок за 30 дней | 1 | Активных дней за 30 дней | По типам | 1 | всего | user | 1 · 100% | Тренировки по неделям | 31.08 | 07.09 | 14.09 | 21.09 | 28.09 | 1 | 05.10 | Всего тренировок: 1 · 06.09 – 05.10 | Сводка | Тип	Тренировки	Минуты | user	1	0 | Итого	1	0 | Смешанная тренировка делится между категориями поровну по блокам; минуты — по длительности тренировки. | Упражнение | Подтягивания | Повторения | 14 | Всего повторений | 2 | Подходов | 8 | Лучший подход | Повторений по тренировкам | Для графика нужно хотя бы две записи. | Экспорт данных — CSV | Вся история тренировок: по строке н   OK
06:44:38 REOPEN in new context, same initData
06:44:38 TAP "Журнал"
06:44:39 EXPECT Журнал still has the workout in a fresh context (J7)
06:44:39 ACTUAL Привет, Audit! | Журнал | + Записать | ‹ | Октябрь 2026 | › | 5–11 ОКТ. | Пн, 5 октября | Свободная | Мои подтягивания | 09:44 | Подходы | 2 | Повторы | 14 | Усилие | 3 | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:44:39 TAP "Планы"
06:44:40 TAP "Мои тренировки"
06:44:41 TAP "Добавить в план"
06:44:42 TAP "Ср"
06:44:43 TAP "Добавить"
06:44:44 RELOAD after add-to-plan
06:44:46 TAP "Планы"
06:44:48 EXPECT Планы current week shows the added workout (Среда)
06:44:48 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано. | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-03 (first add-to-plan when no plan exists is silently lost)
06:44:48 TAP "Мои тренировки"
06:44:49 TAP "Добавить в план (retry)"
06:44:50 TAP "Чт"
06:44:51 TAP "Добавить"
06:44:51 RELOAD after 2nd add
06:44:54 TAP "Планы"
06:44:55 EXPECT Планы shows the workout under ЧЕТВЕРГ after the 2nd add
06:44:55 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 1 | ЧЕТВЕРГ | Мои подтягивания | 0/1 | Начать | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:44:55 TAP "Начать (plan)"
06:44:56 TAP "Начать"
06:44:57 TAP "Готов"
06:44:58 TAP "Готово (9)"
06:44:59 TAP "Пропустить отдых"
06:45:00 TAP "Готов"
06:45:01 TAP "Готово (7)"
06:45:02 TAP "Завершить"
06:45:03 TAP "4 Тяжело"
06:45:04 TAP "Сохранить и завершить"
06:45:05 EXPECT Summary after plan start
06:45:05 ACTUAL Тренировка завершена | Мои подтягивания | 2 | Подходов | 1 | Упражнение | Подтягивания — 2/3 | , не выполнено | Подход 1: 9 повт. | Подход 2: 7 повт. | Прогрессия не пересчитана — нет активного курса со ступенчатой стратегией для этих упражнений. | Закрыть   OK
06:45:05 TAP "Закрыть"
06:45:06 RELOAD 
06:45:08 TAP "Планы"
06:45:09 EXPECT Планы shows 1/1 for the week item after completion
06:45:09 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 1 из 1 | ЧЕТВЕРГ | Мои подтягивания | 1/1 | Ещё раз | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:45:09 TAP "Журнал"
06:45:10 EXPECT Журнал shows 'По плану' entry
06:45:10 ACTUAL Привет, Audit! | Журнал | + Записать | ‹ | Октябрь 2026 | › | 5–11 ОКТ. | Пн, 5 октября | По плану | Мои подтягивания | 09:44 | Подходы | 2 | Повторы | 16 | Усилие | 4 | Свободная | Мои подтягивания | 09:44 | Подходы | 2 | Повторы | 14 | Усилие | 3 | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:45:10 TAP "Планы"
06:45:11 TAP "Действия"
06:45:12 TAP "Убрать из плана"
06:45:13 TAP "Убрать"
06:45:14 RELOAD 
06:45:16 TAP "Журнал"
06:45:17 EXPECT Журнал still names the plan-run entry 'Мои подтягивания' after the plan row was removed
06:45:17 ACTUAL Привет, Audit! | Журнал | + Записать | ‹ | Октябрь 2026 | › | 5–11 ОКТ. | Пн, 5 октября | По плану | Тренировка | 09:44 | Подходы | 2 | Повторы | 16 | Усилие | 4 | Свободная | Мои подтягивания | 09:44 | Подходы | 2 | Повторы | 14 | Усилие | 3 | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-06
06:45:18 SUMMARY FAIL ["F-B-FRESH-CLEAN-04 (CTA only after typing; hint text only): Exercise picker on empty library offers a visible 'create exercise' CTA without typing","F-B-FRESH-CLEAN-03 (first add-to-plan when no plan exists is silently lost): Планы current week shows the added workout (Среда)","F-B-FRESH-CLEAN-06: Журнал still names the plan-run entry 'Мои подтягивания' after the plan row was removed"]
```
Domain state after the run (read-only SQL): training_sessions=2 (1 free, 1 from plan item) for the earlier identical user 7100012; `plan_items` row for the user: `day_of_week=2, plan_week_id=NULL` (orphan, see F-03); the second plan item (Чт) had `plan_week_id=<week 1>` and was removed at the end.
DIAG (after FAIL): F-03 -> `webapp-frontend/src/AddToPlanScreen.tsx:63-66` sends `plan_week_id: null` when `fetchPlan` returns no plan; `app/web/routes_v2.py:1025-1043` accepts null (`create_plan_item`, week-ownership check only if not None) and `app/web/routes_v2.py:834` (`GET /plan`) only later materialises week 1 (`ensure_current_plan_week`), the orphan row is never attached to it and the Планы list filters by `plan_week_id`. F-06 -> `app/db/repositories/training_plans.py:250` `delete_mutable_plan_item` (and the docstring at `app/web/routes_v2.py:1090` promise "Journal history не задеты"); `_resolve_session_titles` (`routes_v2.py:1104`) reads the title via `SessionPlanItem -> PlanItem`, so deleting the PlanItem drops the title.

## JOURNEY J4 — Plan lifecycle from empty   PROFILE audit_fresh_active (tg 7100014)
START STATE S0: clean install, new user, no plan, no workouts.
```
06:45:33 OPEN Mini App (new user)
06:45:33 UI ONBOARDING (no injection): TAP "Далее" > "Да" > "Продолжить" > "Далее" > "Далее" > "Далее" > "Далее" > "Готово"  [baseline 'Замер' -> 'Да' -> 'Продолжить' -> анкета 5 шагов -> 'Готово']
06:45:42 EXPECT Home after onboarding (UI onboarding possible)
06:45:42 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Соберите свою тренировку из упражнений и протоколов. | Создать тренировку | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:45:42 TAP "Планы"
06:45:43 EXPECT E1 empty Планы has a CTA that resolves (add program)
06:45:43 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-02
06:45:43 TAP "Главная"
06:45:44 TAP "Баннер: собрать свой комплекс"
06:45:45 TAP "Создать и добавить упражнения"
06:45:46 TAP "+ Добавить упражнение"
06:45:48 TAP "Создать своё"
06:45:49 TAP "Добавить"
06:45:50 TAP "Сохранить"
06:45:51 TAP "Добавить в план"
06:45:52 TAP "Пн"
06:45:53 TAP "Добавить"
06:45:54 RELOAD after first add-to-plan
06:45:56 TAP "Планы"
06:45:57 EXPECT Plan exists + current week created (rows: 0 workouts) — 'plan exists but current week has 0 workouts'
06:45:57 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано. | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:45:57 EXPECT The workout just added appears in current week
06:45:57 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано. | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-03
06:45:57 TAP "Мои тренировки"
06:45:58 TAP "Добавить в план"
06:45:59 TAP "Чт"
06:46:00 TAP "Добавить"
06:46:01 RELOAD 
06:46:04 TAP "Планы"
06:46:05 EXPECT Item under ЧЕТВЕРГ after reload
06:46:05 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 1 | ЧЕТВЕРГ | План-тест | 0/1 | Начать | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:05 TAP "Действия"
06:46:06 TAP "Перенести"
06:46:07 TAP "Пт"
06:46:08 TAP "Сохранить"
06:46:09 RELOAD 
06:46:11 TAP "Планы"
06:46:12 EXPECT Moved to ПЯТНИЦА after reload
06:46:12 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 1 | ПЯТНИЦА | План-тест | 0/1 | Начать | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:12 TAP "Действия"
06:46:13 TAP "Перенести"
06:46:14 TAP "Свободный пул"
06:46:15 TAP "Сохранить"
06:46:16 RELOAD 
06:46:18 TAP "Планы"
06:46:19 EXPECT Item in СВОБОДНЫЙ ПУЛ after reload
06:46:19 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 1 | СВОБОДНЫЙ ПУЛ | План-тест | 0/1 | Начать | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:19 TAP "Действия: Текущий план"
06:46:20 TAP "Скопировать неделю 1 → 2"
06:46:21 TAP "Скопировать"
06:46:22 EXPECT Week 2 holds the copy ('Скопировано: 1')
06:46:22 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 2 · 12 окт – 18 окт | База | › | 0 из 1 | СВОБОДНЫЙ ПУЛ | План-тест | 0/1 | + Добавить упражнение | Скопировано: 1, пропущено дублей: 0 | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:22 RELOAD 
06:46:25 TAP "Планы"
06:46:26 EXPECT Current-week indicator 'Текущая неделя' on week 1 after reload
06:46:26 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 1 · 5 окт – 11 окт | База | › | Текущая неделя · 0 из 1 | СВОБОДНЫЙ ПУЛ | План-тест | 0/1 | Начать | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:26 TAP "Следующая неделя"
06:46:27 EXPECT Week 2 persists with the copied row
06:46:27 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 2 · 12 окт – 18 окт | База | › | 0 из 1 | СВОБОДНЫЙ ПУЛ | План-тест | 0/1 | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:27 TAP "Следующая неделя"
06:46:28 EXPECT E11 newly created week 3 has an empty state with CTA
06:46:28 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | ‹ | Неделя 3 · 19 окт – 25 окт | База | › | 0 из 0 | На эту неделю пока ничего не запланировано. | + Добавить упражнение | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:28 TAP "Предыдущая неделя"
06:46:29 TAP "Предыдущая неделя"
06:46:30 TAP "Действия"
06:46:31 TAP "Убрать из плана"
06:46:32 TAP "Убрать"
06:46:33 RELOAD 
06:46:35 TAP "Главная"
06:46:36 EXPECT Template workout still exists on Home after removal from plan
06:46:36 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Создать | План-тест | 1 упражнение · 3 × 10 | Подтягивания | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:36 J4 'add program', 'program with no generated PlanItems', 'remove program': BLOCKED BY F-B-FRESH-CLEAN-01 (no programs exist)
06:46:36 SUMMARY FAIL ["F-B-FRESH-CLEAN-02: E1 empty Планы has a CTA that resolves (add program)","F-B-FRESH-CLEAN-03: The workout just added appears in current week"]
```
Domain state (read-only SQL): plan_items rows for this user: (id 5, day_of_week 0, plan_week_id NULL) = the orphan from the first add; (id 7, pool, week 4 = week 2 copy). The Monday item added first never reached week 1 (F-03). "Plan exists but current week has 0 workouts" was hit explicitly (06:28:55 "Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано.").
Not run (BLOCKED BY F-B-FRESH-CLEAN-01): add a program, week-created-from-program, rows generated from a program, "program with no generated PlanItems", remove a program. "Действия: Текущий план" menu only offers "Скопировать неделю 1 → 2" (no program removal exists without a program).
Observed through the UI (exploration, same code): "Убрать из плана" confirm text `Убрать «<title>» из плана?`; template workout survives (verified in the spec: Home still lists it); history entry keeps the session but loses its title (F-06).

## JOURNEY J6 (expired part) — PROFILE audit_fresh_expired (tg 7100015)
START STATE S0: UI onboarding (trial) as for audit_fresh_active, then **TEST HARNESS INJECTION / DOMAIN NECESSITY** (see line 'TEST HARNESS INJECTION' in the log). This is the only injection in the whole audit.
```
06:46:41 OPEN Mini App (new user)
06:46:41 UI ONBOARDING (no injection): TAP "Далее" > "Да" > "Продолжить" > "Далее" > "Далее" > "Далее" > "Далее" > "Готово"  [baseline 'Замер' -> 'Да' -> 'Продолжить' -> анкета 5 шагов -> 'Готово']
06:46:51 EXPECT Home after onboarding (UI onboarding possible)
06:46:51 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Соберите свою тренировку из упражнений и протоколов. | Создать тренировку | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   OK
06:46:51 TEST HARNESS INJECTION: UPDATE users SET subscription_expires_at=now()-interval '1 day' WHERE telegram_id=7100015
06:46:51 RELOAD after expiry injection
06:46:53 TAP "Профиль"
06:46:54 TAP "Подписка"
06:46:55 EXPECT Subscription screen says expired (not 'пробный период') right after expiry
06:46:55 ACTUAL Привет, Audit! | ← Профиль | Подписка | Статус | пробный период (осталось 0 дн., до 04.10.2026) | Оплата картой временно недоступна. | Стоимость подписки: 990 ₽ / месяц. Первые 14 дней — бесплатно. | Как оформить: оплата прямо в боте после пробного периода — картой через Робокассу или Telegram Stars. | Условия оказания услуги и возврата: услуга оказывается сразу после оплаты. Возврат за уже предоставленный доступ не производится. При технической ошибке платежа (двойное списание и т.п.) — полный возврат по обращению в поддержку. | Исполнитель: Возжаев Кирилл Эдуардович (ИП/самозанятый) | ИНН: 667354733620 | ОГРН/ОГРНИП: 324665800108241 | E-mail: kirillvozzhaev99@gmail.com | Полный текст оферт   FAIL F-B-FRESH-CLEAN-08 (stale subscription cache label)
06:46:55 EXPECT Subscription screen offers a way to pay
06:46:55 ACTUAL Привет, Audit! | ← Профиль | Подписка | Статус | пробный период (осталось 0 дн., до 04.10.2026) | Оплата картой временно недоступна. | Стоимость подписки: 990 ₽ / месяц. Первые 14 дней — бесплатно. | Как оформить: оплата прямо в боте после пробного периода — картой через Робокассу или Telegram Stars. | Условия оказания услуги и возврата: услуга оказывается сразу после оплаты. Возврат за уже предоставленный доступ не производится. При технической ошибке платежа (двойное списание и т.п.) — полный возврат по обращению в поддержку. | Исполнитель: Возжаев Кирилл Эдуардович (ИП/самозанятый) | ИНН: 667354733620 | ОГРН/ОГРНИП: 324665800108241 | E-mail: kirillvozzhaev99@gmail.com | Полный текст оферт   FAIL F-B-FRESH-CLEAN-05 (paywall)
06:46:57 TAP "Главная"
06:46:58 EXPECT Главная: paywall / no_access explanation visible for expired user
06:46:58 ACTUAL Привет, Audit! | Что потренируем сегодня? | Главная | Каталог курсов появится здесь позже. | Своя программа | Соберите комплекс из упражнений и протоколов | Мои тренировки | Соберите свою тренировку из упражнений и протоколов. | Создать тренировку | Занимались вне приложения? | Добавьте активность в историю | Нажмите  на тренировке, чтобы добавить | Готовы заниматься? | Откройте план дня | Тесты | Максимум, вис, вес — результаты и динамика › | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-05
06:47:00 TAP "Планы"
06:47:01 EXPECT Планы: paywall / no_access explanation visible for expired user
06:47:01 ACTUAL Привет, Audit! | Планы | Мои тренировки | Сейчас | Завершённые | Текущий план | Курсов в плане нет. Добавьте курс на Главной. | Выбрать курс на Главной | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-05
06:47:03 TAP "Журнал"
06:47:04 EXPECT Журнал: paywall / no_access explanation visible for expired user
06:47:04 ACTUAL Привет, Audit! | Журнал | + Записать | ‹ | Октябрь 2026 | › | В этом месяце тренировок нет | Главная | Планы | Журнал | Аналитика | Профиль   FAIL F-B-FRESH-CLEAN-05
06:47:05 TAP "Аналитика"
06:47:06 EXPECT Аналитика: paywall / no_access explanation visible for expired user
06:47:06 ACTUAL Привет, Audit! | Аналитика | Тренировки | Программа | Тренировки | Минуты | 1 мес | 3 мес | Свой | 0 | Тренировок за 30 дней | 0 | Активных дней за 30 дней | По типам | За выбранный период нет данных. | Тренировки по неделям | 31.08 | 07.09 | 14.09 | 21.09 | 28.09 | 05.10 | Всего тренировок: 0 · 06.09 – 05.10 | Сводка | Тип	Тренировки	Минуты | Итого	0	0 | Смешанная тренировка делится между категориями поровну по блокам; минуты — по длительности тренировки. | Пока нет завершённых тренировок из «Мои тренировки» — показатели по упражнениям появятся после первой. | Экспорт данных — CSV | Вся история тренировок: по строке на подход, открывается в Excel. | Скачать | Главная | Планы | Журнал | Анал   FAIL F-B-FRESH-CLEAN-05
06:47:08 TAP "Баннер: собрать свой комплекс"
06:47:09 EXPECT Expired user can still create a workout (no gate)
06:47:09 ACTUAL Привет, Audit! | Новая тренировка | НАЗВАНИЕ | Сначала название. Упражнения, подходы и отдых вы настроите на следующем шаге. | Создать и добавить упражнения   OK
06:47:09 SUMMARY FAIL ["F-B-FRESH-CLEAN-08 (stale subscription cache label): Subscription screen says expired (not 'пробный период') right after expiry","F-B-FRESH-CLEAN-05 (paywall): Subscription screen offers a way to pay","F-B-FRESH-CLEAN-05: Главная: paywall / no_access explanation visible for expired user","F-B-FRESH-CLEAN-05: Планы: paywall / no_access explanation visible for expired user","F-B-FRESH-CLEAN-05: Журнал: paywall / no_access explanation visible for expired user","F-B-FRESH-CLEAN-05: Аналитика: paywall / no_access explanation visible for expired user"]
```
DOMAIN STATE after the run: `users.subscription_status` flips to `expired` only on the next access check (`app/services/subscription.py:89 refresh_status`); `GET /api/profile` returned the stale cached trial label until then (exploration: tg 7100003 showed "пробный период (осталось 14 дн.)" after `UPDATE subscriptions ... status='expired'` because the Mini App reads the `users` cache columns, not the `subscriptions` table). After the flip the label is "истекла".
DIAG: `grep -rn "no_access"` -> only `app/web/routes.py:736/1711` (legacy `/api/plan`, backdate) and schemas; `/api/v2/*` routes (workouts, sessions/live, plan-items) have no `has_access` check, so an expired user can create and start workouts (exploration: tg 7100003 created a workout and reached Live).

## Empty-state pass (E1–E12), light and dark   PROFILE audit_empty_library (tg 7100016 light, 7100017 dark)
Verdicts and verbatim messages in `EMPTY_STATES.md`. Raw logs: `artifacts/trace-EMPTY-light.log`, `artifacts/trace-EMPTY-dark.log` (both PASS as scripts: they only snapshot).

## Exploration notes (not scripted, evidence in `artifacts/*.png` named by step)
Exploratory node scripts (`webapp-frontend/e2e/audit/B-fresh-clean/step.mjs` + `lib.mjs`) were used for step-by-step discovery before the specs were written (tg 7100001, 7100003, 7100020). Findings from them that the specs also cover or that complement them:
- Onboarding through the UI works end to end and resumes after reload: closing the app after "Уровень зафиксирован" re-opens at the questionnaire "Шаг 1 из 5".
- Live session persistence: reopen mid-session restores "ЖИВАЯ ТРЕНИРОВКА", set 1/3, remaining rest (0:50 after ~9 s away), "ГОТОВО Все подходы плана выполнены" state after the last set; "Завершить" -> effort sheet 1–5 -> summary with sets.
- Live from plan: "Начать: <title>, <день>" in Планы starts the session with `plan_item_ids`; after finishing 2 of 3 sets the summary says "Подтягивания — 2/3 , не выполнено" and "Прогрессия не пересчитана — нет активного курса со ступенчатой стратегией для этих упражнений." (F-10), Планы shows "1/1" and the button turns into "Ещё раз" (F-11).
- Журнал shows "По плану" / "Свободная" labels, sets, reps, effort; Аналитика counts them (shows raw category "user", F-09).
- Add-to-plan for a workout with zero exercises: 422 "У выбранной тренировки нет упражнений" shown inline (good).
- Plan item move day / free pool / copy week / next week creation / reload persistence: all PASS (J4 spec, steps 06:29:02-06:29:25).
- Tapping "Создать своё: «Подтягивания»" immediately does POST /api/v2/exercises (before the protocol sheet is confirmed); backing out leaves a user exercise in the library (F-13).
