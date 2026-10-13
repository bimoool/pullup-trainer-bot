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

## 4. Старый код на обновлённой схеме (rollback кода)

Стенд: код `develop/current` (`1735cad`, **старый**) поднят `uvicorn`-ом против копии БД, уже прошедшей апгрейд +
convergence (`reh_a4b`), и против исходной старой БД (baseline). 6 пользователей × 38 параметрических-свободных GET.

* Статусы **идентичны** на обеих БД: 35 эндпоинтов × 6 пользователей = 200; 3 эндпоинта (`/api/leaderboard`,
  `/api/profile/body-metrics`, `/api/v2/journal/days`) = 422 одинаково везде (в смоук-вызове не заданы обязательные
  query-параметры; это не следствие схемы).
* Запись старым кодом на новой схеме: `POST /api/v2/sessions` (backdated с упражнением) → 200, `POST` (freeform,
  activity) → 200, `GET /api/v2/sessions` → 200 и новая запись видна, `GET /api/v2/plan` → 200.
* Схема: у существующих таблиц нет новых колонок `NOT NULL` без default (все такие — только в новых таблицах
  `custom_plans`, `exercise_categories`, `session_events`, `workout_definition_versions`), существующие колонки не
  меняли тип/nullability и не удалены.

Не покрыто (честно): live-прохождение V5.6-тренировки и прогрессии старым кодом на преобразованных данных; тесты
старого репозитория против новой схемы (их фикстуры сами создают схему своей головы).

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
* **Побочная находка.** Первый прогон на «сыром» сиде дал 2 дубля сессий (одинаковые `user_id`/`performed_at`): сид
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
