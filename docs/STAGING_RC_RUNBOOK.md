# Staging runbook: release candidate #322 + #323 (PR #324)

**Только подготовка. Ни одна команда этого документа не выполнялась на staging; деплой делает владелец.**

> **Статус готовности: BLOCKER, деплой на staging не разрешён.**
> 1. Ждём два исправления: **(IDB)** ворота drain-before-projection при сбое чтения IndexedDB и **(legacy convergence)**
>    случай отредактированных/удалённых копий факультативов. Без них деплой не готов; в этом документе они **не** реализованы.
> 2. CI E2E на кандидате красный (2 из 2), причина не подтверждена — `docs/STAGING_RC_CI_E2E.md`.
> 3. `deploy-staging-run.sh` известен только по приведённым владельцем строкам (§3.0); остальные строки скрипта **не считаются
>    проверенными**. Wrapper принимает ветку (не SHA), не делает backup и convergence, старые app/web работают во время миграции —
>    протокол §3 это компенсирует. БД `pullup_staging` — 10 МБ; бэкапа на staging нет — §5 обязателен до любых изменений.
> 4. HOLD на `--apply` convergence — §6.2.

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

**Wrapper принимает ветку и не фиксирует SHA** (§3.0): деплоится то, на что указывает ветка в момент `git pull`. Поэтому деплой идёт
**отдельной замороженной веткой** (§3.1), а не веткой PR #324, которая будет меняться (фиксы, docs).

## 1.1 Фактическое состояние staging (получено от владельца с VPS; я его не читал)

| | |
|---|---|
| Код на staging | `4298f8b9727f91d4a150431fd0d9e06131944d27` — `feat(access): free-forever «Подтягивания» + 7-day minimum-guarantee trial` (2026-10-07); `git status --short` пуст |
| Alembic current (**R0**) | `c3f7a9e2d5b1` |
| Каталог | `/home/deploy/pullup-trainer-bot-staging` |
| Контейнеры | `pullup-staging-app-1`, `pullup-staging-web-1`, `pullup-staging-db-1`, `pullup-staging-redis-1` (проект `pullup-staging`, сервисы `app`, `web`, `db`, `redis`) |
| Диск | свободно 17 ГБ |
| Память | available ≈ 704 МиБ, swap используется |
| Бэкап | в проверенных каталогах **не найден** |
| Скрипты деплоя | `/home/deploy/deploy-staging-dispatch.sh`, `/home/deploy/deploy-staging-run.sh` (содержимое не получено) |

Выводы: `4298f8b` — предок BASE (67 коммитов до `608015948`), его единственная миграция сверх `a4c8e1f7b2d9` — `c3f7a9e2d5b1`
(`alembic heads` на `4298f8b` = `c3f7a9e2d5b1`) → код и схема staging согласованы. До кандидата не хватает **7 миграций** и
всей работы #303–#308/#305, т.е. staging получит очень большой скачок. Тесты на VPS не запускать (память).

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

Команды 2.1–2.4 владелец уже выполнил (§1.1: проект `pullup-staging`, сервисы, SHA `4298f8b`, Alembic `c3f7a9e2d5b1`). **Остаются 2.5**
(содержимое `deploy-staging-dispatch.sh` / `deploy-staging-run.sh`: принимает ли SHA или ветку, делает ли `alembic upgrade`,
где и как собирает образы при ≈ 704 МиБ available) **и размер БД из §5.1**. Бэкапа нет (2.6 проверен в указанных каталогах).

## 3. Деплой (действие владельца; на VPS ничего не запускалось и не запускается без финального разрешения)

### 3.0 Что известно о `deploy-staging-run.sh`

Проверены **только** строки, присланные владельцем (в таком порядке):

```
git fetch origin
git checkout "$branch"
git pull --ff-only origin "$branch"
docker compose -p pullup-staging build app web
docker compose -p pullup-staging run --rm app alembic upgrade head
docker compose -p pullup-staging up -d
healthcheck http://127.0.0.1:8002/health
```

Не проверено (скрытые строки): `set -e`/реакция на ошибку, чтение секретов, очистка (`docker image prune`, `builder prune` — в
репозитории `deploy/post-deploy-cleanup.sh` делает именно это), проверка аргумента. Любой вывод ниже, зависящий от них, помечен.

Следствия (из строк + кода репозитория + репетиции):

1. **Ветка, не SHA.** Деплоится `HEAD` ветки на момент `git pull`; SHA скрипт не проверяет и не печатает.
2. **Нет backup и convergence** — делает владелец вручную (§5, §6).
3. **Старые app/web работают во время `build` и миграции.** Миграция берёт `ACCESS EXCLUSIVE`-блокировки (ALTER TABLE); старый
   бот/Mini App в это время пишут и/или блокируются. Писатели должны быть остановлены до backup (§3.2, шаг A).
4. **Миграция атомарна.** `env.py` оборачивает все ревизии одной `begin_transaction()`; в 7 ревизиях нет `CONCURRENTLY`,
   `autocommit_block`, `ADD VALUE`. Проверено на копии: сбой последней ревизии (`b5d8e1f3a6c9`) откатил все шесть предыдущих
   (`alembic_version` остался `c3f7a9e2d5b1`, таблиц `workout_definition_versions`/`session_events` нет).
5. **Если `alembic` упал, а в скрипте нет `set -e` (не проверено)**, следующий `up -d` поднимет новый код на старой схеме.
   После любого ненулевого кода/ошибки в логе — сразу `stop app web` и проверка `alembic_version` (§3.3).
6. **`compose`/Dockerfile/`pyproject.toml`/`alembic.ini` между `4298f8b` и кандидатом не менялись** → `up -d` не пересоздаёт `db` и `redis`.
   Новых обязательных настроек `.env` нет (одна новая — `main_min_days_between_starts`, со значением по умолчанию).
7. **Сборка при ≈ 704 МиБ available (swap используется).** `Dockerfile.web`: `package.json` изменён (добавлен `vitest`) →
   слой `npm install` пересобирается; `package-lock.json` в образ **не копируется** (`npm install`, не `npm ci`) → версии
   зависимостей резолвятся заново и могут отличаться от протестированных в CI; затем `tsc -b && vite build`. В обоих образах
   `pip install` выполняется заново (слой стоит после `COPY app`). `build app web` по умолчанию параллельный. Пик памяти не измерен —
   риск OOM/очень долгой сборки; это самый вероятный отказ деплоя.
8. **Откат тем же wrapper'ом на старую ветку после успешной миграции не сработает:** `alembic upgrade head` кодом `4298f8b` на БД,
   уже стоящей на `b5d8e1f3a6c9`, падает — `Can't locate revision identified by 'b5d8e1f3a6c9'` (проверено, exit 255). После
   `pg_restore` (`alembic_version` = `c3f7a9e2d5b1`) или `alembic downgrade c3f7a9e2d5b1` тот же шаг проходит (exit 0). См. §8.

### 3.1 Замороженный HEAD деплой-ветки

* Деплой-ветка — **отдельная**, только для этого выката (имя на усмотрение владельца, например `staging/rc-322-323`). Владелец
  создаёт её на точном SHA, принятом после обоих фиксов и зелёного CI, и закрывает от push. Ветку PR #324 для деплоя не
  использовать. Я эту ветку не создаю (разрешения нет).
* Перед dispatch (в тот же час, без пауз):
  ```bash
  git ls-remote origin refs/heads/<DEPLOY_BRANCH>              # == FROZEN_SHA, записанный при принятии gate
  git diff --stat <GATE_CODE_SHA> <FROZEN_SHA> -- . ':!docs'   # изменения кода относительно прошедшего gate — только принятые фиксы
  ```
* После деплоя (§3.3): `git rev-parse HEAD` в каталоге staging **равен** `FROZEN_SHA`, `git status --short` пуст, ветка = деплой-ветка.
  Образ `.git` не содержит, поэтому факт «собрано из этого HEAD» подтверждается только равенством HEAD в рабочем дереве
  и временем создания образов (после начала деплоя). `HEAD ≠ FROZEN_SHA` при уже выполненной миграции — стоп, решение владельца, §8.

### 3.2 Последовательность

**Шаг 0 — подготовка (read-only).** §2 (остаток), `free -m`, `df -h /home/deploy`, `docker compose -p pullup-staging images`
(сохранить ID образов app/web — нужны для быстрого отката, §8), размер БД 10 МБ (получено).

**Шаг A — остановить писателей.** Это же освобождает память под сборку.
```bash
cd /home/deploy/pullup-trainer-bot-staging
docker compose -p pullup-staging stop app web                     # pullup-staging-app-1 (бот), pullup-staging-web-1 (Mini App); db, redis остаются
DB=pullup-staging-db-1
Q='psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc'
docker exec $DB sh -c "$Q \"select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid()\""   # ожидается 0
docker exec $DB sh -c "$Q \"select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables\""   # записать; повторить через 30 с — значения равны
```
Бот офлайн: Telegram хранит необработанные обновления (до ~24 ч), после запуска бот их обработает. Mini App недоступен.
До конца выката не включать `app`/`web` вручную и не открывать бота/Mini App.

**Шаг B — backup и проверка восстановления** — §5 целиком (при остановленных writers), затем снять счётчики §6.1.

**Шаг C — (опционально, решение владельца) предсборка по одному образу** для снижения пика памяти. Меняет рабочее дерево
staging до dispatch, поэтому — только после финального разрешения:
```bash
cd /home/deploy/pullup-trainer-bot-staging
git fetch origin && git checkout <DEPLOY_BRANCH> && git pull --ff-only origin <DEPLOY_BRANCH>
git rev-parse HEAD                                              # == FROZEN_SHA
COMPOSE_PARALLEL_LIMIT=1 docker compose -p pullup-staging build app
COMPOSE_PARALLEL_LIMIT=1 docker compose -p pullup-staging build web
free -m; dmesg 2>/dev/null | grep -i -E 'out of memory|oom' | tail -n 3
```
Wrapper затем соберёт «по кэшу» — **если** скрытые строки не чистят builder-кэш (не проверено).

**Шаг D — dispatch.** GitHub → Actions → Deploy Staging → `ref` = `<DEPLOY_BRANCH>`. Не запускать повторно после сбоя, пока не
разобран лог (§3.4). Контроль: `watch free -m` на сервере.

**Шаг E — проверка факта выката** — §3.3.

**Шаг F — снова остановить писателей сразу после проверки.** Wrapper запустил `app`/`web`; первое же открытие «Планов» новым
билдом выполняет runtime-convergence (`GET /plan`), а бот и воркеры могут писать. До завершения §6 держать остановленными:
```bash
docker compose -p pullup-staging stop app web
```
Окно между `up -d` и `stop` — секунды; пользователей на staging, кроме владельца/QA, нет (подтвердить).

**Шаг G — данные и convergence** — §6 (convergence `--apply` — только после принятого фикса legacy convergence и dry-run'ов), затем
`docker compose -p pullup-staging start app web` и проверка продукта (§7).

### 3.3 Проверка факта выката

```bash
cd /home/deploy/pullup-trainer-bot-staging
git rev-parse HEAD; git branch --show-current; git status --short            # HEAD == FROZEN_SHA; пусто
docker compose -p pullup-staging ps; docker compose -p pullup-staging images
curl -sf http://127.0.0.1:8002/health
docker exec pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # b5d8e1f3a6c9
```

### 3.4 Если что-то пошло не так (по этапам)

| Сбой | Состояние | Действие |
|---|---|---|
| `build` упал/OOM (до миграции) | схема `c3f7a9e2d5b1`; `app`/`web` остановлены (шаг A); старые образы целы (сбой сборки теги не переписывает — не проверено на этом сервере) | `cd` в каталог, `docker compose -p pullup-staging up -d --no-build app web` — старые образы и тот же compose-файл; проверить `alembic_version` = `c3f7…`; разбор причины |
| `alembic upgrade` упал | атомарно: схема `c3f7a9e2d5b1` (п. 4 §3.0) | **сразу** `stop app web` (п. 5), проверить `alembic_version`; `up -d --no-build app web` на старых образах — только после проверки; разбор лога |
| `up -d`/healthcheck упал после миграции | схема `b5d8e1f3a6c9`, данные не сведены | `stop app web`; логи `docker logs pullup-staging-app-1 --tail 200`, `…-web-1`; откат — §8 |
| `HEAD ≠ FROZEN_SHA` после выката | миграция выполнена | `stop app web`; §8 |

## 4. Цепочка миграций

Голова кандидата — `b5d8e1f3a6c9`, голова одна, цепочка линейная. **R0 staging = `c3f7a9e2d5b1`** (§1.1), поэтому применяются
ровно **7 миграций** (в порядке применения):

| # | Ревизия | Что делает | Данные |
|---|---|---|---|
| 1 | `b7d2e9f4a1c3` | WorkoutDefinition v2: версии, идентичность упражнений, переписанный системный контент (#303) | backfill + контент |
| 2 | `d8a3c6f1e2b4` | Program + Plan v2: occurrences, кредит сессии, констрейнты, custom plans (#304) | backfill |
| 3 | `f4c1a7e9b3d2` | TrainingSession v2: источники, идентичность, prescription snapshot, длительность (#307) | backfill (kind/origin/…) |
| 4 | `a9e6c3d1f5b7` | Live Engine v2: колонки состояния движка + `session_events` (#306) | нет |
| 5 | `a7e2c5b9d1f4` | Единая история: `legacy_id`, `superseded_*`, индексы (#308) | только колонки |
| 6 | `e3b9c5d7a2f1` | Course prescription (#305): `status` varchar(32), `prescription_provenance`, **backfill `block_b.work_sets`** | UPDATE `progression_state` |
| 7 | `b5d8e1f3a6c9` | V5.6: `technique_valid`, `rest_within_limit` в `session_blocks` | нет |

(`c3f7a9e2d5b1` — `programs.access_level` — уже применена на staging.) Проверить точный хвост до деплоя можно только
вне staging (его текущий образ — `4298f8b` — новых ревизий не знает): на машине разработчика, на ветке кандидата, БД не нужна:

```bash
git fetch origin claude/vigilant-clarke-xis1u1 && git checkout --detach origin/claude/vigilant-clarke-xis1u1
alembic history -r c3f7a9e2d5b1:head       # 7 строк, голова b5d8e1f3a6c9
```

Если вывод отличается от таблицы — **стоп**: цепочка не та, что репетировалась.

`e3b9c5d7a2f1` — единственная миграция, меняющая существующее значение (`program_inclusions.progression_state`):
**разрешено** только `block_b.work_sets`: отсутствует / `null` → `4` у записей, где `block_b` — объект. Любое другое
существующее значение (в репетиции: `3`, `5`) сохраняется. Миграция не аддитивна в строгом смысле CLAUDE.md
(UPDATE существующих данных), её `downgrade()` backfill не откатывает.

## 5. Бэкап и проверка восстановления (до деплоя; только staging)

Бэкапа на staging нет (§1.1), БД `pullup_staging` — 10 МБ. Ниже — команды **только для проекта `pullup-staging`**, с именами из §1.1
и защитой: проверка отказывается работать, если контейнер не принадлежит compose-проекту `pullup-staging` (на VPS есть прод и
`reeltrack-*`). Рабочую БД команды не меняют. **Выполнять только после шага A (§3.2): `app` и `web` остановлены, записей нет**, —
иначе дамп и «счётчики до» не соответствуют состоянию на момент миграции. Запускать как скрипт (`bash backup.sh`), а не
вставлять `set -e` в интерактивную консоль.

**Backup считается проверенным, когда выполнено всё** (без этого переходить к шагу C/D нельзя):
1. дамп-файл создан, `sha256` записан, размер > 0, `pg_restore -l` показывает оглавление;
2. восстановление в `restore_check` прошло без ошибок, `alembic_version` там = `c3f7a9e2d5b1`;
3. счётчики в `restore_check` равны счётчикам рабочей БД, снятым в той же остановленной системе (§6.1);
4. после дампа счётчик записей (`sum(n_tup_ins+n_tup_upd+n_tup_del)` из шага A) **не изменился** — за время backup никто не писал;
5. копия дампа лежит **вне VPS** (на сервере один диск).

```bash
set -euo pipefail
DB=pullup-staging-db-1
[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' $DB)" = pullup-staging ] || { echo "NOT STAGING: stop"; exit 1; }

# 5.1 размер БД и имя (не секрет) — убедиться, что дамп поместится на диск
docker exec $DB sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select current_database(), pg_size_pretty(pg_database_size(current_database()))"'
df -h /home/deploy | tail -n 1

# 5.2 дамп (custom format, один файл) + контрольная сумма
umask 077; mkdir -p /home/deploy/backups
TS=$(date -u +%Y%m%dT%H%M%SZ); F=/home/deploy/backups/staging-pre-rc-$TS.dump
docker exec $DB sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$F"
sha256sum "$F" | tee "$F.sha256"; ls -l "$F"
docker exec -i $DB pg_restore -l < "$F" | wc -l          # читается, оглавление непустое
```

Проверка восстановления в **отдельную** БД `restore_check` (рабочую не трогает; выполнить до деплоя, затем удалить):

```bash
docker exec $DB sh -c 'createdb -U "$POSTGRES_USER" restore_check'
docker exec -i $DB sh -c 'pg_restore -U "$POSTGRES_USER" -d restore_check --no-owner' < "$F"
docker exec $DB sh -c 'psql -U "$POSTGRES_USER" -d restore_check -Atc "select version_num from alembic_version"'   # ожидается c3f7a9e2d5b1
docker exec $DB sh -c 'psql -U "$POSTGRES_USER" -d restore_check -Atc "select (select count(*) from users), (select count(*) from training_sessions), (select count(*) from plan_items)"'   # = §6.1 «до»
docker exec $DB sh -c 'dropdb -U "$POSTGRES_USER" restore_check'
```

Круговой дамп→восстановление этими командами (в локальном Postgres 16, `-Fc` / `--no-owner`) прошёл с построчно идентичным
результатом (`docs/STAGING_RC_REHEARSAL.md` §9). Файл дампа хранить вне каталога репозитория и вне томов compose; копию — вне VPS
(на сервере один диск). Redis (`pullup-staging-redis-1`, FSM бота) в откат данных не входит.

**Реальное восстановление (§8, путь 3) — деструктивно, только по решению владельца.**

## 6. Проверки «старых» данных

### 6.1 До деплоя (только счётчики, без персональных данных; снимать при остановленных `app`/`web`, шаг A §3.2)

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

### 6.2 После миграции: проверка данных, затем convergence (после принятого фикса)

Порядок строго такой; `app`/`web` всё это время остановлены (шаг F §3.2).

**6.2.0 Проверка сразу после миграции, ДО convergence** (ожидается состояние «миграция без сведения»; в репетиции — `up_only`):
счётчики из §6.1 **равны** «до» для всех таблиц, кроме новых (`custom_plans`, `exercise_categories`, `session_events`,
`workout_definition_versions`); `plan_items`/`plan_weeks` не изменились; `training_sessions` не изменились по числу; изменён только
`program_inclusions.progression_state` (`block_b.work_sets` absent/null → 4, явные значения сохранены); хэш `initial_progression_state`/`started_at`
из §6.1 совпадает; `alembic_version = b5d8e1f3a6c9`. Любое иное — стоп, §8.

**6.2.1 Convergence — только после принятого фикса legacy convergence** (HOLD ниже) и только после dry-run'ов обоих скриптов с
разбором вывода. Допустимый итоговый diff — §6.3.

> **HOLD: `--apply` обоих скриптов на staging не выполнять**, пока фикс отредактированных/удалённых копий факультативов
> (`docs/STAGING_RC_REHEARSAL.md` §8, «Фикс») не влит в кандидат и не принят владельцем. Разрешены только dry-run'ы и
> pre-check ниже. Без фикса граничный случай (электив не старше плана при неключевой копии) создаёт дубль/воскрешает
> удалённое; с фиксом — не создаёт, а печатает блок «Не разрешено (копия НЕ создана, ничего не привязано): N» с
> `elective_id`, причиной и кандидатами — его разобрать до `--apply`.
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
>
> С фиксом (PR #326) — дополнительно read-only: пользователи с нештатной историей копий (их факультативы не получат ни копии,
> ни привязки — `nonstandard_copy_history` в выводе dry-run). Ожидается `0` для данных, записанных только штатными путями:
> ```sql
> select ts.user_id, count(*) from training_sessions ts left join training_plans tp on tp.user_id = ts.user_id
> where (ts.origin = 'legacy_elective' or (ts.origin is null and ts.source = 'elective')) and ts.legacy_id is null
>   and (tp.id is null or ts.created_at <> tp.created_at) group by 1;
> ```
> Строки здесь (и «из них у пользователей без плана» в dry-run) — разобрать с владельцем до `--apply`: см.
> `docs/STAGING_RC_REHEARSAL.md` §8 «Фикс», «Пробел, который без маркера не закрыть».

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

Критерии: падение build/миграции/healthcheck (§3.4); `HEAD ≠ FROZEN_SHA`; `guard_violations`/exit 4; нарушение §6.3; FAIL в §7.
Во всех случаях первое действие — `docker compose -p pullup-staging stop app web` (писатели остановлены).

**Что нужно подготовить заранее (до деплоя):**
* ветка (или тег) на `4298f8b9727f91d4a150431fd0d9e06131944d27` для отката кода через wrapper — `git checkout "$branch"` + `git pull --ff-only
  origin "$branch"` требуют именно **ветку** (с тегом `pull` на detached HEAD не пройдёт). Создаёт владелец (напр. `staging/pre-rc-4298f8b`); мной не создана;
* ID/теги текущих образов `app`/`web` (шаг 0 §3.2): `docker image inspect -f '{{.Id}}' $(docker inspect -f '{{.Image}}' pullup-staging-app-1)`
  и то же для `…-web-1`; повесить на них свои теги (`docker tag <id> local/staging-app:pre-rc`, `local/staging-web:pre-rc`), чтобы возможный
  `image prune` в скрытых строках wrapper'а не удалил их (не проверено, делает ли он это);
* проверенный backup (§5).

**Ситуации и порядок:**

| Ситуация | Что делать |
|---|---|
| Миграция не прошла (атомарно, схема `c3f7a9e2d5b1`) | §3.4: `up -d --no-build app web` на старых образах; данные не менялись |
| Миграция прошла, **convergence не применялась**, нужно вернуть старый код | **Wrapper на старую ветку не сработает** (§3.0 п. 8: старый `alembic upgrade head` падает на `b5d8e1f3a6c9`). Два варианта: (а) данные: путь 3 ниже (restore → `alembic_version = c3f7a9e2d5b1`), затем wrapper на ветку `4298f8b` (снова `build` при ограниченной RAM) или `up -d --no-build` на сохранённых образах; (б) схема: `docker compose -p pullup-staging run --rm app alembic downgrade c3f7a9e2d5b1` **новым** образом (данные при этом остаются изменёнными: `work_sets = 4` и пр.), затем (а)-код. Старый код на такой схеме читает и пишет (репетиция §4 `docs/STAGING_RC_REHEARSAL.md`) |
| **Convergence применена** (или кто-то открыл «Планы» новым билдом) | Откат кода без данных даёт задвоенные строки плана в старом интерфейсе (репетиция: 4→7, 2→5). **Нужен data restore (путь 3)**, затем код |

**Три разных пути — не смешивать:**

1. **Код.** Старый код (`4298f8b`) на обновлённой схеме проверен на копии (`docs/STAGING_RC_REHEARSAL.md` §4, §9): 20/20 GET → 200;
   старт, ведение и завершение live-сессии и запись в Журнал работают. Чисто — только до convergence. Через wrapper возможен
   только после того, как `alembic_version` стала `c3f7a9e2d5b1` (restore или downgrade). Не проверено: V5.6/STEP-тренировка старым кодом.
2. **Схема (`alembic downgrade c3f7a9e2d5b1`).** Выполнима (в репетиции exit 0), но **не восстанавливает данные** (остаются +19 `plan_items`,
   +3 `plan_weeks`, +3 копии в `training_sessions`, `work_sets = 4`). Использовать только как подготовку к запуску старого wrapper'а, не как откат данных.
3. **Данные — `pg_restore` из дампа §5.** Единственный путь вернуть данные в состояние R0; круговой дамп→восстановление проверен
   построчно. Теряет всё записанное после дампа (на staging в окне выката записей нет — шаг A). **Обязателен после convergence.**
   ```bash
   cd /home/deploy/pullup-trainer-bot-staging
   docker compose -p pullup-staging stop app web
   docker exec pullup-staging-db-1 sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
   docker exec -i pullup-staging-db-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < /home/deploy/backups/staging-pre-rc-<TS>.dump
   docker exec pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # = c3f7a9e2d5b1
   # счётчики §6.1 равны «до»; затем код: wrapper на ветку 4298f8b или up -d --no-build на сохранённых образах
   ```
   Деструктивно: выполнять только по решению владельца. Redis (FSM бота) дамп не затрагивает. После отката — §6.1 (счётчики = «до»),
   `alembic_version`, `git rev-parse HEAD` = `4298f8b…`, health `http://127.0.0.1:8002/health`, затем `start app web`.

## 9. Известные риски и открытые вопросы

- **Два обязательных фикса не готовы** (ждём): (1) IDB — ворота drain-before-projection при сбое чтения IndexedDB
  (`docs/STAGING_RC_CI_E2E.md`); (2) legacy convergence — отредактированные/удалённые копии факультативов
  (`docs/STAGING_RC_REHEARSAL.md` §8). Без них деплой не готов. После них — перепрогон: unit-тесты ворот, edited-copy сценарий, CI E2E.
- **Сборка при ≈ 704 МиБ** (§3.0 п. 7): самый вероятный отказ деплоя; пик не измерен; `npm install` без lock.
- **Скрытые строки `deploy-staging-run.sh` не проверены** (`set -e`, prune, секреты). Требуется полный текст скрипта, прежде чем считать
  §3.4 и §8 окончательными.
- **Staging получит скачок на 67 коммитов и 7 миграций за один выкат**; реальные данные (10 МБ) не видела ни одна репетиция.
- **Неспаренные копии факультативов.** `converge-history` связывает копию с legacy-строкой только по точному совпадению
  `(performed_at, блоки)`; отредактированная копия не спаривается; без фикса при хронологии «электив не старше плана» создаётся
  дубль/воскрешается удалённое (HOLD §6.2). Фикс — PR #326 (`docs/STAGING_RC_REHEARSAL.md` §8, «Фикс»): такие факультативы не
  получают копию, а печатаются в «Не разрешено»; остаточные неоднозначности перечислены там же.
- **Миграция `e3b9c5d7a2f1` неаддитивна** (UPDATE `progression_state`), уже в BASE, не в #322/#323; её `downgrade()` backfill не откатывает.
- **CI E2E красный** на кандидате (2 из 2); причина не подтверждена — `docs/STAGING_RC_CI_E2E.md`.
