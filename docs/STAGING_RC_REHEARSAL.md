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

