# Staging runbook: release candidate #322 + #323 (PR #324)

**Только подготовка. Ни одна команда этого документа не выполнялась на staging; деплой делает владелец.**

> **Статус готовности: BLOCKER, деплой на staging не разрешён.**
> 1. Ждём финалы двух исправлений: **(IDB)** ворота drain-before-projection при сбое чтения IndexedDB и **(legacy convergence)**
>    случай отредактированных/удалённых копий факультативов. В этом документе они **не** реализованы.
> 2. CI E2E на кандидате красный (2 из 2), причина не подтверждена — `docs/STAGING_RC_CI_E2E.md`.
> 3. `deploy-staging-run.sh` известен только по строкам, присланным владельцем (§3.0); `/usr/local/bin/post-deploy-cleanup.sh`
>    и остальное в скрипте **не проверены**. Деплой-ветка выбирается после окончательного candidate SHA (сейчас не создаётся).
> 4. HOLD на `--apply` convergence — §6.2. Staging держится закрытым для записей override'ом до конца проверок — §3.2.
> 5. Сборка фронтенда на сервере невоспроизводима (`npm install` без lock) — §3.5; решение владельца.

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

Всё, что нужно было прочитать с сервера, **уже получено от владельца** (§1.1 и §3.0): проект и контейнеры, SHA `4298f8b`, Alembic `c3f7a9e2d5b1`,
каталог, диск и память, размер БД (10 МБ), отсутствие бэкапа в проверенных каталогах, строки `deploy-staging-run.sh`. Повторный полный `cat` скрипта
не запрашивается (в нём секреты).

Остаются **не проверенными** и **не запрашиваются повторно**: `/usr/local/bin/post-deploy-cleanup.sh` (что реально делает серверная копия), остальные
строки скрипта, форма healthcheck, версия Docker Compose. Это учтено в §3 как допущения.

Read-only команды перед деплоем (шаг 0 §3.2; имена брать из вывода, не угадывать; проект `pullup-staging`, контейнеры из §1.1):
```bash
docker compose version; free -m; df -h /home/deploy
docker compose -p pullup-staging images            # имена/ID образов app и web — для §8
docker compose -p pullup-staging ps -a
git -C /home/deploy/pullup-trainer-bot-staging rev-parse HEAD     # 4298f8b9727f91d4a150431fd0d9e06131944d27
```
Не печатать `.env`, `~/.staging-secrets.env`, токены; вывод — без секретов и персональных данных. На сервере живут ещё прод и `reeltrack-*` — все команды
только для проекта `pullup-staging`.

## 3. Деплой (действие владельца; на VPS ничего не запускалось и не запускается без финального разрешения)

### 3.0 Что известно о `deploy-staging-run.sh`

Со слов владельца (проверенные факты):

```
1: (shebang)
2: set -euo pipefail
   git fetch origin
   git checkout "$branch"
   git pull --ff-only origin "$branch"
   docker compose -p pullup-staging build app web
   docker compose -p pullup-staging run --rm app alembic upgrade head
   docker compose -p pullup-staging up -d
   healthcheck http://127.0.0.1:8002/health
   /usr/local/bin/post-deploy-cleanup.sh        # вызывается после healthcheck, если файл исполняемый
```

**Не проверено:** остальные строки скрипта; форма и длительность healthcheck; **содержимое `/usr/local/bin/post-deploy-cleanup.sh`**.
Копия в репозитории (`deploy/post-deploy-cleanup.sh`) делает `docker image prune -f` (только dangling-образы, не `-a`),
`docker builder prune -f --filter until=168h` и всегда `exit 0`; что установлено на сервере — неизвестно. Повторный полный `cat`
скрипта не запрашивается.

Следствия (из строк + кода репозитория + репетиции):

1. **Ветка, не SHA.** Деплоится `HEAD` ветки на момент `git pull`; SHA скрипт не проверяет и не печатает.
2. **Нет backup и convergence** — делает владелец вручную (§5, §6).
3. **`set -euo pipefail`:** упавший `build` или `alembic upgrade head` обрывает скрипт **до** `up -d`; упавший healthcheck (если он возвращает
   ненулевой код — форма не проверена) обрывает скрипт **до** cleanup. Но к этому моменту `git checkout` и `git pull` уже
   выполнены: **рабочее дерево staging остаётся на новой ветке/HEAD**, даже если деплой упал.
4. **Старые app/web работают во время `build` и миграции** (скрипт их не останавливает). Миграция берёт `ACCESS EXCLUSIVE`-блокировки
   (ALTER TABLE), старый бот/Mini App в это время пишут и/или блокируются → писатели должны быть остановлены заранее (§3.2, шаг A).
5. **Миграция атомарна.** `env.py` оборачивает все ревизии одной `begin_transaction()`; в 7 ревизиях нет `CONCURRENTLY`,
   `autocommit_block`, `ADD VALUE`. Проверено на копии: сбой последней ревизии (`b5d8e1f3a6c9`) откатил все шесть предыдущих
   (`alembic_version` остался `c3f7a9e2d5b1`, новых таблиц и колонок нет). Вместе с `set -e` (п. 3) неудачная миграция не доходит до `up -d`.
6. **Wrapper запускает `app` и `web` сам (`up -d`) до всякого `--apply`** — окно runtime-convergence (первый `GET /plan` новым билдом
   выполняет сведение) и записей бота. «Запустить и быстро остановить» защитой не является → §3.2, hold-override.
7. **`compose`/Dockerfile/`pyproject.toml`/`alembic.ini` между `4298f8b` и кандидатом не менялись** → `up -d` не пересоздаёт `db` и `redis`.
   Новых обязательных настроек `.env` нет (одна новая — `main_min_days_between_starts`, со значением по умолчанию).
8. **Сборка при ≈ 704 МиБ available (swap используется).** `Dockerfile.web`: `package.json` изменён (добавлен `vitest`) → слой `npm install`
   пересобирается, затем `tsc -b && vite build`; в обоих образах `pip install` выполняется заново (слой стоит после `COPY app`);
   `build app web` по умолчанию параллельный. Пик памяти не измерен — риск OOM/очень долгой сборки. Отдельно — невоспроизводимость
   `npm install` без lock: §3.5.
9. **Откат тем же wrapper'ом на старую ветку после успешной миграции не сработает:** `alembic upgrade head` кодом `4298f8b` на БД,
   уже стоящей на `b5d8e1f3a6c9`, падает — `Can't locate revision identified by 'b5d8e1f3a6c9'` (проверено, exit 255). После
   `pg_restore` (`alembic_version` = `c3f7a9e2d5b1`) или `alembic downgrade c3f7a9e2d5b1` тот же шаг проходит (exit 0). См. §8.

### 3.1 Замороженный HEAD деплой-ветки

* **Деплой-ветка выбирается и создаётся только после окончательного candidate SHA** (код-SHA после обоих фиксов, зелёного CI и решения по §3.5).
  Сейчас её не создают и не защищают; ветку PR #324 для деплоя не использовать (она будет меняться).
* Когда ветка создана: владелец ставит её на точный `FROZEN_SHA` и закрывает от push. Перед dispatch (в тот же час, без пауз):
  ```bash
  git ls-remote origin refs/heads/<DEPLOY_BRANCH>              # == FROZEN_SHA, записанный при принятии gate
  git diff --stat <GATE_CODE_SHA> <FROZEN_SHA> -- . ':!docs'   # изменения кода относительно прошедшего gate — только принятые фиксы
  ```
* После деплоя (§3.3): `git rev-parse HEAD` в каталоге staging **равен** `FROZEN_SHA`, `git status --short` пуст (кроме override из §3.2, он в
  `.git/info/exclude`), ветка = деплой-ветка. Образ `.git` не содержит, поэтому «собрано из этого HEAD» подтверждается равенством HEAD в рабочем
  дереве и временем создания образов (после начала деплоя). `HEAD ≠ FROZEN_SHA` при выполненной миграции — стоп, решение владельца, §8.

### 3.2 Последовательность: staging закрыт для записей до конца проверок

**Почему не «остановить после старта».** `up -d` запускает `app` (бот, воркеры) и `web` (Mini App); пока они подняты, возможны записи и
runtime-convergence. Нужен механизм, при котором wrapper их **вообще не запускает**.

**Рассмотренные доступные механизмы** (новых флагов в скриптах не придумывается):

| Механизм | Закрывает | Вывод |
|---|---|---|
| Остановка `app`/`web` после `up -d` | — (окно между `up -d` и `stop`) | **не защита** |
| Остановка `app`/`web` до деплоя (шаг A) | писатели до backup и во время `build`/миграции | необходима, но wrapper затем сам их поднимет |
| `docker-compose.override.yml` с `profiles` у `app` и `web` (штатная возможность Compose; файл подхватывается автоматически) | wrapper'овский `up -d` (без имён сервисов) поднимает только `db`, `redis`; `build app web` и `run --rm app` с явными именами работают | **рекомендуется**; проверка ниже |
| nginx 503 для `staging.app.bimoool.com` | только Mini App; бот (long polling) не закрывает; нужны права на nginx | недостаточно |
| `deploy.replicas: 0` в override | то же, что профили | равнозначно, менее наглядно |
| флаг режима обслуживания/read-only в приложении | — | **в коде нет** (поиск по `app/config.py`: `maintenance`/`readonly`/`disable` — пусто) |

**Что проверено** (Docker Compose v5.6.0 в песочнице, демона нет; версия на VPS не известна): с override `docker compose config --services`
для `up -d` без аргументов даёт `db redis` (без override — `db redis app web`); `docker compose --dry-run build app web` собирает оба образа,
несмотря на профили (явно названные службы включают свой профиль); `docker-compose.override.yml` в каталоге проекта подхватывается без `-f`.
**Не проверено** (нужен демон): `run --rm app …` и `up -d` с профилями на реальном сервере — проверяется read-only командами шага A.
Допущение (не проверено): скрытые строки wrapper'а не удаляют неотслеживаемый файл (`git clean`) и не перезаписывают compose-файлы.

**Шаг 0 — подготовка (read-only).** `docker compose version` (нужны профили, Compose ≥ 2), `free -m`, `df -h /home/deploy`,
`docker compose -p pullup-staging images` (сохранить ID/имена образов app/web — §8), размер БД 10 МБ (получено).

**Шаг A — остановить писателей и поставить hold.** Это же освобождает память под сборку.
```bash
cd /home/deploy/pullup-trainer-bot-staging
docker compose -p pullup-staging stop app web                     # pullup-staging-app-1 (бот), pullup-staging-web-1 (Mini App); db, redis остаются
cat > docker-compose.override.yml <<'EOF'
services:
  app:
    profiles: ["hold"]
  web:
    profiles: ["hold"]
EOF
echo docker-compose.override.yml >> .git/info/exclude            # локально; рабочее дерево остаётся «чистым» для git status
docker compose -p pullup-staging config --services               # ожидается ровно: db, redis
docker compose -p pullup-staging --dry-run up -d                 # app/web не должны создаваться и стартовать; db/redis — без изменений
DB=pullup-staging-db-1
Q='psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc'
docker exec $DB sh -c "$Q \"select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid()\""   # ожидается 0
docker exec $DB sh -c "$Q \"select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables\""   # записать; через 30 с повторить — равны
```
Если `--dry-run up -d` намерен создать/запустить `app` или `web` — **стоп**, механизм не работает на этой версии Compose; деплой не начинать.
Бот офлайн: Telegram хранит необработанные обновления (до ~24 ч), после запуска бот их обработает. Остановленные командой `stop` контейнеры
не поднимаются после перезагрузки VPS (поведение Docker для `restart: unless-stopped`, не проверено на сервере).

**Шаг B — backup и проверка восстановления** — §5 целиком (при остановленных writers), затем «до»-снимок §6.1.

**Шаг C — (опционально, решение владельца) предсборка по одному образу** для снижения пика памяти. Меняет рабочее дерево до dispatch;
**воспроизводимость сборки не обеспечивает** (§3.5):
```bash
cd /home/deploy/pullup-trainer-bot-staging
git fetch origin && git checkout <DEPLOY_BRANCH> && git pull --ff-only origin <DEPLOY_BRANCH>
git rev-parse HEAD                                              # == FROZEN_SHA
COMPOSE_PARALLEL_LIMIT=1 docker compose -p pullup-staging build app
COMPOSE_PARALLEL_LIMIT=1 docker compose -p pullup-staging build web
free -m; dmesg 2>/dev/null | grep -i -E 'out of memory|oom' | tail -n 3
```

**Шаг D — dispatch.** GitHub → Actions → Deploy Staging → `ref` = `<DEPLOY_BRANCH>`. Ожидаемое поведение при hold: `build` и миграция проходят,
`up -d` поднимает только `db`/`redis` (уже работают), **healthcheck :8002 не проходит (web не запущен)** → скрипт завершается с ошибкой, workflow красный,
cleanup не вызывается. Это ожидаемо; отличать от настоящего сбоя — по логу: есть строки «Running upgrade … b5d8e1f3a6c9» и нет traceback.
Форма healthcheck (бесконечный ли цикл, таймаут) не проверена — следить за `free -m`, при зависании отменить workflow и проверить §3.3. Не запускать повторно
до разбора лога.

**Шаг E — проверка факта выката** — §3.3 (app/web по-прежнему остановлены).

**Шаг F — проверка данных и convergence при остановленных app/web** — §6 (`--apply` — только после принятого фикса legacy convergence и dry-run'ов).

**Шаг G — снять hold и запустить.** Образы уже собраны на шаге D, пересборка не нужна:
```bash
cd /home/deploy/pullup-trainer-bot-staging
rm docker-compose.override.yml && sed -i '/^docker-compose.override.yml$/d' .git/info/exclude
docker compose -p pullup-staging config --services               # db, redis, app, web
docker compose -p pullup-staging up -d --no-build
curl -sf http://127.0.0.1:8002/health
```
Затем §7. Первое открытие «Планов» новым билдом — после этого шага, когда convergence уже проверена.

### 3.3 Проверка факта выката

```bash
cd /home/deploy/pullup-trainer-bot-staging
git rev-parse HEAD; git branch --show-current; git status --short            # HEAD == FROZEN_SHA; пусто
docker compose -p pullup-staging ps -a; docker compose -p pullup-staging images
docker exec pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # b5d8e1f3a6c9
```
`app`/`web` при активном hold — `Exited`; healthcheck на :8002 не отвечает — это штатно до шага G.

### 3.4 Если что-то пошло не так (по этапам)

| Сбой | Состояние | Действие |
|---|---|---|
| `build` упал/OOM | схема `c3f7a9e2d5b1`; `app`/`web` остановлены (шаг A); рабочее дерево уже на новой ветке (п. 3 §3.0); старые образы целы (сбой сборки теги не переписывает — не проверено на сервере) | оставить hold; разобрать причину. Вернуть старые app/web (схема не менялась): §8.2 — `up -d --no-build app web` после снятия override |
| `alembic upgrade` упал | атомарно: схема `c3f7a9e2d5b1` (п. 5 §3.0); `up -d` не выполнялся (`set -e`) | оставить hold, проверить `alembic_version`; разобрать лог; старый код запускать только после проверки |
| healthcheck красный при снятом hold | схема `b5d8e1f3a6c9`, данные не сведены или сведены | `stop app web`; логи `docker logs pullup-staging-app-1 --tail 200`, `…-web-1`; откат — §8 |
| `HEAD ≠ FROZEN_SHA` после выката | миграция выполнена | не снимать hold; §8 |

### 3.5 Воспроизводимость сборки фронтенда (риск: `npm install` без lock)

**Факт.** `Dockerfile.web` копирует только `webapp-frontend/package.json` и выполняет `npm install`; `package-lock.json` в образ не попадает
(он не исключён `.dockerignore`, просто не копируется), хотя в репозитории lock есть (с #306). Все 15 прямых зависимостей заданы диапазонами `^`/`~`:
каждая сборка на сервере резолвит транзитивные и прямые версии заново — **собранный фронтенд может отличаться от протестированного в CI (`npm ci` по lock)**.
Кэш Docker-слоя этого не исправляет: на этом деплое слой `npm install` и так будет пересобран (`package.json` изменён).
Предсборка по одному образу (шаг C) экономит память, но резолвит те же диапазоны — риск не устраняет.

**Минимальное решение без изменения серверных скриптов** — правка репозитория (2 строки `Dockerfile.web`):
`docs/rehearsal/patches/dockerfile-web-npm-ci.patch` (проверено `git apply --check`; **не применена**):
```diff
-COPY webapp-frontend/package.json ./
-# package-lock.json нет (см. CLAUDE.md) — npm install, не npm ci, до
-# первой генерации лока средой с доступом к npm-реестру.
-RUN npm install
+COPY webapp-frontend/package.json webapp-frontend/package-lock.json ./
+# Воспроизводимая сборка: ровно версии из package-lock.json (как в CI: `npm ci`), без повторного разрешения диапазонов.
+RUN npm ci
```
Проверено локально: шаги этапа (`npm ci` только из `package.json` + lock, затем копирование исходников и `npm run build`) завершаются успешно
(Node 22; в CI `e2e.yml` тот же `npm ci` + `npm run build` на Node 20, как в `node:20-slim`). `npm ci` падает, если lock расходится с `package.json`, — это
дополнительная защита. Образ в песочнице не собирался (демона нет).

Это изменение сборки образа, которое CI не исполняет (CI образы не строит): если принято, оно входит в окончательный candidate SHA **до** gate и требует
перепроверки сборки на сервере (первый реальный `docker build` — на staging). Без патча риск остаётся принятым осознанно; мера смягчения — сравнить собранный
`dist`/версии (`docker run --rm <web-image> ls /app/webapp-frontend/dist/assets`) и пройти §7 на реальном устройстве.

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

`e3b9c5d7a2f1` — миграция, меняющая существующее значение (`program_inclusions.progression_state`). Проверяется **предикатом**, а не
числом строк (на реальных данных количество и состав другие): у каждой записи, где `block_b` — объект, а `work_sets` отсутствует или JSON `null`, после
миграции `work_sets = 4`; у остальных записей значение `work_sets` и все прочие ключи состояния **не изменились**. Запросы — §6.1/§6.2.0.
Миграция не аддитивна в строгом смысле CLAUDE.md (UPDATE существующих данных), её `downgrade()` backfill не откатывает.

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

Два набора снимков (сохранить в файлы; значения — без персональных данных):

**(1) Хэши строк по ДО-колонкам для всех таблиц** — единый механизм «до/после», не требующий, чтобы счётчики оставались неизменными:
```bash
# генератор берёт список колонок из схемы ДО миграции; файл hash_queries.sql потом выполняется и ДО, и ПОСЛЕ
docker exec -i pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' < gen_hash_queries.sql > hash_queries.sql
docker exec -i pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' < hash_queries.sql > hq_before.txt     # строки: таблица|число|хэш
```
(Файл `docs/rehearsal/sql/gen_hash_queries.sql` лежит в ветке кандидата; в рабочем дереве staging до деплоя его нет — создать на сервере в консоли
(`cat > gen_hash_queries.sql <<'EOF' … EOF`, содержимое — из репозитория/PR) и выполнить команды выше как есть;
хэширует `row(<колонки, существовавшие до>)` по таблицам с колонкой `id`;
таблицы без `id` перечислены в комментарии файла. Проверено на репетиционной БД: 47 таблиц, после семи миграций изменились данные
только в `program_inclusions`, число строк не изменилось нигде.)

**(2) Точечные снимки:**
```sql
-- (a) что изменит e3b9c5d7a2f1: значения work_sets до (без персональных данных: id и число)
select id || ':' || coalesce((progression_state->'block_b'->'work_sets')::text, 'ABSENT') from program_inclusions order by id;     -- work_sets_before.txt
-- (b) части состояния, которые миграции менять НЕ должны (хэш должен совпасть после)
select md5(string_agg(id::text||'|'||(progression_state #- '{block_b,work_sets}')::text, ',' order by id)) from program_inclusions;   -- state_wo_work_sets
select md5(string_agg(row(id,training_plan_id,program_id,snapshot,started_at,expires_at,is_active,created_at,initial_progression_state)::text, '|' order by id)) from program_inclusions;   -- inclusion_other_cols
-- (c) счётчики для сверки с restore_check (§5) и «до»
select 'users', count(*) from users union all select 'subscriptions', count(*) from subscriptions
union all select 'program_inclusions', count(*) from program_inclusions union all select 'workouts (legacy)', count(*) from workouts
union all select 'elective_workouts', count(*) from elective_workouts union all select 'training_sessions', count(*) from training_sessions
union all select 'session_blocks', count(*) from session_blocks union all select 'set_logs', count(*) from set_logs
union all select 'plan_weeks', count(*) from plan_weeks union all select 'plan_items', count(*) from plan_items;
```

Дополнительно, **если R0 ≥ `a7e2c5b9d1f4`** (есть `legacy_id`): неспаренные копии факультативов — риск дублей, см. §9.

```sql
select origin, count(*) as sessions, count(legacy_id) as keyed from training_sessions where source = 'elective' group by 1;
```

### 6.2 После миграции: проверка данных, затем convergence (после принятого фикса)

Порядок строго такой; `app`/`web` всё это время остановлены (шаг F §3.2).

**6.2.0 Проверка сразу после миграции, ДО convergence — по ожидаемым преобразованиям семи миграций, а не по неизменности счётчиков.**
Выполнить `hash_queries.sql` (тот же файл) → `hq_after.txt` и сравнить с `hq_before.txt` по таблицам:
```bash
diff <(cut -d'|' -f1,3 hq_before.txt) <(cut -d'|' -f1,3 hq_after.txt)    # хэши ДО-колонок
diff <(cut -d'|' -f1,2 hq_before.txt) <(cut -d'|' -f1,2 hq_after.txt)    # числа строк
```
Что допустимо (сводка по миграциям; проверено на репетиционных данных, на реальных — сверять с этим перечнем):

| Ревизия | Преобразование | Что должно быть в diff |
|---|---|---|
| `b7d2e9f4a1c3` | новая `workout_definition_versions` (+триггер неизменяемости), `exercise_categories`; новые колонки `exercises` (`display_name`, `slug`, `category_id`, `subcategory_id`, `visibility`, `analytics_exercise_id`), `complexes.current_version_id`; backfill этих колонок и **версий** (append-only), системный контент пишется новыми версиями; подписки, доступ, планы, включения, сессии не трогает | новые таблицы с числом строк > 0; в ДО-хэшах `exercises`/`complexes`/`complex_items` различий быть **не должно**, а если есть — только строки системного контента (`source_type = 'system'`), разбор построчно |
| `d8a3c6f1e2b4` | новые колонки `programs`, `program_inclusions`, `plan_items`, `plan_weeks`; `custom_plans`; backfill новых колонок (`programs.slots/frequency/constraints/assessment`, `program_inclusions.status`, `plan_items.source/workout_definition_id`, `training_sessions.plan_item_id` где связь однозначна) | в ДО-хэшах различий нет |
| `f4c1a7e9b3d2` | новые колонки `training_sessions` (`kind`, `origin`, `source_v2`, `duration_source`, `started_at`, `ended_at`, …) + backfill (`origin`: `legacy_elective` / `legacy_backfill` / `native`) | в ДО-хэшах различий нет; новые `origin` проверяются запросом ниже |
| `a9e6c3d1f5b7` | колонки состояния движка; новая пустая `session_events` | `session_events` = 0 строк |
| `a7e2c5b9d1f4` | `legacy_id`, `superseded_*`, индексы (в т.ч. уникальный `(origin, legacy_id)`) | данных не меняет |
| `e3b9c5d7a2f1` | `status` varchar(32), `prescription_provenance`; **UPDATE** `progression_state`: `block_b.work_sets` absent/`null` → `4` | различие **только** в `program_inclusions` и **только** в этом ключе (проверки ниже) |
| `b5d8e1f3a6c9` | `technique_valid`, `rest_within_limit` (nullable) в `session_blocks` | данных не меняет |

Итого для существующих таблиц допустимое различие ДО-хэшей: `program_inclusions` (только `work_sets`) и, возможно, строки системного контента (`b7d2`). Числа строк
существующих таблиц на этой стадии не меняются (сведение ещё не выполнялось). Проверки предиката `e3b9c5d7a2f1` (после; сравнить с «до» (2)(a)/(b)):
```sql
-- 1) не осталось объектов block_b без числового work_sets (ожидается 0)
select count(*) from program_inclusions where jsonb_typeof(progression_state->'block_b')='object'
  and coalesce(jsonb_typeof(progression_state->'block_b'->'work_sets'),'null')='null';
-- 2) всё остальное состояние и прочие колонки не изменились: оба хэша из «до» (2)(b) совпадают
-- 3) построчно: где work_sets был absent/null — теперь 4; где было число — то же число (сравнить work_sets_before.txt с выводом (2)(a) после)
```
Дополнительно: `alembic_version = b5d8e1f3a6c9`; `origin` у `training_sessions`: `select origin, count(*) from training_sessions group by 1` — только
`native`, `legacy_backfill`, `legacy_elective`. Любое иное расхождение — стоп, §8.

**6.2.1 Convergence — только после принятого фикса legacy convergence** (HOLD ниже) и только после dry-run'ов обоих скриптов с
разбором вывода. Допустимый итоговый diff — §6.3.

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
Счётчики `dry-run` совпадают со счётчиками первого `apply` (числа на реальных данных будут другими). Заметки владельца по одному аккаунту:
`--telegram-id <ID>` вместо `--all`; BEFORE/AFTER снимок — `scripts/qa_state_snapshot.py --telegram-id <ID>`
(read-only), порядок и ожидания — `docs/STAGING_CONVERGENCE_RUNBOOK.md`.

### 6.3 Допустимый итоговый diff «до → после» (миграция + convergence)

Основа — ожидаемые преобразования семи миграций (§6.2.0) плюс сведение. Счётчики **не** требуются неизменными: ниже указано, что должно и что не должно меняться.

| Область | Допустимо | Недопустимо |
|---|---|---|
| `alembic_version` | `c3f7a9e2d5b1` → `b5d8e1f3a6c9` | другая голова |
| `program_inclusions.progression_state` | только `block_b.work_sets`: absent/`null` → `4` (предикат §6.2.0) | любой другой ключ; изменение явных значений `work_sets` |
| `program_inclusions`: прочие ДО-колонки | без изменений (хэш (2)(b) совпадает) | любое изменение |
| Новые колонки и таблицы | перечень §6.2.0 | — |
| `plan_items` | + строки-occurrences; легаси-агрегат **текущей/будущей** недели получает `plan_week_id`, `status='removed'` (не удаляется), у развёрнутого агрегата `count_per_week` уменьшается | изменение или удаление строк **прошлых** недель; уменьшение числа строк |
| `plan_weeks` | + недели (`past_gap_empty` и т.п.) | удаление |
| `training_sessions` | + нативные копии legacy-тренировок/факультативов (`origin = legacy_*`, `legacy_id`); у существующих копий `legacy_id` NULL → значение при точном совпадении | изменение ДО-колонок существующих сессий; `superseded_at` у существующих; дубли `(origin, legacy_id)`; новые копии факультативов для электива, у которого уже есть неключевая копия (HOLD §6.2) |
| `session_blocks`, `set_logs` | + строки копий | изменение ДО-колонок существующих |
| Таблицы, которые ни одна миграция не меняет (`users`, `subscriptions`, `pending_payments`, `workouts`, `blocks`, `workout_sets`, `baselines`, `elective_workouts`, `*_archive_*`, `achievements`, `coins`, `user_body_metrics`, …) | ДО-хэши и счётчики равны | любое изменение |

Проверки после (должны быть «0 строк»):
```sql
select origin, legacy_id, count(*) from training_sessions where legacy_id is not null group by 1,2 having count(*) > 1;   -- дубли копий
```
Остальное — хэши (1) и точечные снимки (2) против «до»: расхождения допустимы только по таблице выше.

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

Критерии: падение build/миграции (§3.4); `HEAD ≠ FROZEN_SHA`; `guard_violations`/exit 4; нарушение §6.2.0/§6.3; FAIL в §7.
Первое действие всегда — писатели остановлены и hold на месте (`docker compose -p pullup-staging stop app web`; override не снимать).

**Подготовить заранее (до деплоя):**
* ветка на `4298f8b9727f91d4a150431fd0d9e06131944d27` (напр. `staging/pre-rc-4298f8b`) — wrapper делает `git checkout "$branch"` + `git pull --ff-only
  origin "$branch"`, с тегом `pull` на detached HEAD не пройдёт. Создаёт владелец; мной не создана;
* **свои теги на текущие образы** `app`/`web` (имена/ID — шаг 0 §3.2):
  `docker tag <ID_образа_app> local/staging-app:pre-rc`, `docker tag <ID_образа_web> local/staging-web:pre-rc`. Без тегов старые образы остаются
  без имени после пересоздания контейнеров и могут быть удалены `docker image prune -f` из cleanup (содержимое серверной версии не проверено;
  при hold контейнеры `app-1`/`web-1` не пересоздаются, поэтому образы пока держатся ими);
* проверенный backup (§5).

### 8.1 Старый wrapper на новой revision — НЕ работает (доказано)

Деплой старой ветки тем же wrapper'ом выполняет `alembic upgrade head` кодом `4298f8b`. Если `alembic_version` = `b5d8e1f3a6c9`, он падает
(`Can't locate revision identified by 'b5d8e1f3a6c9'`, exit 255), и по `set -e` скрипт обрывается до `up -d`. Проверено на копии БД. Это означает:
**wrapper можно использовать для отката только когда `alembic_version` снова `c3f7a9e2d5b1`** — после `pg_restore` (8.3) или после `alembic downgrade c3f7a9e2d5b1`
(схема откатывается, данные нет, см. 8.3). Править одну строку `alembic_version` вручную нельзя — см. 8.3.

### 8.2 Альтернативный откат кода: сохранённые старые образы, без Alembic

Сценарий: миграция прошла, **convergence не применялась**, нужно вернуть старый код. Старый код не запускает Alembic при старте: репетиция поднимала `4298f8b`
(`uvicorn app.web.main:app`) против обновлённой схемы — 20/20 GET → 200, старт/подходы/завершение live-сессии и запись в Журнал работают
(`docs/STAGING_RC_REHEARSAL.md` §4, §9). Бот (`app.main`) в песочнице не запускался (нужен Telegram).
```bash
cd /home/deploy/pullup-trainer-bot-staging
docker compose -p pullup-staging stop app web
docker tag local/staging-app:pre-rc <ИМЯ_ОБРАЗА_APP_ИЗ_ШАГА_0>      # вернуть имена, под которыми compose ищет образы (docker compose images)
docker tag local/staging-web:pre-rc <ИМЯ_ОБРАЗА_WEB_ИЗ_ШАГА_0>
rm -f docker-compose.override.yml && sed -i '/^docker-compose.override.yml$/d' .git/info/exclude
docker compose -p pullup-staging up -d --no-build app web                # без сборки и без Alembic; схема остаётся b5d8e1f3a6c9
curl -sf http://127.0.0.1:8002/health
```
Ограничения: (а) только до convergence/первого `GET /plan` новым кодом — иначе в старом интерфейсе задвоенные строки плана (репетиция: 4→7, 2→5); (б) схема остаётся новой —
следующий деплой старой веткой wrapper'ом всё равно упадёт (8.1); (в) способ не проверен на реальном сервере (демона в песочнице нет), требует, чтобы старые образы существовали
(теги, шаг «подготовить заранее»); (г) рабочее дерево staging уже на новой ветке — compose-файл тот же (проверено: не менялся), но `git status`/HEAD не соответствуют образам; вернуть
`git checkout <ветка 4298f8b>` после отката.

### 8.3 После convergence — полноценный откат требует возврата данных

После `--apply` (или после первого `GET /plan` новым билдом) данные изменены сведением: новые `plan_items`/`plan_weeks`, `status='removed'`, новые копии
`training_sessions` с `legacy_id`, `work_sets = 4`. **Это не вернуть ни сменой `alembic_version`, ни `alembic downgrade`:**
* `alembic downgrade c3f7a9e2d5b1` откатывает схему, данные сведения и backfill остаются (репетиция: plan_items +19, plan_weeks +3, training_sessions +3, `work_sets=4`);
* ручная правка `alembic_version` на `c3f7a9e2d5b1` при новой схеме оставляет состояние рассогласованным: проверено на копии — следующий `alembic upgrade head`
  падает на первой же ревизии (`DuplicateTableError: relation "exercise_categories" already exists`), `alembic_version` остаётся `c3f7a9e2d5b1`.

Единственный путь — **`pg_restore` из дампа §5** (дамп содержит схему и данные R0 и `alembic_version = c3f7a9e2d5b1`). Теряет всё записанное после дампа
(на staging в окне выката записей нет — шаг A). Деструктивно: только по решению владельца.
```bash
cd /home/deploy/pullup-trainer-bot-staging
docker compose -p pullup-staging stop app web
docker exec pullup-staging-db-1 sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker exec -i pullup-staging-db-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < /home/deploy/backups/staging-pre-rc-<TS>.dump
docker exec pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # = c3f7a9e2d5b1
# счётчики и ДО-хэши (hash_queries.sql) равны «до» (§6.1); затем код: 8.2 (старые образы) либо wrapper на ветку 4298f8b (8.1: теперь Alembic пройдёт)
```
После отката: §6.1 (хэши и счётчики = «до»), `alembic_version`, `git rev-parse HEAD` = `4298f8b…`, health `http://127.0.0.1:8002/health`. Redis (FSM бота) дамп не затрагивает.

## 9. Известные риски и открытые вопросы

- **Два обязательных фикса не готовы** (ждём финалы): (1) IDB — ворота drain-before-projection при сбое чтения IndexedDB
  (`docs/STAGING_RC_CI_E2E.md`); (2) legacy convergence — отредактированные/удалённые копии факультативов
  (`docs/STAGING_RC_REHEARSAL.md` §8). Без них деплой не готов. После них — перепрогон: unit-тесты ворот, edited-copy сценарий, CI E2E; затем
  окончательный candidate SHA → деплой-ветка (§3.1).
- **Невоспроизводимая сборка фронтенда** (`npm install` без lock, §3.5) — предложен патч, не применён; решение владельца до окончательного SHA.
- **Сборка при ≈ 704 МиБ** (§3.0 п. 8): вероятный отказ деплоя; пик не измерен.
- **hold-override проверен только на уровне `config`/`--dry-run build` (Compose v5.6.0, без демона)**; версия Compose и поведение `run`/`up` на VPS не проверены —
  обязательная проверка шага A (`config --services`, `--dry-run up -d`).
- **`/usr/local/bin/post-deploy-cleanup.sh` и остальные строки `deploy-staging-run.sh` не проверены** (форма healthcheck, возможные `git clean`/правки compose).
- **Staging получает скачок на 67 коммитов и 7 миграций за один выкат**; реальные данные (10 МБ) не видела ни одна репетиция (все числа в `docs/STAGING_RC_REHEARSAL.md`
  — на синтетике и на staging не переносятся).
- **Неспаренные копии факультативов.** `converge-history` связывает копию с legacy-строкой только по точному совпадению `(performed_at, блоки)`; отредактированная копия не
  спаривается; при хронологии «электив не старше плана» создаётся дубль/воскрешается удалённое (HOLD §6.2).
- **Миграция `e3b9c5d7a2f1` неаддитивна** (UPDATE `progression_state`), уже в BASE, не в #322/#323; её `downgrade()` backfill не откатывает.
- **CI E2E красный** на кандидате (2 из 2); причина не подтверждена — `docs/STAGING_RC_CI_E2E.md`.
