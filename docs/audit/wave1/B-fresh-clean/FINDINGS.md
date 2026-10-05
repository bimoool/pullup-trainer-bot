# FINDINGS — B-fresh-clean (pure clean install, new Telegram users)

Role prefix `F-B-FRESH-CLEAN-NN` (short `F-NN` below). Baseline 523a930, DB = `alembic upgrade head` only.
Evidence base paths are under `docs/audit/wave1/B-fresh-clean/artifacts/`. Severity is a suggestion.

## Summary

| Id | Sev | Layer | One line |
|---|---|---|---|
| F-01 | P0 | missing system content | Clean install has 0 programs and 0 exercises: Home says "Каталог курсов появится здесь позже." — the product's main path (discover program -> add -> train) cannot start |
| F-02 | P0 | UX dead-end | Empty Планы CTA "Выбрать курс на Главной" and Home banner "Откройте план дня" loop between Планы and Главная with nothing to choose |
| F-03 | P0 | API/backend defect + frontend state defect | The FIRST "Добавить в план" from a user with no plan creates an orphan plan item (`plan_week_id=NULL`): success on screen, week stays "0 из 0", workout never appears (reproduces "plan with zero workouts") |
| F-04 | P2 | UX dead-end (soft) | On an empty library the exercise picker shows only "Ничего не найдено"; the "Создать своё" action appears only after typing a name (explained only in small hint text) |
| F-05 | P2 | subscription/auth defect (or valid domain difference — needs product decision) | An expired user sees no paywall/no_access anywhere in the Mini App and can still create and start workouts; Subscription screen has no pay button |
| F-06 | P2 | persistence defect | "Убрать из плана" deletes the PlanItem and cascades `session_plan_items`, so the already completed journal entry loses its title ("Мои подтягивания" -> "Тренировка") although the endpoint docstring promises journal history is untouched |
| F-07 | P3 | UX dead-end (soft) | Workout detail with zero exercises: "Начать" is disabled with no explanation and the empty text "В тренировке пока нет упражнений" has no CTA |
| F-08 | P3 | API/backend defect | Profile / Подписка shows a stale trial label after the trial ended ("пробный период (осталось 0 дн., до 04.10.2026)") until some other call refreshes the cache |
| F-09 | P3 | frontend state defect | Аналитика "По типам"/"Сводка" shows the raw category key "user" |
| F-10 | P3 | UX copy | Live summary for a free workout: "Прогрессия не пересчитана — нет активного курса со ступенчатой стратегией для этих упражнений." (internal jargon shown to a user without a course) |
| F-11 | P3 | UNKNOWN (domain question) | Plan item counted "1/1" and button "Ещё раз" after finishing 2 of 3 sets; summary said "не выполнено" and effort sheet "остальное останется в плане" |
| F-12 | P3 | UX copy | Планы card keeps "Курсов в плане нет. Добавьте курс на Главной." + dead CTA above a week that contains manual workouts |
| F-13 | P3 | persistence defect | Tapping "Создать своё: «X»" immediately persists a user exercise (POST /api/v2/exercises) before the protocol sheet is confirmed; "Отмена" leaves an orphan exercise in the library |
| F-14 | P3 | reference-only / harness | Harness env: `@playwright/test` 1.63 wants Chromium build 1243 but only 1194 is installed in `/opt/pw-browsers`; audit config therefore sets `executablePath` (not an app defect) |

Positive observations (PASS, evidence in TRACE): UI onboarding works and resumes after reload; custom-workout creation including "Создать своё" exercise; live session with rest/phase transitions, mid-session reload restores timer and logged sets; finish -> summary -> Журнал -> Аналитика; new browser context with the same initData sees the same data; add-to-plan once a plan exists, move day, free pool, copy week, next/prev week, current-week indicator; adding a zero-exercise workout to a plan is rejected with a readable message; "Записать" of an empty workout is rejected ("Введи хотя бы один подход").

---

### F-B-FRESH-CLEAN-01 — empty catalogue on a clean install (P0, missing system content)
- Journey/step: J1 step "Home -> discover a program".
- Expected: Home shows >=1 program card (e.g. "Подтягивания") to open Program Detail and add/start.
- Actual: Home: "Что потренируем сегодня?" ... "Каталог курсов появится здесь позже." then only "Своя программа", "Мои тренировки", "Занимались вне приложения?", "Готовы заниматься?", "Тесты". `GET /api/v2/programs` -> `{"programs":[]}`; `/api/v2/exercises` -> `{"exercises":[]}` (artifacts/api-programs.json, api-exercises.json).
- Evidence: `J1-home-catalogue.png`, `after-onb.png`, `trace-J1.log` (06:3x EXPECT/ACTUAL), `pw/j1_*/trace.zip`.
- Repro from S0: `alembic upgrade head` on empty DB; open Mini App as new user; finish onboarding; look at Главная.
- DIAG: `webapp-frontend/src/HomeScreen.tsx:420` renders the text when `catalog.programs.length === 0`; migrations insert no programs/exercises (read-only SQL: programs=0, exercises=0, complexes=0, program_items=0; only 3 assessment_protocols + 1 collections row exist). Catalogue content is created by scripts outside `alembic` (compare B-fresh-catalog).
- Likely layer: missing system content (the deploy/migration contract does not guarantee a catalogue). Consequence: J1, J4 "add program", E10 are BLOCKED on a clean install.

### F-B-FRESH-CLEAN-02 — circular empty-state CTAs (P0, UX dead-end)
- Journey/step: J1 / J4 / E1, "Планы" with no plan.
- Expected: CTA leads to something that can be chosen/added.
- Actual: Планы: "Текущий план | Курсов в плане нет. Добавьте курс на Главной." CTA "Выбрать курс на Главной" -> Главная -> "Каталог курсов появится здесь позже." (no card). Home banner "Откройте план дня" -> Планы (same message). Fully closed loop, three taps, no state change.
- Evidence: `J1-plans-empty.png`, `J1-cta-loop-home.png`, `J1-plan-of-day-loop.png`, `EMPTY-dark-E1.png`, `trace-J1.log` 06:21:27–06:21:30 (first run) and final run, `trace-J4.log` E1.
- Repro: S0 + onboarding, Планы -> "Выбрать курс на Главной" -> Баннер "Откройте план дня".
- DIAG: `webapp-frontend/src/DashboardScreen.tsx:863` (CTA only navigates to Home), `HomeScreen.tsx:420` (empty catalogue message). Root cause F-01; the CTA has no alternative ("Своя тренировка" / "Создать тренировку") for a user who has no catalogue.
- Layer: UX dead-end (root: missing system content).

### F-B-FRESH-CLEAN-03 — first add-to-plan is silently lost (P0, API/backend + frontend state)
- Journey/step: J2b / J4: Планы empty -> Мои тренировки -> "Добавить в план" -> Ср -> "Добавить" -> reload -> Планы.
- Expected: Планы shows the current week with the workout under "СРЕДА" ("Текущая неделя · 0 из 1").
- Actual: success (no error), after reload Планы shows "Неделя 1 · 5 окт – 11 окт | База | Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано." The workout is nowhere. Repeating the add (now a week exists) works and the item appears under "ЧЕТВЕРГ" — which hides the problem on the second try. The orphan row remains forever (not visible, not removable).
- Evidence: `J2-plan-after-add.png`, `J4-plan-exists-week-0.png`, `after-add-to-plan.png`, `trace-J2.log` 06:44-06:45 (EXPECT "...(Среда)" FAIL), `trace-J4.log` 06:28:55; API: `api-plan-orphan.json` (`"plan_week_id":null,"day_of_week":2`, `plan_weeks` has week 1 without it). Request body: `POST /api/v2/plan-items {"complex_id":2,"plan_week_id":null,"day_of_week":2,"count_per_week":1}` -> 200.
- Repro from S0: onboard; Главная -> Своя программа -> create "X" -> add an exercise -> Сохранить -> Добавить в план -> Ср -> Добавить -> reload -> Планы.
- DIAG: `webapp-frontend/src/AddToPlanScreen.tsx:63-66` sets `planWeekId` to null when `fetchPlan` returns `plan: null`; `app/web/routes_v2.py:1025-1043` `create_plan_item` accepts `plan_week_id=None` and creates the TrainingPlan (`get_or_create_for_user`) without attaching to the current week; `GET /plan` (`routes_v2.py:834`) creates week 1 later via `ensure_current_plan_week`, but the existing item is never back-filled, and the week view (`DashboardScreen`) renders items by `plan_week_id`. 
- Layer: API/backend defect (should default to the current week) + frontend state defect. This is the closest reproduction of the owner's "adding a plan produced a plan with zero workouts".

### F-B-FRESH-CLEAN-04 — "create exercise" CTA hidden on an empty library (P2, UX)
- Journey/step: J2: editor -> "+ Добавить упражнение".
- Expected: on an empty library a visible "Создать упражнение" CTA.
- Actual: "Добавить упражнение | Выберите упражнение — на следующем шаге настроите подходы и отдых. Нет нужного? Введите название, и появится «Создать своё». | Ничего не найдено". The CTA "Создать своё: «<текст>» +" appears only after typing. It works (leads to protocol sheet -> "Добавить" -> workout shows "3 × 10 повторений"). So not a dead end, but an unprompted user sees "Ничего не найдено" with an enabled search box only.
- Evidence: `J2-picker-empty.png`, `EMPTY-light-E4.png`, `EMPTY-dark-E4.png`, `trace-J2.log`.
- Layer: UX dead-end (soft).

### F-B-FRESH-CLEAN-05 — expired user is never paywalled in the Mini App (P2, subscription/auth)
- Journey/step: J6.
- Expected: "clear paywall/no_access" for an expired user.
- Actual: Профиль > Подписка: "Статус | истекла | Оплата картой временно недоступна. | Стоимость подписки: 990 ₽ / месяц... | Как оформить: оплата прямо в боте после пробного периода — картой через Робокассу или Telegram Stars." — no payment button, and Главная/Планы/Журнал/Аналитика show no gating text; the expired user can create a workout ("Просроченный"), add exercises, "Начать" and reach "ЖИВАЯ ТРЕНИРОВКА" (exploration, tg 7100003). No crash, no dead UI.
- Evidence: `J6-expired-subscription.png`, `J6-expired-*.png`, `sub-expired.png`, `trace-J6.log`.
- DIAG: `no_access` exists only in legacy `app/web/routes.py:736,1711`; `/api/v2/*` routes call no `has_access`. Needs a product decision whether Mini App is meant to be gated at all (bot paywall: `app/bot/handlers/workout.py:247`).
- Layer: subscription/auth defect or valid domain difference.

### F-B-FRESH-CLEAN-06 — removing a plan item rewrites journal history (P2, persistence)
- Journey/step: J2/J4 end: after a plan-run session was completed, Планы -> Действия -> "Убрать из плана" -> "Убрать".
- Expected: the template and the journal history are untouched (endpoint docstring: "Journal history не задеты").
- Actual: Журнал entry flips from `По плану | Мои подтягивания | 09:28 | Подходы 2 | Повторы 16 | Усилие 4` to `По плану | Тренировка | 09:28 | ...` (title lost; label "По плану" remains although no plan row exists). Template workout survives.
- Evidence: `J2-journal-plan.png` (before) vs `J2-journal-after-remove.png` (after), `trace-J2.log` EXPECT "Журнал still names ... FAIL".
- DIAG: `app/web/routes_v2.py:1104` `_resolve_session_titles` derives the title via `SessionPlanItem -> PlanItem`; `delete_mutable_plan_item` (`app/db/repositories/training_plans.py:250`) deletes the row and `session_plan_items` cascade; the session's own `workout_snapshot` title (routes_v2.py:1179) is only a fallback for the other branch.
- Layer: persistence defect (violates "archive, don't delete" spirit).

### F-B-FRESH-CLEAN-07 — empty workout detail: disabled "Начать" w/o explanation (P3, UX)
- E12: `Мои тренировки` > workout without exercises: chip "Пока без упражнений", "Начать" disabled, "Упражнения: В тренировке пока нет упражнений" — no CTA. "Изменить" exists (so not a hard dead end). Evidence `E12-detail.png`, `EMPTY-dark-E12-detail.png`.

### F-B-FRESH-CLEAN-08 — stale subscription label after expiry (P3, API/backend)
- After the trial end date passed (harness injection on `users.subscription_expires_at`), Профиль > Подписка: "Статус | пробный период (осталось 0 дн., до 04.10.2026)" instead of expired; the status flips only after some access check calls `refresh_status` (`app/services/subscription.py:89`: "Ничто не переводит статус в EXPIRED проактивно"); `GET /api/profile` itself does not refresh (`app/web/routes.py:488`). Evidence `trace-J6.log`, `J6-expired-subscription.png`.

### F-B-FRESH-CLEAN-09 — raw category "user" in Аналитика (P3)
- Аналитика: "По типам | 1 | всего | user | 1 · 100%", "Сводка | Тип Тренировки Минуты | user 1 2". Evidence `J2-analytics.png`, `analytics-after-w1.png`.

### F-B-FRESH-CLEAN-10 — internal jargon in the live summary (P3)
- "Прогрессия не пересчитана — нет активного курса со ступенчатой стратегией для этих упражнений." shown to a user with no course. Evidence `J2-summary-plan.png`, `summary2.png`.

### F-B-FRESH-CLEAN-11 — partial run counted as done on the plan (P3, UNKNOWN)
- Finished 2 of 3 sets from the plan: summary "Подтягивания — 2/3 , не выполнено"; effort sheet text "Что сделано — зачтено, остальное останется в плане."; Планы then "Текущая неделя · 1 из 1 | ... 1/1 | Ещё раз". The remainder does not "stay in the plan" visibly. Evidence `after-close-summary.png`, `plans-after-complete.png`.

### F-B-FRESH-CLEAN-12 — contradictory Планы card (P3, UX copy)
- Above a week that contains manual workouts: "Текущий план | Курсов в плане нет. Добавьте курс на Главной. | [Выбрать курс на Главной]". Evidence `J4-plan-week2.png`, `plans-after2.png`.

### F-B-FRESH-CLEAN-13 — exercise created before confirmation (P3, persistence)
- `POST /api/v2/exercises {"name":"Подтягивания"}` fires on tapping "Создать своё: «Подтягивания»"; the next time the picker lists "Подтягивания" even if the protocol sheet was cancelled/abandoned. Observed in exploration (tg 7100001).

### F-B-FRESH-CLEAN-14 — harness environment (P3, reference-only)
- `@playwright/test` 1.63.0 expects chromium build 1243 (`/opt/pw-browsers/chromium_headless_shell-1243/...`), installed are `chromium-1194`/`chromium_headless_shell-1194`. The audit config sets `launchOptions.executablePath` (a renamed copy of the 1194 binary, see TRACE header). Also the console shows `Telegram SDK init() failed ... Unable to retrieve launch parameters` in every run: expected with the repo's own Telegram mock (platform difference, not an app defect).

## Assumptions / not tested
- "Home -> discover a program" was interpreted literally: there is no program anywhere, hence J1 is BLOCKED rather than redirected to another path.
- J3 "any workout reachable through the UI": the only reachable workouts are user-created custom ones (J2), so J3 shares J2's workout.
- Dark theme only for the empty-state pass (7100017).
- Real iPhone-only behaviour (safe-area, native keyboard, WebView back button) is not reproducible here; viewport emulation only (platform difference).
