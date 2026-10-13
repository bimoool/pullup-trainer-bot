# Репетиция миграции кандидата #322 + #323 на изолированной БД

Кандидат: код `ef607c06df8b223684387261db0e17ebbbdda282` (PR #324). Команды deploy на staging **не выполнялись**; реальный
staging не читался (нет доступа) — см. `docs/STAGING_RC_RUNBOOK.md` §2. Всё ниже — **синтетические данные** на
локальном Postgres 16 (порт 54329, отдельный кластер). Это доказывает поведение кода на репрезентативной «старой» БД,
но **не** доказывает, что реальные данные staging ведут себя так же.

## 1. Как собрана «старая» БД

Стартовая ревизия реального staging неизвестна, поэтому репетиция прогнана с двух стартов на одной линейной цепочке
(`alembic history -r <R0>:head` из кода кандидата подтверждает, что обе ревизии на ней):

| Старт | Откуда | Миграций до head |
|---|---|---|
| `a4c8e1f7b2d9` | head `develop/current` `1735cad` — самая старая из рассмотренных голов, на которой мог остаться staging | 8 |
| `a7e2c5b9d1f4` | head `integration/domain-v2` `3758a88` | 2 |

«Старая» БД на `a4c8e1f7b2d9` построена **кодом `develop/current`**: схема — его Alembic, данные — его сиды
(`scripts/e2e_seed.py`, 14 сценариев: legacy-тренировки, факультативы, планы/инклюзии STEP, подписки, v2-сессии и т.д.),
плюс граничные случаи `block_b.work_sets` через SQL:

| inclusion | `block_b.work_sets` до |
|---|---|
| 2, 4–6 (и пустые `{}`) | отсутствует |
| 3 | JSON `null` |
| 7 | `3` |
| 8 | `5` |

Две v2-копии факультативов, записанные сидом нештатно, заменены копиями, созданными **штатной функцией backfill
старого кода** (`_create_training_session_for_elective` из `develop/current`): см. §6. База не изменялась после
заморозки; каждая репетиция идёт в `CREATE DATABASE … TEMPLATE <замороженная копия>`.

Размер: 47 таблиц, 1179 строк до; 14 users, 14 subscriptions, 6 legacy workouts, 12 blocks, 14 workout_sets,
14 baselines, 2 elective_workouts, 230 training_sessions, 24 plan_items, 9 plan_weeks, 8 inclusions.

## 2. Последовательность и результат (одинакова для обоих стартов)

`docs/rehearsal/rehearse.sh <source_db> <tag>` (снимок `docs/rehearsal/dbsnap.py` — построчные md5 по колонкам, значения не печатаются):

| Шаг | Старт `a4c8…` | Старт `a7e2…` |
|---|---|---|
| before-снимок | rev `a4c8e1f7b2d9`, 47 таблиц, 1179 строк | rev `a7e2c5b9d1f4`, 51 таблица, 1200 строк |
| `alembic upgrade head` | exit 0, 8 миграций → `b5d8e1f3a6c9` | exit 0, 2 миграции → `b5d8e1f3a6c9` |
| `repair_plan_convergence.py --all` (dry-run) | exit 0, 55 мутаций, `guard_violations` 0; снимок до/после **идентичен** | то же |
| `… --all --apply` | exit 0, 55 мутаций (= dry-run), `guard_violations` 0 | то же |
| `… --all --apply` (повтор) | exit 0, **0 мутаций** | то же |
| `backfill_multi_program.py --converge-history` (dry-run) | exit 0; снимок до/после **идентичен** | то же |
| `… --converge-history --apply` | exit 0: привязано 5, создано 3, без изменений 3 | то же |
| `… --converge-history --apply` (повтор) | exit 0: «копий без изменений: 6», ничего нового | то же |

Счётчики convergence (apply): `plan_weeks_created` 3, `plan_items_attached_to_week` 12, `plan_items_created` 19,
`aggregates_frozen` 3, `aggregates_retired` 10, `manual_rows_converted` 8, `snapshot_repairs` 0, `session_credits_linked` 0.

## 3. Итоговый diff before → after (старт `a4c8…`)

```
plan_items: 24 -> 43; new cols …; count_per_week: 3 rows changed; plan_week_id: 12 rows changed
plan_weeks: 9 -> 12
program_inclusions: new cols …; progression_state: 2 rows changed
session_blocks: 227 -> 233        set_logs: 457 -> 484        training_sessions: 230 -> 233
новые таблицы: custom_plans (0), exercise_categories (11), session_events (0), workout_definition_versions (10)
остальные таблицы (users, subscriptions, workouts, blocks, workout_sets, baselines, elective_workouts,
  achievements, coins, user_body_metrics, …): без изменений — ни одной изменённой строки
```

Разбор по требованиям задачи:

* **`e3b9c5d7a2f1`.** `progression_state` изменён ровно у 2 строк, и в них изменился только один ключ:
  `block_b.work_sets: ABSENT → 4` (inclusion 2) и `null → 4` (inclusion 3). Явные `3` (inclusion 7) и `5` (inclusion 8)
  сохранены; остальные ключи состояния и `initial_progression_state` не тронуты. Повторный запуск data-шагов даёт 0 изменений.
* **Исторические sessions/snapshots.** Ни одна существующая колонка `training_sessions`, `session_blocks`, `set_logs`
  не изменилась (diff показывает только новые колонки и добавленные строки); ни одна строка не пропала.
  `program_inclusions.snapshot`, `started_at`, `initial_progression_state` не изменены.
* **Прошлые PlanItems.** 15 существующих `plan_items` изменены (12 получили `plan_week_id`, 3 — `count_per_week` 2→1
  при развёртывании агрегата в occurrences); **все они в текущей неделе** (`start_date` 2026-10-12 при «сегодня»
  2026-10-13), строки недель с `start_date + 6 < today` не изменялись. Строки не удалены (агрегаты → `status='removed'`).
* **Версии/расписание legacy.** Legacy-таблицы (`workouts`, `blocks`, `workout_sets`, `baselines`, `elective_workouts`)
  и `programs.config` не менялись; новые колонки `programs` (`access_level`, `slots`, `frequency`, …) заполнены миграциями.
* **Подписки, счётчики.** `subscriptions` 14 → 14, `users` 14 → 14, `workouts` 6 → 6, `blocks` 12 → 12,
  `elective_workouts` 2 → 2, построчные хэши не изменились.
* **Дубли истории.** `(origin, legacy_id)` — 0 дублей (на уровне БД есть уникальный индекс). Нативные копии после apply: `legacy_backfill` 6 (все с ключом: 3 привязаны к существовавшим, 3 созданы),
  `legacy_elective` 2 (обе существовавшие копии привязаны к своим legacy-строкам, новых не создано; §6).

Старт `a7e2…` — те же счётчики; дополнительно меняются уже существовавшие колонки Plan v2 (`sequence_cursor`,
`completed_main_sessions`, `status`, `occurrence_index`, … — convergence их заполняет) и `training_sessions.legacy_id`
у 5 строк (привязка).

## 4. Старый код на обновлённой схеме (rollback кода) — повторная проверка с корректными параметрами

Первая версия этой проверки опиралась на 422 из-за отсутствующих query-параметров, и это ничего не доказывало.
Повтор (`docs/rehearsal/rollback_api_check.py`): код `develop/current` (`1735cad`, старый) поднят против (A) исходной старой
БД и (B) копии после апгрейда + convergence; 7 авторизованных пользователей; 20 GET **с валидными параметрами** (в том числе
`/api/leaderboard?metric=max_reps`, `/api/profile/body-metrics?metric=weight_kg`, `/api/v2/journal/days?month=…`,
`/api/v2/analytics/training?from&to`, `/api/v2/sessions?status=completed`, `/api/v2/plan`, `/api/v2/plan-items`).

* **Чтения:** 20/20 эндпоинтов отвечают 200 на A и на B для всех 7 пользователей (0 не-200).
* **Записи старым кодом** (пользователь 880011, своя тренировка, на A и на B каждый на своей копии): `POST /sessions/live`
  (старт свободной сессии) → 200; `sets:batch` (2 подхода) → 200; `complete` → 200, `status=completed`; запись в Журнал
  (`POST /sessions`, backdated) → 200; после этого завершённых сессий 0 → 2 и сумма в `journal/days` = 2 — **одинаково на A и на B**.
* **Но видимое различие в «Планах».** Старый код не знает `plan_items.status` и показывает строки, которые convergence пометила
  `removed` (легаси-агрегаты), вместе с новыми occurrences:

| пользователь | старый код, старая схема | старый код, апгрейд **без** convergence | старый код, апгрейд **+ convergence** |
|---|---|---|---|
| 880004 | строк плана 8, plan-items 4 | 8 / 4 (**без изменений**) | **11 / 7** |
| 880006 | 4 / 2 | 4 / 2 | **7 / 5** |
| 880007 | 3 / 3 | 3 / 3 | **4 / 4** |

Вывод для rollback: **откат только кода чисто безопасен до применения convergence** (схема после апгрейда старому коду не
мешает и план не меняется); **после convergence откат кода без восстановления данных даёт задвоенные строки плана** в старом
интерфейсе. Первое же открытие «Планов» новым кодом выполняет ту же convergence (`GET /plan`), т.е. точка невозврата для
чистого отката кода — первое открытие «Планов» новым билдом или `--apply` скрипта. Новых `NOT NULL` без default у существующих
таблиц нет, существующие колонки не менялись.

Не покрыто: live-прохождение V5.6-тренировки (курс/STEP) и прогрессия старым кодом на преобразованных данных; тесты
старого репозитория против новой схемы (их фикстуры создают схему своей головы). Замечание: БД-источник `old_a4b` получила
записи §4 (2 сессии пользователя 880011) **после** всех копий для §2/§3/§5; в баз­овой репетиции они не участвуют.

## 5. `alembic downgrade` — не восстановление данных

На копии после апгрейда + convergence: `alembic downgrade a4c8e1f7b2d9` → exit 0, `alembic current` = `a4c8e1f7b2d9`,
ошибок нет. Но снимок против оригинала **не совпадает**:

```
plan_items: 24 -> 43 (+19); count_per_week: 3 rows changed; plan_week_id: 12 rows changed
plan_weeks: 9 -> 12
program_inclusions.progression_state: 2 rows changed    (work_sets остался 4)
session_blocks: 227 -> 234    set_logs: 457 -> 486    training_sessions: 230 -> 235
```
(+2 сессии / +1 блок / +2 лога — запись из §4, выполненная до этой проверки; остальное — следы convergence/backfill.)
Вывод: downgrade откатывает схему, данные convergence и backfill остаются. Для возврата данных — только
`pg_restore` (§5 runbook).

## 6. Восстановление из дампа и неспаренные копии факультативов

* **Дамп → восстановление.** `pg_dump -Fc` исходной БД (до апгрейда) → `pg_restore --no-owner` в пустую БД: exit 0,
  0 строк stderr, построчный снимок **идентичен** оригиналу (47 таблиц, 1179 строк, rev `a4c8e1f7b2d9`).
* **Предыстория.** Первый прогон на «сыром» сиде дал 2 дубля сессий (одинаковые `user_id`/`performed_at`): сид
  записал копии факультативов не штатным путём, `converge-history` связывает копию с legacy-строкой только при
  **точном** совпадении `(performed_at, блоки)` (`app/services/legacy_history_convergence.py::_converge_electives`) и
  создал вторую. После замены этих копий копиями из **штатного backfill старого кода** — `привязано 5, создано 3`, дублей
  нет. Следствие для реального staging: копии факультативов, отредактированные в Журнале до convergence, не
  спарятся (дубль, если факультатив записан после создания плана; иначе `ambiguous_elective_without_copy`). Это
  поведение кода BASE, не #322/#323; проверка перед apply — runbook §6.1/§9.

## 7. Что репетиция не доказывает

* Реальные данные staging, реальную стартовую ревизию, поведение deploy wrapper'а, наличие и объём бэкапа.
* Объём/время на данных реального размера (БД репетиции — 1179 строк; VPS 1 vCPU / 1 GB RAM).
* Playwright против этой БД и Telegram/iPhone-проверки (отдельно: общий gate, runbook §7).

## 8. Отредактированные копии факультативов (отдельная фикстура)

Требование: не заменять отредактированную копию нетронутой; создать копию штатным backfill старого кода, править штатным
путём, затем новая convergence. Фикстура — `docs/rehearsal/edited_copy_fixture.py` (строит **старым** кодом), правки —
`docs/rehearsal/edited_copy_api.py` через **старое API**, весь прогон — `docs/rehearsal/edited_copy_run.sh`.

Каждый пользователь: «мигрированный» (3 legacy-тренировки + копии, план `TrainingPlan`) + 4 факультатива, у каждого копия создана
`_create_training_session_for_elective` **старого** backfill. Правки через `PATCH`/`DELETE /api/v2/sessions/{id}` старого API (все 200/204):
E1 — значение подхода 15→20; E2 — перенос даты на вчера; E3 — не тронут (контроль); E4 — копия удалена.

* **Пользователь A** (770001, хронология прода: факультативы записаны за 30 дней до плана, план создан при миграции).
* **Пользователь B** (770002, граничный: `elective.created_at` не раньше `plan.created_at`; в проде не ожидается — старый код
  копий при записи не создавал, новый создаёт сразу с ключом).

Результат `converge-history` (dry-run = apply; повторный apply — только «без изменений»):

| | A | B |
|---|---|---|
| E3 (нетронутый) | связан (`legacy_id` = id электива) | связан |
| E1, E2 (отредактированные) | **не пересозданы**, остаются без ключа (`legacy_id` NULL), «без пары оставлено как есть» | **созданы вторыми копиями (дубль)** |
| E4 (копия удалена) | **не воскрешён** («неоднозначно», `ambiguous_elective_without_copy`) | **воскрешён** (создан заново) |
| `sessions_completed` старый API → новый API | 6 → 7 (+1 — post-migration legacy-тренировка стала нативной) | 6 → **10** (+1 такая же, **+3 дубля/воскрешение**) |
| `journal/days` (сентябрь/октябрь), `profile`, `history` | **идентичны** | октябрь: день 13: 6 → **9**; `workouts_count` 7 → **10** |
| `analytics`: `total_workouts` / `sessions_last_30_days` | 6 → 7 | 6 → **10** |

**Минимальный repro дубля** (пользователь B): пользователь с `TrainingPlan`, факультатив с `created_at >= plan.created_at`,
у которого есть неключевая (`legacy_id IS NULL`) копия `origin='legacy_elective'`, отредактированная в Журнале (значение или
дата) или удалённая → `scripts/backfill_multi_program.py --converge-history --apply` создаёт новую копию
(`_converge_electives`: точное совпадение `(performed_at, блоки)` не находится, ветка «факультатив старше плана → не
воскрешать» не срабатывает, потому что `elective.created_at < plan_created_at` ложно).

**Почему A безопасен, а B нет:** защита опирается на `TrainingPlan.created_at` (косвенный признак «электив записан до миграции»),
а не на факт существования неключевой копии.

**Scope fix (не применён):** `app/services/legacy_history_convergence.py::_converge_electives` — заменить условие
`elective.created_at < plan_created_at` на признак по копиям: у пользователя есть неключевая копия `legacy_elective`, созданная
не раньше `elective.created_at` (`copy.created_at >= elective.created_at`) → считать электив «неоднозначным» и не создавать копию.
~5 строк + тест на repro (3 случая: правка значения, перенос даты, удаление). Решение и срок — за владельцем.

**До разрешения этого случая convergence на staging не применять** (runbook §6.2 HOLD).

### Фикс (PR #326, ветка `claude/zealous-archimedes-5mnn41` → `claude/vigilant-clarke-xis1u1`)

`app/services/legacy_history_convergence.py::_converge_electives`. Признак «уже перенесён» — не догадка по дате, а
**инвариант штатных писателей**, проверенный запуском самого старого backfill (`docs/rehearsal/old_backfill_created_at.py`
на коде `4298f8b` — фактический staging — и `1735cad`):

```
backfill #1: 1 migrated          plan id=1 created_at=…19:41:32.929275   ← одна транзакция:
  session(freeform)  created_at=…19:41:32.929275                          план, копия тренировки
  session(elective)×2 created_at=…19:41:32.929275                          и обе копии факультативов
  elective id=1,2    created_at=…19:41:32.846 / .862  (раньше плана)
elective #3 (после) + backfill #2: 0 migrated, 1 already migrated — копии у #3 нет
ALL COPIES created_at == plan.created_at: True        (то же на 1735cad)
```

Плюс по коду всех трёх версий (`1735cad`, `4298f8b`, кандидат): `TrainingPlan` уникален на пользователя
(`UNIQUE user_id`), создаётся backfill'ом в транзакции копий или `get_or_create_for_user` (экран «Планы»), **путей
удаления нет** (только `ON DELETE CASCADE` от `users`, вместе с факультативами); backfill пропускает пользователя с
планом целиком; `--truncate` стирает планы и сессии вместе и переимпортирует.

Правила (для факультатива без копии с ключом):

1. **История не объяснима штатными писателями** → guard на пользователя: **ни одной** привязки и новой копии
   факультатива, всё в отчёт (`nonstandard_copy_history`, `evidence`). След (читается до записей прогона):
   * план есть: копия без ключа **вне транзакции плана**, не являющаяся точной копией факультатива «после плана» не
     старше неё (такой бывает копия сведения/dual-write, потерявшая ключ при `alembic downgrade a7e2c5b9d1f4`);
   * плана нет: копия без ключа (кроме такой же точной копии) или копия с ключом, созданная позже своей legacy-строки.
   Guard ничего не меняет, поэтому повтор видит те же следы (стабилен).
2. Точная копия `(performed_at, блоки с note)` не старше факультатива → привязка (как раньше).
3. Факультатив **не позже плана** → копия не создаётся, ничего не привязывается: `backfilled_copy_edited_or_deleted`,
   если уцелела копия из транзакции плана, иначе `pre_migration_without_copy` (перенос доказан только планом: удалены
   все копии — или план создан экраном «Планы» до импорта, и тогда факультатив не импортировался никогда; это не
   различить — поэтому unresolved, а не копия).
4. Точная копия есть, но старше факультатива → `exact_copy_predates_elective`, ни привязки, ни второй копии.
5. Иначе (после плана; или плана нет и следов нет) → копия создаётся (первый импорт: по инварианту backfill такой
   факультатив не переносил). Создание у пользователя **без плана** отчёт помечает отдельно («по инварианту «нет плана
   — backfill не проходил»»), не выдавая его за доказательство.

Прочее: dry-run видит копии без origin (dry-run = apply); `--converge-history` печатает «Не разрешено (копия НЕ
создана, ничего не привязано): N» по строке на факультатив (причина, кандидаты — копии без ключа того же формата не
старше факультатива, только для ручной проверки; `evidence` для guard'а). По времени, повторам или сумме ничего не
связывается.

**Штатно ли «удалены все копии и нет подходящего плана»? Нет.** Старое API удаляет копии (204), план остаётся
(`plans after old API: 2`), а у каждого перенесённого факультатива `created_at <= plan.created_at` навсегда. «Плана нет»
или «план новее перенесённого факультатива» получается только нештатно (ручной SQL, сиды `e2e_seed.py` с явным
`created_at`, ручной фикс миграции до Checkpoint 1).

**Пробел, который без маркера не закрыть.** Нештатная история, у которой **не осталось ни одного следа** (удалены все
копии И план, или копии были без плана и все удалены), в БД побайтно совпадает с пользователем, которого backfill не
импортировал никогда — а такому первый импорт обязан создать копии. Тест
`test_traceless_deleted_copies_are_indistinguishable_from_never_imported` фиксирует, что оба получают одинаковый
результат. Закрыть можно только данными, которых в БД нет: (а) подтверждённый владельцем момент(ы) запуска старого
backfill на staging/проде (из логов деплоя) — тогда «онбординг до прогона, а плана нет» станет следом; (б) список
пользователей, затронутых ручным SQL/сидами/ручным фиксом; (в) на будущее — маркер прогона импорта или архив
удалённых копий (старое API удаляло дерево сессии без следа). Дату не придумываю, миграцию не добавляю.

Известная цена guard'а (ложная блокировка, не дубль): после `alembic downgrade a7e2c5b9d1f4` + upgrade у пользователя
**без плана** с legacy-тренировками копии сведения теряют ключ и выглядят как след → его новые факультативы попадут в
«Не разрешено»; отредактированная копия сведения, потерявшая ключ, — тоже. Штатный откат в runbook — `pg_restore`, не
downgrade.

#### Доказательства

Репетиция на **старом коде staging `4298f8b`** (`edited_copy_run.sh <old> [edit|delete-all]`, изолированный Postgres 16):

| | edit (§8), с фиксом | delete-all, с фиксом | delete-all, база `5a84911` |
|---|---|---|---|
| старое API | E1/E2 правка 200, E4 удаление 204 | все 8 копий — 204; планов осталось 2 | то же |
| «копий факультативов создано» dry / apply1 / apply2 | 0 / 0 / 0 | 0 / 0 / 0 | 4 / 4 / 0 (B воскрешён) |
| «Не разрешено» | 6 (E1, E2, E4 × 2) | 8 (`pre_migration_without_copy`) | 4 |
| B: `profile.workouts_count`, journal 13-е | идентичны | идентичны | 4 → 8, 4 → 8 |
| dry-run пишет? | нет (`dbsnap` diff пуст) | нет | — |

Тесты (реальный Postgres): `tests/test_web/test_elective_copy_convergence.py` — 15,
`tests/test_scripts/test_single_history_migration.py` — 4 (в т. ч. downgrade→upgrade и новый
`test_late_elective_copy_outside_the_plan_transaction_is_left_unresolved` — прежняя форма фикстуры с копией 9005 вне
транзакции плана: через сам скрипт — 3 факультатива в «Не разрешено», ни привязки, ни копии). Основная фикстура
оставлена с `created_at` копии 9005 = `created_at` плана — так пишет штатный backfill (вывод выше); поздняя копия —
отдельный тест, правка фикстуры ошибку не прячет. Связанные тесты (все файлы, упоминающие elective/convergence) — 485
passed. Откат: сервис базы `5a84911` — 11 из 19 падают; первая версия фикса `4f87c12` — 4 из 19 (след без плана →
2 копии воскрешены; поздняя копия привязана; отчёт не называет основание первого импорта).

## 9. Репетиция от фактической ревизии staging: `c3f7a9e2d5b1`, старый код `4298f8b`

Владелец сообщил: staging на `4298f8b9727f91d4a150431fd0d9e06131944d27`, Alembic `c3f7a9e2d5b1` (`docs/STAGING_RC_RUNBOOK.md` §1.1).
Всё из §§1–8 повторено с этим стартом; «старая» БД построена **кодом `4298f8b`** (его Alembic `heads` = `c3f7a9e2d5b1`, те же 14 сидов
`e2e_seed.py`, те же граничные `work_sets`, электив-копии заменены копиями штатного backfill этого кода). Данные синтетические.

* **Цепочка:** 7 миграций — `b7d2e9f4a1c3 → d8a3c6f1e2b4 → f4c1a7e9b3d2 → a9e6c3d1f5b7 → a7e2c5b9d1f4 → e3b9c5d7a2f1 → b5d8e1f3a6c9`.
  `alembic upgrade head` exit 0, `alembic current` = `b5d8e1f3a6c9`.
* **Convergence** (`repair_plan_convergence.py --all`): dry-run 55 мутаций, `guard_violations` 0, снимок после dry-run идентичен;
  apply 55; повторный apply **0**. `converge-history`: dry-run ничего не пишет; apply — привязано 5, создано 3; повторный apply — только «без изменений».
* **Diff before → after** — как в §3 (plan_items 24→43, plan_weeks 9→12, training_sessions 230→233, session_blocks 227→233,
  set_logs 457→484; новые таблицы `custom_plans`, `exercise_categories`, `session_events`, `workout_definition_versions`; `programs.access_level` уже была,
  новые колонки `slots/frequency/constraints/assessment`). `e3b9c5d7a2f1`: `work_sets` `ABSENT→4` (inclusion 2), `null→4` (3);
  явные `3` (7) и `5` (8) сохранены; `initial_progression_state`, legacy-таблицы, `subscriptions`, `users` без изменений.
* **Отредактированные копии факультативов** (`edited_copy_run.sh /tmp/…/hd-4298f8b`, правки штатным API `4298f8b`): результат **тот же**, что в §8 —
  пользователь A: дублей нет, 3 электива «неоднозначно» (не воскрешены), journal/profile/history идентичны, +1 сессия (post-migration тренировка);
  пользователь B (граничный): +3 дубля/воскрешение (journal день 13: 6→9, `workouts_count` 7→10).
* **Откат кода (старый код `4298f8b`)** на трёх состояниях БД, 20 GET с валидными параметрами и записи: 20/20 → 200 на старой схеме и после
  апгрейда+convergence; live start/sets/complete и запись в Журнал — 200 на обеих. «Планы» старого кода: после апгрейда **без** convergence
  идентичны (880004: 8/4, 880006: 4/2, 880007: 3/3 строк плана/plan-items); **после convergence** задвоены (11/7, 7/5, 4/4).
* **`alembic downgrade c3f7a9e2d5b1`** после convergence: exit 0, схема откатилась, данные нет (plan_items +19, plan_weeks +3, training_sessions +3,
  `work_sets=4`, `plan_week_id` у 12 строк) — **не восстановление данных**.
* **`pg_dump -Fc` → `pg_restore --no-owner`** в чистую БД: exit 0, 0 строк stderr, 427 записей оглавления, построчный снимок идентичен.
* **Побочное наблюдение:** старый код `GET /api/v2/plan` сам пишет в БД (создаёт недостающую неделю плана, расставляет `plan_week_id`) — поэтому
  сравнения «до» нужно брать из снимка, сделанного до любого чтения старым API (так и сделано: `reh_c3/before.json`).

Не доказано: реальные данные staging (размер, форма `progression_state`, состав факультативов), поведение `deploy-staging-run.sh`,
память VPS при сборке образов, и два ожидаемых исправления (IDB-ворота; случай отредактированных копий) — они в этом
репозитории не реализованы, проверки с ними не выполнялись.

## 10. Проверки под фактический `deploy-staging-run.sh` (из строк, присланных владельцем)

Скрипт: `git fetch; git checkout "$branch"; git pull --ff-only; docker compose -p pullup-staging build app web;
docker compose -p pullup-staging run --rm app alembic upgrade head; docker compose -p pullup-staging up -d; healthcheck :8002/health`.
Скрытые строки скрипта не проверены.

* **Миграция атомарна (инъекция отказа).** На копии БД `c3f7a9e2d5b1` заранее добавлена колонка `session_blocks.technique_valid`, чтобы
  последняя ревизия `b5d8e1f3a6c9` упала: `alembic upgrade head` → exit 1 (`DuplicateColumnError`), в логе видны «Running upgrade» всех 7
  ревизий, но `alembic_version` остался `c3f7a9e2d5b1`, таблиц `workout_definition_versions` и `session_events` нет, колонки
  `plan_items.status` нет — **откатились все шесть предыдущих**. Причина: один `begin_transaction()` в `env.py` и PostgreSQL-транзакционный DDL.
* **Старый код на уже обновлённой БД не может выполнить свой `alembic upgrade head`.** `4298f8b` на БД `b5d8e1f3a6c9` →
  `Can't locate revision identified by 'b5d8e1f3a6c9'`, exit 255. На БД после `alembic downgrade c3f7a9e2d5b1` тот же шаг — exit 0
  (и на БД после `pg_restore`, где `alembic_version = c3f7a9e2d5b1`). Следствие: **откат кода тем же wrapper'ом возможен только после
  возврата `alembic_version` к `c3f7a9e2d5b1`** (runbook §3.0 п. 8, §8).
* **Миграция без convergence не меняет счётчики.** Снимок до и сразу после `alembic upgrade head` (reh_c3): ни одна таблица не
  изменила число строк; появились новые колонки/таблицы (`workout_definition_versions` 10 строк, `exercise_categories` 11 — контент миграций)
  и изменена `program_inclusions.progression_state` (2 строки, `work_sets`). Это ожидаемое состояние после шага E (runbook §6.2.0).
* **Дифф конфигурации выката.** `docker-compose.yml`, `Dockerfile`, `Dockerfile.web`, `pyproject.toml`, `alembic.ini` между `4298f8b` и кандидатом
  не изменились; в `app/config.py` добавлена одна настройка с значением по умолчанию. `webapp-frontend/package.json` изменён (+`vitest`),
  `package-lock.json` +405 строк, но `Dockerfile.web` копирует только `package.json` и делает `npm install` → слой npm пересобирается,
  версии резолвятся без lock (в CI — `npm ci` по lock). Это не воспроизводилось и не измерялось (сборка образов в песочнице не выполнялась).

