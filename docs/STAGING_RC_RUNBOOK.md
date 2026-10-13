# Staging runbook: release candidate #322 + #323 (PR #324)

**Только подготовка. Ни одна команда этого документа не выполнялась на staging; деплой делает владелец.**

> **Статус готовности: BLOCKER, деплой на staging не разрешён.** (1) CI E2E на кандидате красный (2 из 2 прогонов), причина
> не подтверждена — `docs/STAGING_RC_CI_E2E.md`; (2) HOLD на `converge-history --apply`: случай отредактированных копий
> факультативов — §6.2 и `docs/STAGING_RC_REHEARSAL.md` §8; (3) состояние staging не прочитано — §2.
Доказательства репетиции на изолированной БД — `docs/STAGING_RC_REHEARSAL.md`. Команды общего gate —
`docs/STAGING_RC_GATE.md`.

## 1. Что именно выкатывается

| | |
|---|---|
| Код кандидата (прошёл общий gate) | `ef607c06df8b223684387261db0e17ebbbdda282` |
| Ветка | `claude/vigilant-clarke-xis1u1` (PR #324, draft → `integration/domain-v2`) |
| Состав | BASE `608015948ef94729e73cc55e9261b912b3e039d3` + merge #322 `e3c05f74…` + merge #323 `2eeff57d…` |
| Что может лежать поверх | только коммиты, меняющие **исключительно `docs/`** |

Перед деплоем проверить, что tip ветки не содержит ничего кроме `docs/` поверх кода кандидата:

```bash
git fetch origin claude/vigilant-clarke-xis1u1
git diff --stat ef607c06df8b223684387261db0e17ebbbdda282 origin/claude/vigilant-clarke-xis1u1 -- . ':!docs'   # должно быть пусто
git rev-parse origin/claude/vigilant-clarke-xis1u1                                                          # записать SHA
```

**Принимает ли deploy-wrapper SHA или ветку — не проверено** (скрипт `~/deploy-staging-run.sh` на сервере, в
репозитории его нет). Из репозитория известно: workflow `deploy-staging.yml` принимает input `ref` («Ветка») и
вызывает `./deploy-staging.sh <ref>`; прод-контур принимает только 40-hex SHA (`deploy/deploy-run.sh`). Поэтому
деплоить **именем ветки** и сверить выкаченный SHA по §3.1.

## 2. Что мне известно из репозитория, а что надо прочитать на сервере

Из репозитория (`docker-compose.yml`, `STAGING_SETUP.md`, skill `deploy-and-verify`, `docs/STAGING_QA_HARNESS.md`):
compose-проект `pullup-staging`; сервисы `db`, `redis`, `app` (бот, образ из `Dockerfile`, **содержит `scripts/`**),
`web` (Mini App, `Dockerfile.web`, **без `scripts/`**); каталог `/home/deploy/pullup-trainer-bot-staging`;
порт Mini App 8002; домен `staging.app.bimoool.com`. Всё это — **заявленное, не проверенное на живом сервере**.

Фактическое состояние staging — только этими read-only командами (в веб-консоли сервера или по SSH под пользователем,
у которого есть доступ к docker). **Имена проектов, сервисов, контейнеров и каталогов не угадываются — они берутся из
вывода первой команды.** Не печатать `.env`, `~/.staging-secrets.env`, токены; вывод — без секретов и персональных данных.
На сервере живёт ещё чужой проект (`reeltrack-*`) и прод — выбирать строки, где имя compose-проекта содержит `staging`.

```bash
# 2.1 какие compose-проекты, сервисы и контейнеры запущены (проект / сервис / контейнер / образ / статус)
docker ps --format '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}\t{{.Names}}\t{{.Image}}\t{{.Status}}' | sort
# 2.2 рабочий каталог каждого compose-проекта (из него берётся каталог staging; прод и reeltrack не трогать)
docker ps --format '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}' | sort -u
# 2.3 SHA, на котором лежит код staging (подставить working_dir staging-проекта из 2.2)
git -C <WORKING_DIR_STAGING> rev-parse HEAD
git -C <WORKING_DIR_STAGING> log -1 --format='%H %cI %s'
git -C <WORKING_DIR_STAGING> status -sb | head -n 5
# 2.4 текущая ревизия Alembic (подставить имя контейнера Postgres staging: в 2.1 строка с образом postgres:*)
docker exec <DB_CONTAINER_STAGING> sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'
# 2.5 как устроен деплой: делает ли wrapper миграцию/бэкап, принимает ли SHA (скрипты без секретов; секреты в ~/.staging-secrets.env — не открывать)
cat ~/deploy-staging.sh ~/deploy-staging-run.sh
# 2.6 есть ли механизм бэкапа и место на диске
ls -la ~/backups 2>/dev/null | head -n 20; crontab -l 2>/dev/null | grep -iE 'dump|backup'; systemctl list-timers --all 2>/dev/null | grep -iE 'backup|dump'; df -h / | tail -n 1
```

Дальше в команды §3–§8 подставлять найденные `-p <PROJECT_STAGING>` и имена сервисов из 2.1 (в тексте ниже использованы
`pullup-staging`, `db`, `app`, `web` из `docker-compose.yml` репозитория — **заменить на найденные**).

Пока §2.1–2.6 не выполнены, **факты о staging неизвестны**: стартовую ревизию в §4 нельзя считать установленной.

## 3. Деплой (действие владельца; в рамках этой задачи не выполнялось)

1. Бэкап — §5. Без проверенного бэкапа не продолжать.
2. GitHub → Actions → **Deploy Staging** → `ref` = `claude/vigilant-clarke-xis1u1`.
3. Порядок на стороне wrapper'а **неизвестен** (§2.5). Правило из `deploy-and-verify`: собрать образ → миграции → поднять
   контейнеры. Новый код на старой схеме неработоспособен; старый код на новой схеме работает (§7, доказано на копии).
   Если wrapper не делает миграцию сам:
   ```bash
   docker compose -p pullup-staging run --rm app alembic upgrade head
   ```
4. После деплоя проверить SHA: §2.3 (`git rev-parse HEAD` в каталоге staging) = SHA из §1.

### 3.1 Проверка факта деплоя
```bash
cd /home/deploy/pullup-trainer-bot-staging && git rev-parse HEAD
docker compose -p pullup-staging ps
curl -sf https://staging.app.bimoool.com/health
docker compose -p pullup-staging exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # b5d8e1f3a6c9
```

## 4. Цепочка миграций

Голова кандидата — `b5d8e1f3a6c9`, голова одна, цепочка линейная. Staging находится где-то на ней; **стартовая ревизия
R0 — из §2.4**. Миграции, которые будут применены (в порядке применения):

| # | Ревизия | Что делает | Данные |
|---|---|---|---|
| 1 | `c3f7a9e2d5b1` | `programs.access_level` (бесплатный курс «Подтягивания») | UPDATE access_level |
| 2 | `b7d2e9f4a1c3` | WorkoutDefinition v2: версии, идентичность упражнений, переписанный системный контент (#303) | backfill + контент |
| 3 | `d8a3c6f1e2b4` | Program + Plan v2: occurrences, кредит сессии, констрейнты, custom plans (#304) | backfill |
| 4 | `f4c1a7e9b3d2` | TrainingSession v2: источники, идентичность, prescription snapshot, длительность (#307) | backfill (kind/origin/…) |
| 5 | `a9e6c3d1f5b7` | Live Engine v2: колонки состояния движка + `session_events` (#306) | нет |
| 6 | `a7e2c5b9d1f4` | Единая история: `legacy_id`, `superseded_*`, индексы (#308) | только колонки |
| 7 | `e3b9c5d7a2f1` | Course prescription (#305): `status` varchar(32), `prescription_provenance`, **backfill `block_b.work_sets`** | UPDATE `progression_state` |
| 8 | `b5d8e1f3a6c9` | V5.6: `technique_valid`, `rest_within_limit` в `session_blocks` | нет |

Для R0 выше начала таблицы применяется только хвост, начиная со следующей за R0 ревизии. Проверить точный хвост до
деплоя (БД не нужна):

```bash
docker compose -p pullup-staging run --rm app alembic history -r <R0>:head
```

Если R0 нет в таблице выше — **стоп**: цепочка staging отличается от рассмотренной, репетицию надо повторить с реальной R0.

`e3b9c5d7a2f1` — единственная миграция, меняющая существующее значение (`program_inclusions.progression_state`):
**разрешено** только `block_b.work_sets`: отсутствует / `null` → `4` у записей, где `block_b` — объект. Любое другое
существующее значение (в репетиции: `3`, `5`) сохраняется. Миграция не аддитивна в строгом смысле CLAUDE.md
(UPDATE существующих данных), её `downgrade()` backfill не откатывает.

## 5. Бэкап и проверка восстановления (до деплоя)

Механизм бэкапа в репозитории не описан — §2.6 покажет, есть ли он на сервере. Минимум:

```bash
mkdir -p ~/backups && umask 077
TS=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -p pullup-staging exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > ~/backups/staging-pre-rc-$TS.dump
sha256sum ~/backups/staging-pre-rc-$TS.dump; ls -l ~/backups/staging-pre-rc-$TS.dump
# дамп читается и непустой:
docker compose -p pullup-staging exec -T db pg_restore -l < ~/backups/staging-pre-rc-$TS.dump | wc -l
```

Проверка восстановления в **отдельную** БД (не трогает рабочую; перед этим убедиться, что хватает диска, §2.6):

```bash
docker compose -p pullup-staging exec -T db sh -c 'createdb -U "$POSTGRES_USER" restore_check'
docker compose -p pullup-staging exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d restore_check --no-owner' < ~/backups/staging-pre-rc-$TS.dump
docker compose -p pullup-staging exec -T db sh -c 'psql -U "$POSTGRES_USER" -d restore_check -Atc "select version_num from alembic_version"'   # = R0
docker compose -p pullup-staging exec -T db sh -c 'dropdb -U "$POSTGRES_USER" restore_check'
```

## 6. Проверки «старых» данных

### 6.1 До деплоя (только счётчики, без персональных данных)

```sql
-- снять и сохранить: counts_before.txt
select 'users', count(*) from users
union all select 'subscriptions', count(*) from subscriptions
union all select 'program_inclusions', count(*) from program_inclusions
union all select 'workouts (legacy)', count(*) from workouts
union all select 'elective_workouts', count(*) from elective_workouts
union all select 'training_sessions', count(*) from training_sessions
union all select 'session_blocks', count(*) from session_blocks
union all select 'set_logs', count(*) from set_logs
union all select 'plan_weeks', count(*) from plan_weeks
union all select 'plan_items', count(*) from plan_items;
-- какие значения work_sets сейчас (что именно изменит e3b9c5d7a2f1):
select jsonb_typeof(progression_state->'block_b') as block_b,
       coalesce((progression_state->'block_b'->'work_sets')::text, 'ABSENT') as work_sets, count(*)
from program_inclusions group by 1, 2 order by 1, 2;
-- хэш неизменяемых данных (должен совпасть после): initial_progression_state и started_at
select md5(string_agg(id::text||'|'||initial_progression_state::text||'|'||started_at::text, ',' order by id)) from program_inclusions;
```

Дополнительно, **если R0 ≥ `a7e2c5b9d1f4`** (есть `legacy_id`): неспаренные копии факультативов — риск дублей, см. §9.

```sql
select origin, count(*) as sessions, count(legacy_id) as keyed from training_sessions where source = 'elective' group by 1;
```

### 6.2 Convergence (после миграции, до того как владелец откроет «Планы» на новом билде)

> **HOLD: `--apply` обоих скриптов на staging не выполнять**, пока владелец не решит случай отредактированных копий
> факультативов (`docs/STAGING_RC_REHEARSAL.md` §8). Разрешены только dry-run'ы и pre-check ниже. Для факультативов, записанных
> до плана (хронология прода), в репетиции дубль не возникает; граничный случай (электив не старше плана при неключевой копии)
> создаёт дубль/воскрешает удалённое.
>
> Pre-check (read-only; после миграции `f4c1a7e9b3d2`, колонка `origin` есть; до неё заменить условие на `ts.source = 'elective'`).
> Ожидается `0`; `> 0` — HOLD остаётся, нужен фикс или ручное решение по этим пользователям:
> ```sql
> select count(*) from elective_workouts e join training_plans tp on tp.user_id = e.user_id
> where e.created_at >= tp.created_at
>   and exists (select 1 from training_sessions ts where ts.user_id = e.user_id and ts.origin = 'legacy_elective' and ts.legacy_id is null);
> ```
> Второй индикатор — dry-run `--converge-history`: «копий факультативов создано: N» при ненулевом «копий факультативов без пары
> оставлено как есть» — разобрать до `--apply`.

Запускать на сервисе `app` (в `web` нет `scripts/`). Для каждого скрипта — dry-run → apply → повторный apply.

```bash
C='docker compose -p pullup-staging run --rm app'
$C python scripts/repair_plan_convergence.py --all                > conv_dry.json   # dry-run; ничего не пишет
$C python scripts/repair_plan_convergence.py --all --apply        > conv_apply1.json
$C python scripts/repair_plan_convergence.py --all --apply        > conv_apply2.json   # total_mutations == 0
$C python scripts/backfill_multi_program.py --converge-history                > hist_dry.txt     # dry-run
$C python scripts/backfill_multi_program.py --converge-history --apply        > hist_apply1.txt
$C python scripts/backfill_multi_program.py --converge-history --apply        > hist_apply2.txt  # только «без изменений»
```

Не запускать `backfill_multi_program.py` без `--converge-history` (это полный backfill плана, не сведение истории).
Критерии остановки: ненулевой `guard_violations` или код выхода 4 у `repair_plan_convergence.py`; `total_mutations != 0`
в `conv_apply2`; в `hist_apply2` есть «создано»/«привязано».
`dry-run` совпадает с первым `apply` по счётчикам (в репетиции: 55 = 55). Заметки владельца по одному аккаунту:
`--telegram-id <ID>` вместо `--all`; BEFORE/AFTER снимок — `scripts/qa_state_snapshot.py --telegram-id <ID>`
(read-only), порядок и ожидания — `docs/STAGING_CONVERGENCE_RUNBOOK.md`.

### 6.3 Допустимый diff «до → после» (всё остальное должно остаться без изменений)

| Область | Допустимо | Недопустимо |
|---|---|---|
| `alembic_version` | R0 → `b5d8e1f3a6c9` | другая голова |
| `program_inclusions.progression_state` | только `block_b.work_sets`: отсутствует/`null` → `4` | любой другой ключ; изменение явных значений (`3`, `5`, …) |
| `program_inclusions.initial_progression_state`, `started_at`, `snapshot` | без изменений (хэш из §6.1 совпадает) | любое изменение |
| `program_inclusions` — новые колонки | `status`, `sequence_cursor`, `completed_main_sessions`, `prescription_provenance`, … | — |
| `plan_items` | + строки-occurrences; у **текущей/будущей** недели: легаси-агрегат получает `plan_week_id`, `status='removed'` (не удаляется), `count_per_week` развёрнутого агрегата уменьшается | изменение или удаление строк **прошлых** недель; уменьшение числа строк |
| `plan_weeks` | + недели (`past_gap_empty` и т.п.) | удаление |
| `training_sessions` | + нативные копии legacy-тренировок/факультативов (`origin = legacy_*`, `legacy_id`); у существующих копий `legacy_id` NULL → значение при точном совпадении | изменение существующих колонок; `superseded_at` у существующих; дубли `(origin, legacy_id)` |
| `session_blocks`, `set_logs` | + строки копий | изменение существующих |
| `users`, `subscriptions`, `pending_payments`, `workouts`, `blocks`, `workout_sets`, `baselines`, `elective_workouts`, `*_archive_*`, `achievements`, `coins`, `user_body_metrics` | без изменений | любое изменение |
| Новые таблицы | `custom_plans`, `exercise_categories`, `session_events`, `workout_definition_versions` | — |

Проверки после (должны быть «0 строк»):
```sql
select origin, legacy_id, count(*) from training_sessions where legacy_id is not null group by 1,2 having count(*) > 1;   -- дубли копий
select md5(string_agg(id::text||'|'||initial_progression_state::text||'|'||started_at::text, ',' order by id)) from program_inclusions; -- = §6.1
```
И счётчики из §6.1 — ни один не должен уменьшиться; `users`, `subscriptions`, `workouts`, `elective_workouts` — равны.

## 7. Проверка продукта

После §3.1 и §6.2: smoke `/health`, затем чек-лист на реальном iPhone из `docs/IPHONE_QA_CHECKLIST.md`
(staging-бот, **не прод**) плюс:

- **#323:** подписи полей онбординга и формы входов курса видны целиком, клавиатура не закрывает поле/кнопку;
  объяснение помощи/веса сразу после замера; категории на Главной/в поиске — человеческие подписи;
  карточка V5.6 в каталоге — «Основные тренировки · 2 в неделю»; имена блоков в Журнале («Объём A», «Сила A (5×5)»);
  просроченный платный курс — за гейтом, бесплатные «Подтягивания» доступны.
- **#322:** V5.6-тренировка до конца → Summary показывает реальный итог; «Завершить досрочно» → «Прогрессия не
  пересчитана — сессия завершена досрочно.», в журнале одна запись; обрыв сети на завершении (авиарежим на
  финальном подходе) → нет дублей, Summary нейтральный, очередь доотправляется сама.
- **Старые пользователи:** AFTER-снимки владельца и 1–2 «старых» аккаунтов (`qa_state_snapshot.py`) против BEFORE:
  таблица §6.3; «Планы» не «0 из 0»; история Журнала та же.
- Платформа Telegram (safe area, Back, closing confirmation, wake lock) — только на устройстве.

## 8. Rollback

Критерии: падение миграции; `guard_violations`/exit 4; нарушение таблицы §6.3; FAIL в §7.

**Три разных пути — не смешивать:**

1. **Код.** Actions → Deploy Staging → `ref` = предыдущий ref/SHA из §2.3. Старый код на обновлённой схеме проверен на
   копии (`docs/STAGING_RC_REHEARSAL.md` §4, валидные параметры): 20/20 GET → 200; старый код стартует, ведёт и завершает
   live-сессию, пишет запись в Журнал. **Чисто — только до convergence:** после апгрейда без convergence «Планы» старого
   кода идентичны исходным; **после convergence старый код показывает задвоенные строки плана** (в репетиции 4→7, 2→5 строк
   plan-items), потому что не знает `plan_items.status = 'removed'`. Точка невозврата для чистого отката кода — первое
   открытие «Планов» новым билдом (`GET /plan` сам делает convergence) или `--apply`. После неё откат кода = путь 3.
   Не проверено: live-прохождение V5.6/STEP-тренировки старым кодом и реальные данные staging.
2. **Схема (`alembic downgrade <R0>`).** Выполнима (в репетиции exit 0), но **это не восстановление данных**:
   после downgrade остаются +19 `plan_items`, +3 `plan_weeks`, +3 копии в `training_sessions`, `work_sets = 4` и т.д.
   (`docs/STAGING_RC_REHEARSAL.md` §5). Использовать только вместе с восстановлением данных, не вместо него.
3. **Данные — `pg_restore` из дампа §5.** Единственный путь вернуть данные в состояние R0; проверен круговой
   дамп→восстановление (идентичность посчитана построчно). Теряет всё записанное после снятия дампа.
   ```bash
   docker compose -p pullup-staging stop app web
   docker compose -p pullup-staging exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
   docker compose -p pullup-staging exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < ~/backups/staging-pre-rc-<TS>.dump
   docker compose -p pullup-staging exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # = R0
   # затем деплой предыдущего кода (путь 1) и повтор §6.1 — счётчики равны «до»
   ```
   Деструктивно: выполнять только по решению владельца. Redis (FSM бота) дамп не затрагивает.

## 9. Известные риски и открытые вопросы

- **Staging не читался** (нет доступа): R0, SHA, имена сервисов, поведение wrapper'а, наличие бэкапа — не установлены (§2).
- **Неспаренные копии факультативов.** `converge-history` связывает существующую копию факультатива с legacy-строкой
  только по **точному** совпадению `(performed_at, блоки)`. Копия, отредактированная в Журнале, не спарится: если
  факультатив записан после создания плана — будет создана вторая копия (дубль в Журнале); если до — попадёт в
  `ambiguous_elective_without_copy` и не воскрешается. На репетиции с копиями, созданными штатным backfill'ом старого
  кода, дублей нет; на сидах, записанных иначе, — есть. Перед apply — запрос из §6.1 и просмотр `hist_dry.txt`.
- **Миграция `e3b9c5d7a2f1` неаддитивна** (UPDATE) — это уже в BASE, не в #322/#323; решение владельца.
- **CI E2E.** См. PR #324: E2E-job на SHA кандидата красный; причина по логам не установлена (§ статус в PR).
