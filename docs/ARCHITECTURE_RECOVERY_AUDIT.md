# ARCHITECTURE RECOVERY AUDIT — роль D (архитектурный аудит, только чтение)

Ветка `claude/wonderful-tesla-2dph8h`, HEAD `1735cad`, дата аудита 2026-10-06 (вторник).
Код продукта не менялся. Цитаты `file:line` — по HEAD. Метки:
**[КОД]** — доказано чтением кода/истории git; **[ГИПОТЕЗА]** — правдоподобно, но требует проверки
по данным staging (SQL-проверки — в §0.4).

Приоритет источников по `CLAUDE.md`: конституция > `PROJECT_SPEC` > `IMPLEMENTATION_PLAN` > notes/skills >
код. Где здесь предлагается изменение поведения — это **предложение владельцу**, не решение.

---

## 0. ИНЦИДЕНТ: «Подтягивания / Неделя 4 · 5–11 окт / Текущая неделя · 0 из 0»

### 0.1 Что именно видит пользователь (разбор экрана)

- «Текущий план» → карточка курса рисуется только для `is_active` инклюзий
  (`webapp-frontend/src/DashboardScreen.tsx:712`, `:892`). Значит у владельца **есть активная
  ProgramInclusion** с `snapshot.program_name = «Подтягивания»` (`app/web/routes_v2.py:183`).
- «Неделя 4 · 5 окт – 11 окт» — это степпер **недели плана** (`DashboardScreen.tsx:1125`), а не
  `inclusionWeekLabel` курса (тот выводится только при `duration_weeks`, `plansOverview.ts:38-43`;
  у «Подтягиваний» длины нет). Неделя 4 при сегодня = 2026-10-06 ⇒ `plan_week_number`
  (`app/domain/multi_program.py:328-335`) отсчитан от недели **14–20 сентября** ⇒
  `TrainingPlan.created_at` ∈ 14–20.09.2026.
- «Текущая неделя · 0 из 0» + «На эту неделю пока ничего не запланировано.» —
  `weekItems = plan.items.filter(item.plan_week_id === week.id)` пуст (`DashboardScreen.tsx:997`,
  `:1157-1162`). Фронтенд отбрасывает **только** строки неактивных инклюзий (`toPlanState`,
  `DashboardScreen.tsx:202-216`), а инклюзия активна. `isCurrent` — это `current_week_id` сервера
  (`planWeekNav.ts:53-63`). ⇒ **Сервер вернул 0 PlanItem с `plan_week_id = текущая неделя`.**
  Фронтенд-фильтрация как причина **опровергнута [КОД]**.

### 0.2 Датировка: владелец — пользователь бэкфилла 19.09 до checkpoint 1.1 [КОД, история git]

| Дата | Коммит | Что поменялось в `scripts/backfill_multi_program.py` |
|---|---|---|
| 18.09 | миграция `2b3c4d5e6f7a` | таблицы `training_plans/plan_weeks/program_inclusions/plan_items` |
| 19.09 16:51 | `cd2808f` | «Найден на **живом аккаунте**»: бэкфилл создавал План+Инклюзию без PlanItem; добавлена ручная вставка `PlanItem(... program_inclusion_id, plan_week_id=NULL)` из `snapshot["exercises"]` |
| 19.09 | `526f680` (Checkpoint 1) | `plan_week_id`, `PlanWeekService`, seed `ProgramItem` |
| 20.09 05:30 | `c895b82` (Checkpoint 1.1) | rollover читает **только** `snapshot["program_items"]`; `seed_catalog` начинает класть этот ключ; появляется `normalize_legacy_snapshots` |

Снимок, записанный бэкфиллом 19.09 (`git show 3c66456:scripts/backfill_multi_program.py`, `snapshot = {...}`
около стр. 218), **не содержит ключа `program_items`**. Неделя 1 плана = 14–20.09 ровно совпадает с
прогоном 19.09; неделя 4 = 5–11.10 — ровно экран инцидента.

### 0.3 Все пути «инклюзия + план + текущая неделя есть, а строк в текущей неделе 0»

Единственная точка наполнения текущей недели — `PlanWeekService._materialize_inclusions_into_week`
(`app/services/plan_week.py:99-164`), вызывается из `ensure_current_plan_week` (`:73`). Строк нет, если
для каждой активной инклюзии сработал один из `continue`:

| # | Путь | Где | Статус | Для владельца |
|---|---|---|---|---|
| P1 | **Снимок без `program_items`** (legacy-снимок бэкфилла до 1.1): unweeked-строк уже нет (привязаны к той неделе, когда план впервые открыли после Checkpoint 1), `existing_this_week` пуст → `program_items_snapshot` falsy → `continue  # legacy-снимок ... нормализуется отдельно, не здесь` | `plan_week.py:134-153` | **[КОД]** путь существует и тих | **Главный кандидат** |
| P2 | Нормализация `normalize_legacy_snapshots` существует, но запускается **только** ручным прогоном `backfill_multi_program.py` (`:647-655`); deploy его не вызывает (`grep backfill deploy* .github` — пусто, кроме комментария) | `scripts/backfill_multi_program.py:607-630` | **[КОД]** | Нужен SQL: если ключа нет — P1 подтверждён |
| P3 | `snapshot.program_items == []`: инклюзия создана, когда у Program не было ProgramItem (бэкфилл/`create_inclusion` до seed ProgramItem 19.09 или установка без каталога) — `_build_snapshot` честно кладёт `[]` | `app/services/program_inclusion.py:42`, `:119` | **[КОД]** | Маловероятно (у владельца бэкфилл) |
| P4 | Все элементы снимка с `exercise_id=None` (complex-only ProgramItem) → `create_plan_items_for_week_from_snapshot` пропускает все | `app/db/repositories/training_plans.py:422-425`; так же `bulk_create...:296-297` | **[КОД]** | Нет (у «Подтягиваний» exercise_id есть) |
| P5 | `structure_type` ≠ `recurring` (FIXED/SINGLE_LESSON вообще не материализуются) или снимок без `structure_type` и `Program` не найдена | `plan_week.py:123-132` | **[КОД]** | Нет: и бэкфилл, и миграция — `recurring` (`backfill:207,264`, `a4c8e1f7b2d9:147`) |
| P6 | `inclusion.is_active = false`, а UI всё ещё показывает курс | `plan_week.py:109`; UI фильтрует активные `DashboardScreen.tsx:712` | **Опровергнуто [КОД]** — неактивный курс в «Текущем плане» не рисуется |
| P7 | Две строки Program «Подтягивания» (бэкфилл vs миграция), у одной нет ProgramItem | бэкфилл: `scalar_one_or_none` по имени (`backfill:199-203`); миграция: `ORDER BY id LIMIT 1` (`a4c8e1f7b2d9:141`) | **Опровергнуто для материализации [КОД]**: P1 читает снимок, а не live Program. Дубль Program возможен только через сторонний сид/ручную вставку **[ГИПОТЕЗА]**; тогда бэкфилл падает `MultipleResultsFound` ⇒ нормализация (P2) невыполнима — усилитель P1 |
| P8 | Строки привязаны к «чужой» неделе: unweeked-строки бэкфилла привязаны к неделе первого открытия (`attach_unweeked`, `plan_week.py:134-143`); в последующих неделях путь — только P1 | `plan_week.py:142-143` | **[КОД]** — это предусловие P1, а не самостоятельная причина |
| P9 | Номер недели: бэкенд от `plan.created_at.date()` (UTC-дата) и локального `today`; фронт берёт `current_week_id` сервера | `plan_week.py:44-45`, `routes_v2.py:832-836`, `planWeekNav.ts:53-63` | **Опровергнуто как причина 0 [КОД]** — неделя может сдвинуться у полуночи понедельника, но материализуется та же, что показывается |
| P10 | Фазы/REST: материализатор фазу не фильтрует, `PlanWeek.phase` всегда `BASE` | `plan_week.py:51,96,202` | **Опровергнуто [КОД]** (REST дал бы «Неделя отдыха», `DashboardScreen.tsx:1010`) |
| P11 | GET без коммита/кэш | `app/web/db.py:15-17` коммитит GET; `PLAN_STALE_MS` 60 с (`DashboardScreen.tsx:198`) | **Опровергнуто [КОД]** для устойчивого симптома |
| P12 | Удаление программных строк текущей недели | `delete_mutable_plan_item` отказывает программным (`training_plans.py:250-262`); `delete_unperformed_inclusion_items_after_week` — только недели **после** текущей (`:441-460`) | **Опровергнуто [КОД]** |
| P13 | Две активные инклюзии (двойной POST, нет уникальности на `(plan, program, active)`) — у старой снимок без `program_items`, новая наполнила бы неделю | `program_inclusion.py:130-139` | **[КОД]** возможна, но дала бы ≠0; Dashboard тогда `multiple_active_inclusions` (`routes_v2_dashboard.py:79-80`) |
| P14 | Недели, созданные «пустыми» путями, которые не зовут материализацию (`_fill_past_gap_weeks`) | `plan_week.py:85-97` | **[КОД]**, но это прошлые недели (read-only по спеке) — не текущая |

### 0.4 Проверки на staging (только чтение; выполнять оператору)

```sql
-- 1) снимок без program_items у активной инклюзии  → подтверждает P1/P2
SELECT pi.id, pi.started_at, pi.snapshot ? 'program_items' AS has_items,
       jsonb_array_length(COALESCE(pi.snapshot->'program_items','[]')) AS n,
       pi.progression_state->>'backfilled_from' AS bf
FROM program_inclusions pi JOIN training_plans tp ON tp.id = pi.training_plan_id
JOIN users u ON u.id = tp.user_id WHERE u.telegram_id = :owner AND pi.is_active;
-- 2) строки по неделям
SELECT pw.week_number, pw.start_date, count(p.id) FROM plan_weeks pw
LEFT JOIN plan_items p ON p.plan_week_id = pw.id WHERE pw.training_plan_id = :plan GROUP BY 1,2 ORDER BY 1;
-- 3) дубли каталога  → P7
SELECT id, name FROM programs WHERE name = 'Подтягивания';
-- 4) масштаб: все активные инклюзии без ключа
SELECT count(*) FROM program_inclusions WHERE is_active AND NOT (snapshot ? 'program_items');
```

Ожидание при P1: (1) `has_items=false`, `bf='legacy_v1'`; (2) строки только в одной ранней неделе.

### 0.5 Вывод по инциденту

**Наиболее вероятно (≈85%) — P1+P2**: владелец смигрирован бэкфиллом 19.09 (до `c895b82`), его
снимок без `program_items`, нормализация на staging не прогонялась (или упала, P7). Неделя, в которую он
впервые открыл «Планы» после Checkpoint 1, получила unweeked-строки; каждая следующая неделя — 0.
Свежий e2e проходит, потому что инклюзия создаётся `ProgramInclusionService` со снимком 1.1 и
проверяется в неделе 1 через ветку `attach_unweeked` — путь rollover из legacy-снимка ни одним тестом
не исполняется (см. §15). Остальные кандидаты: P3 ≈5%, P7-как-усилитель ≈5%, прочие ≤5% суммарно.

---

## 1. CURRENT DOMAIN GRAPH

```
Telegram User ──1:1── User (users)  ── subscription_* (кэш статуса + expires_at)
   │  legacy (источник прогрессии бота и legacy Mini App):
   ├── Baseline, Questionnaire, EquipmentItem
   ├── Workout ──< Block(A/B) ;  WorkoutSet (сеты по 12)      ← resolve_next_targets
   ├── ElectiveWorkout
   │  v2:
   └── TrainingPlan (UNIQUE user_id) ──< ProgramInclusion(snapshot, progression_state, is_active)
          │                                   └── program_id → Program ──< ProgramItem → Exercise / Complex
          ├──< PlanWeek(week_number, start_date, phase)  UNIQUE(plan, week_number)
          └──< PlanItem(plan_week_id NULL?, program_inclusion_id NULL?, exercise_id, complex_id)
                    └──< SessionPlanItem >── TrainingSession(source, status, workout_snapshot)
                                                └──< SessionBlock ──< SetTarget / SetLog
   Journal  = legacy Workout + v2 TrainingSession − backfill-копии (_backfilled_fingerprint)
   Analytics v2 = TrainingSession (+ legacy в части экранов)
   Complex(source_type system|user, owner_user_id) ──< ComplexItem(protocol)
```

### 1.1 Таблица рёбер

Колонки: **Кто создаёт / Когда / Идемп. / Eager|Lazy / Источник истины / Старые пользователи могут не иметь? /
Что чинит / Какой экран-API / Частичное состояние?**

| Ребро | Кто создаёт | Когда | Идемп. | E/L | Истина | Старые без него? | Что чинит | Триггер | Частично? |
|---|---|---|---|---|---|---|---|---|---|
| TelegramUser→User | бот `/start`, legacy онбординг (`users.py:73`) | первое сообщение / анкета | да (по telegram_id) | eager | `users` | нет | — | бот, `/api/onboarding/*` | `onboarding_completed_at NULL` — «не онбордился» |
| User→Subscription | trial при онбординге, оплата, админ | событие | — | eager + **lazy refresh на GET** (`routes.py:455,1338`) | `subscription_expires_at`; кэш `subscription_status` | кэш может залипнуть `trial` (`ENGINEERING_NOTES` #300) | `refresh_status` на GET profile/subscription | `/api/profile`, `/api/subscription` | да: кэш ≠ срок |
| User→Workout/Block/WorkoutSet | бот, legacy `/api/workout/submit` | каждая тренировка legacy | частично | eager | legacy — истина прогрессии бота | — | — | бот, `WorkoutScreen` (`App.tsx:456`) | — |
| User→ElectiveWorkout | бот/`/api/elective/submit` | — | — | eager | legacy | — | — | бот, Mini App | — |
| User→TrainingPlan | `get_or_create_for_user` (`training_plans.py:48-55`) из `create_inclusion`, `POST /plan-items`, `POST /plan/weeks`; **бэкфилл** (`backfill:699`) | первое действие v2 / ручной прогон скрипта | да (UNIQUE) | lazy | `training_plans` | **да**: онбордившиеся после прогона бэкфилла плана не имеют (онбординг его не создаёт) | ничего автоматически; `GET /plan` → `plan:null` (`routes_v2.py:849-850`) | Главная «Добавить», AddToPlan | нет |
| Plan→ProgramInclusion | `ProgramInclusionService.create_inclusion` (`program_inclusion.py:114-140`); бэкфилл (`backfill:702-710`) | «Добавить в план»; прогон скрипта | **нет** (нет уникальности, клиентская защита `HomeScreen.tsx:246-248,262-264`) | eager | `program_inclusions` | да (как выше) | — | `POST /program-inclusions` | **да**: снимок без `program_items` (до 1.1), `[]`, без `structure_type` |
| Inclusion→snapshot.program_items | `_build_snapshot` (`program_inclusion.py:42`); `seed_catalog` (`backfill:281`); `normalize_legacy_snapshots` (`backfill:607-630`) | при создании; ручной прогон | да | eager / ручной repair | снимок (immutable по контракту) | **да**: инклюзии бэкфилла 19.09 | **только ручной** прогон бэкфилла | нет UI-триггера | да |
| Inclusion→progression_state | `_build_initial_progression_state`; бэкфилл `_build_progression_state` (из legacy); каскад v2 (`progression_cascade.py:239`, `live_session.py:861`, `session_log.py:267`) | создание; каждая v2-сессия | — | eager | v2 | бот-тренировки после бэкфилла **не попадают** | нет | live session | да: застывший снимок legacy-прогрессии |
| Program→ProgramItem | миграция `a4c8e1f7b2d9:170-182,226-230`; `seed_catalog` (`backfill:217-242`) | `alembic upgrade`; ручной прогон | да | eager | `program_items` | — | миграция | — | возможно: Program без items при сиде до 19.09 |
| Plan→PlanWeek | `ensure_current_plan_week` (`plan_week.py:47-52`), `_fill_past_gap_weeks` (`:85-97`), `ensure_plannable_week` (`:197-203`) | **на GET /plan** и пишущих вызовах | да (ON CONFLICT, `training_plans.py:321-351`) | **lazy, на чтении** | `plan_weeks` | да: недели не существуют, пока экран не открыт | следующий GET | Home, Планы, Журнал, AddToPlan, SessionPre (все зовут `fetchPlan`) | да: неделя без строк |
| PlanWeek→PlanItem (курс) | `bulk_create_plan_items_from_program_items` (unweeked, `training_plans.py:282-310`) + `attach_plan_items_to_week` (`:400-404`); `create_plan_items_for_week_from_snapshot` (`:406-439`) | создание инклюзии; **первый GET недели** | да по (инклюзия, неделя) под `lock_plan` | **lazy** | производное от снимка | **да** (P1) | ничего (тихий `continue`) | GET /plan, POST /plan/weeks, copy-to-next | **да** — предмет инцидента |
| PlanWeek→PlanItem (ручн.) | `POST /plan-items` (`routes_v2.py:1016-1078`), `copy_manual_items` | действие | по мультимножеству | eager | `plan_items` | сироты `plan_week_id NULL` до #297 | самолечение на GET (`plan_week.py:57-59`) | AddToPlan | был баг #297 |
| PlanItem→SessionPlanItem→TrainingSession | `create_live_session` (`training_sessions.py:245`) | «Начать» | `client_session_id` | eager | v2 | — | — | `POST /sessions/live` | in_progress / lazy-финализация interval на `GET /sessions` (`routes_v2.py:1254`) |
| Workout→TrainingSession (копия) | бэкфилл (`backfill:689-696`) | один раз | по пользователю (маркер — TrainingPlan) | — | legacy (копия скрыта отпечатком) | тренировки после прогона не копируются | ничего (и не нужно: Журнал читает legacy) | — | — |
| Complex/ComplexItem | миграция (system), Builder (user) | — | да (по имени) | eager | `complexes` | — | — | Builder | — |

---

## 2. CURRENT STATE CREATION PATHS (кто создаёт пользовательское состояние плана)

1. **Свежий путь v2**: Главная «Добавить» → `POST /program-inclusions` (`routes_v2.py:900-924`) →
   `create_inclusion` (план, инклюзия со снимком 1.1, unweeked PlanItem) → `ensure_current_plan_week`.
2. **Ручная строка**: `POST /plan-items` (`routes_v2.py:1016-1078`) → `get_or_create_for_user` (план без курса) →
   `ensure_current_plan_week` (если не передан `plan_week_id`).
3. **Неделя вперёд**: `POST /plan/weeks` (`routes_v2.py:956-972`) → `get_or_create_for_user` → `ensure_plannable_week`.
4. **Копирование недели**: `POST /plan/weeks/{id}/copy-to-next` (`:975-999`).
5. **Чтение**: `GET /plan` (`:839-898`) — создаёт неделю, gap-недели, привязывает сирот/unweeked, материализует.
6. **Бэкфилл (ручной оператор)**: `backfill_all` (`backfill:633-754`) — для новых: история + план +
   инклюзия + `bulk_create` + `ensure_current_plan_week(today=now.date() в UTC)`; для уже мигрированных —
   только `ensure_current_plan_week`; до цикла — `normalize_legacy_snapshots`.
7. **Исторические (уже не в коде, но в данных)**: бэкфилл 18–19.09 без PlanItem; бэкфилл `cd2808f` с
   ручными PlanItem из `snapshot["exercises"]`, `count_per_week=3`, без недели; снимки без `program_items`.
8. **E2E/тесты**: `scripts/e2e_seed.py` создаёт `TrainingPlan/PlanItem` напрямую (19 мест, §15).
9. **Бот**: не создаёт ни одной v2-строки (`grep models_program app/bot` — пусто).

Итого **6 живых путей + 2 исторических формы данных**, из них только №5/№6 «сходятся» (и №6 — вручную).

---

## 3. MULTIPLE SOURCES OF TRUTH — **12**

| # | Факт | Источник A | Источник B (и далее) | Риск |
|---|---|---|---|---|
| 1 | Прогрессия «Подтягиваний» | legacy `Workout/Block/WorkoutSet` → `resolve_next_targets` | `ProgramInclusion.progression_state` (застывший снимок бэкфилла + v2-каскад) | цифры расходятся тихо (skill multi-program «главный класс багов») |
| 2 | История тренировок | `Workout` | `TrainingSession` (копии бэкфилла, скрытые `_backfilled_fingerprint`) | двойной учёт (#282/#284) |
| 3 | Факультативы | `ElectiveWorkout` | `TrainingSession(source=elective)` | — |
| 4 | Структура курса | live `Program/ProgramItem` | `inclusion.snapshot.program_items` (иммутабелен) | legacy-снимок без ключа = P1 |
| 5 | Строки недели | снимок (шаблон) | материализованные `PlanItem` | производные данные хранятся, но не пересчитываются |
| 6 | Системный каталог | миграция `a4c8e1f7b2d9` (конфиг заморожен) | `seed_catalog` (конфиг из живых констант `backfill:146-168`) | `seed_exercise_library.py`, `seed_collections.py` | расхождение конфига/набора items снимка |
| 7 | «Текущая неделя» | `plan_week_number(plan.created_at UTC-date, local today)` | фронт fallback `currentWeekIndex(localToday)` (`planWeekNav.ts:39-47`) | `course_week_number(started_at local)` (`program_schedule.py:18`) | сдвиг у полуночи |
| 8 | «Сегодня» | `_plan_today` (tz пользователя) | UTC в `routes_v2_dashboard.py:90`, `live_session.py:310` | устройство `localToday` (`planWeekNav.ts:99`, дубль `journalLog.ts:61`) | разные дни у UTC±N |
| 9 | Доступ | `subscription_expires_at` | кэш `subscription_status` | залипание (#300) |
| 10 | «Пользователь мигрирован/онбордился» | `onboarding_completed_at` | наличие `TrainingPlan` (маркер бэкфилла `backfill:526-528`) | `dashboard/status=not_migrated` (`routes_v2_dashboard.py:72-77`) | онбордившийся после бэкфилла — без плана |
| 11 | «Курс уже добавлен» | клиентский `includedProgramIds` (`HomeScreen.tsx:246`) | сервер (без уникальности) | дубль инклюзий |
| 12 | Упражнения подтягиваний | `BlockType/ExerciseType` legacy | `Exercise` (`block_a/block_b`, роли ищутся по `subcategory` `find_step_role_exercises`) | — |

---

## 4. LEGACY / V2 OVERLAP

- Бот и legacy Mini App (`WorkoutScreen`, `App.tsx:456`; `/api/workout/*`, `routes.py:847-1086`) пишут
  только legacy; v2 пишет только v2. Синхронизации после единственного прогона бэкфилла **нет** [КОД]
  (`backfill:28-31`: «НЕ переключает логику»).
- `admin_reset` (`app/services/admin_reset.py:45-54`) чистит legacy и сбрасывает онбординг, **но
  `TrainingPlan/ProgramInclusion/progression_state` не трогает** → после повторного онбординга v2 показывает
  старый курс с прежней прогрессией [КОД].
- Готовность «ещё рано» v2 (`routes_v2_dashboard.py:86-95`) считает только v2-сессии; legacy-тренировка в
  боте вчера не блокирует курс в v2 сегодня [КОД; продуктово не решено → вопрос владельцу].
- Сид e2e берёт каталог через `scripts.backfill_multi_program.seed_catalog` (`e2e_seed.py:137-146`) —
  тестовая фикстура зависит от операторского скрипта.

---

## 5. LAZY SIDE EFFECTS (запись на GET)

| GET | Что пишет | Где |
|---|---|---|
| `GET /api/v2/plan` | PlanWeek текущей недели; gap-недели; привязка сирот и unweeked; PlanItem текущей и существующих будущих недель; `SELECT … FOR NO KEY UPDATE` плана | `routes_v2.py:855-858` → `plan_week.py:34-83` |
| `GET /api/v2/sessions` | lazy-финализация interval-сессий | `routes_v2.py:1254` |
| `GET /api/profile`, `GET /api/subscription` | `refresh_status` кэша подписки | `routes.py:455`, `:1338` |

`fetchPlan` (то есть материализация) вызывают 5 экранов: `HomeScreen`, `DashboardScreen`,
`SessionJournalScreen`, `AddToPlanScreen`, `SessionPreScreen`. Пользователь, не открывающий Mini App, не имеет
недель вовсе; бот их не создаёт. Повторный GET с ошибкой материализации падает 500 целиком (нет изоляции
«показать то, что есть»).

---

## 6. STATE CONVERGENCE FAILURES

Каждый пункт: место + конкретное состояние, которое не сходится само.

1. **Legacy-снимок без `program_items` никогда не даёт строк после первой недели.**
   `plan_week.py:151-153`. Состояние: инклюзия бэкфилла 19.09, unweeked-строки уже привязаны к неделе W;
   любая неделя > W → 0 строк. Repair — только ручной прогон бэкфилла (`backfill:652-654`). **= инцидент.**
2. **Нормализация привязана к одной Program по имени.** `backfill:620` (`program_id == seed.program_id`),
   `:199-203` (`scalar_one_or_none`). Состояние: две Program «Подтягивания» → скрипт падает до нормализации;
   инклюзия на «другой» Program не нормализуется никогда. [ГИПОТЕЗА о наличии дубля]
3. **Пустой снимок `program_items: []`** (`program_inclusion.py:42,119`): курс подключён, когда у Program не
   было items → ни одной строки ни в одной неделе, без ошибки и без repair.
4. **Онбордившийся после прогона бэкфилла legacy-пользователь не имеет TrainingPlan.** `users.py:73` не
   создаёт план; `routes_v2_dashboard.py:72-73` → `not_migrated` навсегда, пока сам не нажмёт «Добавить».
5. **progression_state застыл на 19.09**, бот-тренировки после этого его не двигают
   (`backfill:447-520` — один раз; бот не импортирует v2). Состояние: владелец тренировался в боте →
   v2 предлагает устаревшие цели.
6. **Сброс админом не сбрасывает v2.** `admin_reset.py:45-54`. Состояние: пересозданный онбординг + старый план/прогрессия.
7. **Недели существуют только если экран открывали.** `plan_week.py:85-97` заполняет пропуски пустыми
   неделями; прошлые недели строками не наполняются — история «что было запланировано» для недель без
   визитов теряется навсегда (по спеке это принято, но это non-convergence данных).
8. **Дубль активных инклюзий одного курса.** `program_inclusion.py:130-139` без проверки;
   `routes_v2_dashboard.py:79-80` → `multiple_active_inclusions` — Dashboard неработоспособен, repair нет.
9. **Строки в будущих неделях из снимка, неделя всегда BASE.** `plan_week.py:51,96,202` + материализатор не
   фильтрует `week_phase` (`training_plans.py:426-431`) — при появлении REST/PEAK-items все фазы попадут в каждую неделю.
10. **Бэкфилл зовёт `ensure_current_plan_week(today=now.date())` в UTC**, рантайм — в tz пользователя
    (`backfill:675,727` vs `routes_v2.py:832-836`). У UTC+N в понедельник 00:00–N:00 бэкфилл материализует
    «прошлую» неделю. Backfill ≠ runtime.
11. **`plan.created_at.date()` — UTC-дата**, `today` — локальная (`plan_week.py:44`). План, созданный в
    понедельник 01:00 MSK (= воскресенье UTC), нумерует недели от предыдущего понедельника; `start_date`
    недель согласован, но «Неделя N» на 1 больше ожидаемой. [КОД; влияние — косметика/сдвиг]
12. **Ручные PlanItem бэкфилла `cd2808f` построены из `snapshot["exercises"]`, а не из ProgramItem**
    (`count_per_week=3`, без `week_phase`). Если ProgramItem позже изменятся, первая неделя и
    последующие (после нормализации) будут разной формы. [КОД, история]
13. **Будущие недели, созданные до появления курса**, наполняются только если попадают в окно +4 при
    следующем GET (`plan_week.py:79-81`); неделя > +4 существовать не может — ок; но удалённые «Убрать курс»
    будущие строки (`training_plans.py:441-460`) не возвращаются при повторной активации **той же** инклюзии
    (активации нет — только новая инклюзия). Ок по спеке; отмечено как необратимость.

---

## 7. TIME / WEEK LOGIC — все места

| Где | Что считает | База времени |
|---|---|---|
| `app/domain/multi_program.py:324-343` | `plan_week_number`, `plan_week_start_date` (понедельник) | чистые date |
| `app/services/plan_week.py:44-45, 91, 174, 189-190` | номер текущей недели | `plan.created_at.date()` (**UTC**) + `today` (local) |
| `app/web/routes_v2.py:828-836` | `_utcnow`, `_plan_today` | tz пользователя (`resolve_timezone`, `training_analytics.py:26-36`) |
| `app/web/routes_v2.py:1057, 1105` | окно планирования для POST/PATCH plan-items | как выше |
| `app/web/routes_v2.py:176-180` + `app/domain/program_schedule.py:18-24` | `course_week_number` (от `started_at` local, **не** понедельник) | local |
| `app/domain/multi_program.py:355-370` + `routes_v2.py:872-883` | `done_count` по неделе item | local |
| `app/services/live_session.py:310` | запрет старта будущей недели | **UTC + 1 день допуск** |
| `app/web/routes_v2_dashboard.py:90` | `check_training_readiness` (rest days) | **UTC** |
| `app/domain/rules.py:36-44`, `routes.py:2406`, `bot/handlers/workout.py:219` | legacy MIN_REST_DAYS | UTC `performed_at` |
| `app/domain/training_analytics.py:112` | понедельник для аналитики | local |
| `app/bot/handlers/reports.py:52`, `app/workers/weekly_report.py:27` | «неделя» = последние 7 суток | UTC, скользящая |
| `webapp-frontend/src/planWeekNav.ts:39-63` | текущая неделя (fallback по `start_date <= today`) | сервер `current_week_id` / устройство |
| `planWeekNav.ts:99-104`, `journalLog.ts:61` | `localToday` (дубль) | устройство |
| `plansOverview.ts:24-28` | даты курса | устройство |
| `scripts/backfill_multi_program.py:675, 727, 776` | `today` для материализации | **UTC** |

Итого **≥14 мест**, 3 базы времени (UTC, tz пользователя, устройство), 2 определения «недели»
(календарная от понедельника vs скользящие 7 дней).

---

## 8. SUBSCRIPTION BOUNDARIES

- Гейтится только **старт** курсовой тренировки: `live_session.py:282, 313-320`; запись курса
  `routes_v2.py:1441-1444`; legacy — `has_access` в `/api/workout/*`. Материализация плана, просмотр,
  «Добавить курс» — не гейтятся (`PROJECT_SPEC` §5 «Подписка», D6) [КОД соответствует спеке].
- Подписка **не влияет** на 0-из-0 (P-список §0.3): материализация не читает подписку [КОД].
- Остаточный риск: кэш `subscription_status` освежается только на двух GET; бот, вероятно, читает кэш
  [ГИПОТЕЗА — не проверено в этом аудите].

---

## 9. SYSTEM CONTENT LIFECYCLE (seed vs migration vs backfill)

| Аспект | Миграция `a4c8e1f7b2d9` | `seed_catalog` (бэкфилл) | `create_inclusion` |
|---|---|---|---|
| Поиск Program | `ORDER BY id LIMIT 1` (`:141`) | `scalar_one_or_none` (`backfill:200-201`) — падает при дубле | по id |
| Поиск Exercise | `name` + `owner_user_id IS NULL` (`:156`) | **только `name`** (`backfill:172`) — пользовательское упражнение с тем же именем → `MultipleResultsFound` [ГИПОТЕЗА о достижимости] | роли по `subcategory` |
| Config | заморожен на 05.10 (`:51-58`) | живые константы на момент прогона (`backfill:146-168`) | `program.config` |
| `program_items` снимка | — | только items A и B (`backfill:252-253, 281`) | **все** `list_program_items` (`program_inclusion.py:119`) |
| Пользовательские строки | никогда | **записывает всех онбордившихся** | одна инклюзия |
| Запуск | каждый deploy | вручную оператором | UI |

Миграция `4e5f6a7b8c9d` добавила `plan_week_id` **без data-шага** (комментарий `:22-25`: «проставляет
отдельный бэкфилл-шаг») — схема без сходимости данных. Миграция `a4c8e1f7b2d9` кладёт каталог, но
**не нормализует** существующие инклюзии. Ни одна миграция не исправляет legacy-снимки.

---

## 10. TOP ARCHITECTURAL ROOT CAUSES

| Ранг | Корень | Доказательство | Проявления |
|---|---|---|---|
| **P0** | **Сходимость пользовательского состояния не является инвариантом системы**: repair существует как функция ручного операторского скрипта (`normalize_legacy_snapshots`), а рантайм на нераспознанной форме данных молча делает `continue` | `plan_week.py:151-153`; `backfill:607-655`; deploy не зовёт | инцидент 0-из-0; №1–3 §6 |
| **P0** | **Отсутствует проверка инвариантов** «активная RECURRING-инклюзия ⇒ в текущей неделе ≥1 её строка» — ни в коде, ни в тестах, ни в мониторинге | `grep` тестов §15: нет теста «legacy-снимок, неделя ≥2» | баг виден только владельцу на живых данных |
| **P1** | **Материализация на чтении (lazy) + производные данные хранятся**: PlanItem = f(снимок, неделя), но вычисляется только при открытии экрана и только «вперёд» | §5 | недели без строк, расхождение бэкфилл/рантайм |
| **P1** | **Два несинхронизированных мира legacy/v2** с разовой копией | §3 №1–3, §4 | застывшая прогрессия, admin_reset, not_migrated |
| **P1** | **Тестовые данные создаются в обход продуктовых путей** | §15 | e2e зелёный, staging сломан (#297, #301, этот) |
| **P2** | Время: 3 базы и ≥14 мест | §7 | сдвиги у полуночи |
| **P2** | Нет натуральной уникальности (Program.name, активная инклюзия на программу) | §9, §6 №8 | дубли |

---

## 11. TARGET ARCHITECTURE — минимальная сходимость (не переписывание)

Каждое изменение — с ответом «КАКОЙ КЛАСС БАГОВ СТАНОВИТСЯ НЕВОЗМОЖНЫМ». Всё ниже — предложения владельцу;
поведение продукта не меняется, кроме исчезновения пустых недель у активного курса (что уже требует
`PROJECT_SPEC` §6 «#301»: «Пустая будущая неделя "0 из 0" остаётся только у плана БЕЗ курса»).

### T1. Единая нормализация снимка в рантайме — `normalize_inclusion_snapshot(inclusion)`
Перенести логику `normalize_legacy_snapshots` в сервис (домен/сервисный слой) и вызывать из
`_materialize_inclusions_into_week` **перед** чтением `program_items`: снимок без ключа (и только без ключа)
дополняется `program_items` из ProgramItem той Program, на которую ссылается инклюзия, один раз,
персистентно (как делает скрипт). Это не нарушает иммутабельность: заполняется отсутствующий ключ, а не
переписывается существующий — ровно семантика уже принятого скрипта (`backfill:615-618`).
**Делает невозможным:** «инклюзия, нормализуемая только оператором» — класс P1/P2 (и сам инцидент) для
любого пользователя, открывшего экран, без ручного прогона. *Требует подтверждения владельца* (решение
«никогда не ходить в live Program за program_items», `plan_week.py:112-121`, сейчас явно запрещает это в
рантайме → конфликт с записанным решением, по `CLAUDE.md` п.6 — спросить).

### T2. `converge_user_plan(user, today)` — одна идемпотентная функция для всех входов
Тонкая обёртка: `normalize snapshots → ensure_current_plan_week → materialize window`. Вызывается из
`GET /plan`, `POST /program-inclusions`, `POST /plan-items`, `POST /plan/weeks`, copy-to-next **и** из
бэкфилла/миграционного скрипта с тем же `today = local(user)`.
**Делает невозможным:** «бэкфилл ≠ рантайм» (§6 №10) и «новая точка создания недели забыла материализацию»
(ловушка (1) в `ENGINEERING_NOTES` #301).

### T3. Громкий отказ вместо тихого `continue`
Нераспознанная форма снимка (нет `program_items` после T1, `[]`, все `exercise_id=None`) → структурированный
лог/метрика `plan_convergence_gap{inclusion_id, reason}` (без падения GET).
**Делает невозможным:** «0 из 0 обнаружен владельцем, а не системой».

### T4. Инвариант-чекер (скрипт `--dry-run` + тест)
SQL-инварианты: (a) каждая активная RECURRING-инклюзия имеет непустой `snapshot.program_items`;
(b) для плана с активной RECURRING-инклюзией текущая неделя (если существует) содержит ≥1 строку этой
инклюзии; (c) нет PlanItem с `plan_week_id IS NULL`; (d) ≤1 активной инклюзии на (plan, program);
(e) одна Program на системное имя. Запуск: CI на e2e-БД и операторски на staging (только чтение).
**Делает невозможным:** незамеченное расхождение данных после деплоя/бэкфилла.

### T5. Тест «живая форма данных», а не сид
Тест: инклюзия со снимком формы 19.09 (без `program_items`) + unweeked строки → GET /plan в неделе 1 →
сдвиг времени на 3 недели → GET /plan → ≥1 строка курса. Доказывается откатом T1.
**Делает невозможным:** регресс P1; e2e без исторических форм данных.

### T6. Data-convergence ревизия = вызов той же функции
Одноразовый шаг деплоя (по правилам `migrations-safe`: `--dry-run`, идемпотентно), который проходит по всем
активным инклюзиям и вызывает T1 (не свою SQL-математику — как требует комментарий `4e5f6a7b8c9d:22-25`).
**Делает невозможным:** «миграция создала схему, данные не сошлись» для уже существующих пользователей,
которые давно не открывают экран.

### T7. Уникальность активной инклюзии на программу (частичный уникальный индекс, аддитивно)
**Делает невозможным:** `multiple_active_inclusions` от двойного тапа/двух вкладок (§6 №8). *Требует
продуктового решения* (можно ли подключить один курс дважды) → вопрос владельцу.

Отброшено (не отвечает на «какой класс багов исключает» в рамках инцидента): перенос материализации в cron,
переписывание week-логики, слияние legacy/v2 (это cutover, отдельная волна).

**Порядок:** диагностика SQL §0.4 → T5 (красный тест) → T1+T3 → T2 → T4 → T6 → T7.

---

## 12. ARCHITECTURAL SMELLS

| Smell | Есть? | Где |
|---|---|---|
| legacy/v2 дублированное состояние | да | §3 №1–3, §4 |
| скрытое lazy-создание на GET | да | `routes_v2.py:855-858`, `:1254`; `routes.py:455,1338` |
| материализация только при открытии экрана | да | §5; бот недели не создаёт |
| разные пути fresh vs existing | да | свежий: `create_inclusion`+`attach_unweeked`; существующий: rollover из снимка (`plan_week.py:151-164`) — e2e исполняет только первый |
| миграции создают схему без сходимости данных | да | `4e5f6a7b8c9d:22-25`; `a4c8e1f7b2d9:34-36` |
| бэкфиллы не эквивалентны рантайму | да | UTC `today` (`backfill:675,727`); снимок только из A/B items (`:281`) vs все items (`program_inclusion.py:119`); конфиг из констант vs `program.config` |
| orphan PlanItems | да (лечатся) | ручные — `plan_week.py:57-59`; программные unweeked — `:134-143` |
| PlanWeeks без PlanItems | да | P1; gap-недели `plan_week.py:85-97` (по спеке) |
| инклюзии без расписания | да | снимок без/с пустым `program_items` (P1/P3) |
| расхождение seed vs migration | да | §9 |
| фронт полагается на материализацию бэкенда | да | «0 из 0» рисуется для любой пустой недели; нет отличия «курс есть, строк нет — ошибка данных» от «пустой ручной план» (`DashboardScreen.tsx:1157-1162`) |
| дублирование бизнес-правил бот/API/фронт | да | MIN_REST_DAYS бот (`workout.py:219`) / legacy API (`routes.py:2406`) / v2 (`routes_v2_dashboard.py:90`); окно +4 бэк (`multi_program.py:346-352`) / фронт (`planWeekNav.ts:82`); `localToday` ×2 |
| расчёт времени/недели в нескольких местах | да | §7 (≥14) |
| устаревшие кэши | да | `subscription_status`; клиентский `includedProgramIds`; `PLAN_STALE_MS` |
| состояние, которое не самолечится | да | §6 №1–6, №8 |
| тесты создают состояние, которое прод обязан создавать сам | да | §15 |

---

## 13. LEGACY-ОБЪЕКТЫ ПРОГРЕССИИ (коротко)

`Workout` (`participates_in_cascade`, `is_free_entry`), `Block` A/B (`equipment_*`, `is_heavy`, `is_deload`,
`transition_failed`), `WorkoutSet` (`workouts_completed`), `Baseline` — читаются `resolve_next_targets` и
приватными хелперами (`_weak_streak`, `_stall_streak`, импортируются бэкфиллом `backfill:96-105`). В v2
перенесено одним снимком в `progression_state` (`backfill:489-520`), детали блоков сознательно потеряны
(`backfill:33-48`). Любая правка формулы legacy после 19.09 не отражается в v2 [КОД].

---

## 14. ВОПРОСЫ ВЛАДЕЛЬЦУ (конфликты/пробелы — не решались)

1. T1 противоречит записанному решению «за `program_items` в live Program не ходить» (`plan_week.py:112-121`).
   Разрешить заполнение **отсутствующего** ключа в рантайме (как уже делает операторский скрипт)?
2. Прогонять ли `backfill_multi_program.py` (нормализацию) на staging сейчас как немедленный repair — после
   SQL §0.4? (Это операторское действие, не код; скрипт также enrolls всех онбордившихся без плана —
   `FUNCTIONAL_AUDIT_WAVE_1.md:438`.)
3. Можно ли иметь две активные инклюзии одного курса (T7)?
4. Должна ли legacy-тренировка в боте влиять на готовность/прогрессию v2 до cutover?

---

## 15. ТЕСТЫ И СИДЫ, СОЗДАЮЩИЕ СОСТОЯНИЕ НАПРЯМУЮ

`grep "PlanItem(|PlanWeek(|ProgramInclusion(|TrainingPlan("`: `scripts/e2e_seed.py` — **19** мест
(напр. `:294` PlanItem без недели поверх уже созданных `create_inclusion` строк; `:576-595`; `:612`
`TrainingPlan(created_at=now-14d)`; `:634-640`; `:758-762`; `:776`; `:814`; `:932-935`; `:1267`);
тесты — **22 файла**, крупнейшие: `tests/test_web/test_v2_plan_item_management.py` (7),
`test_v2_plan_schedule.py` (5), `test_v2_plan_done_counts.py` (4), `test_v2_mixed_workout.py` (3),
`test_journal_dedupe.py` (3), `tests/test_services/test_plan_week_service.py` (3).

Покрытие формы данных инцидента: `test_plan_week_service.py` всегда передаёт `program_items=...` в хелпер
(`:64-77`; `program_items=None` используется только «где тест специально проверяет legacy»), но **нет ни одного
теста** «legacy-снимок + неделя ≥2 → строки курса». Единственный legacy-тест
(`tests/test_scripts/test_backfill_multi_program.py:414-461`) проверяет, что **скрипт** нормализует снимок, —
то есть закрепляет repair как операторскую процедуру, а не рантайм-инвариант.
