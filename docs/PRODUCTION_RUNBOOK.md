# Production runbook: guarded-выкат MVP-1 и откат

Скрипты: `deploy/deploy-production-guarded-run.sh` (preflight / rehearse-check / apply) и
`deploy/rollback-production-guarded.sh` (R1 / R3). Тесты потока: `tests/test_scripts/test_deploy_production_guarded.py`
(заглушки docker/git/curl, без Docker и БД). Основа — план `PRODUCTION_RELEASE_PLAN.md` (фазы, риски, R1–R3, решения D1–D12).

**Решения владельца, на которых построен скрипт:** legacy-пользователи сохраняют прежнюю прогрессию (полный backfill
`scripts/backfill_multi_program.py` на legacy-версии курса, без перевода на V5.6; D2 = (а)); прод выкатывается
guarded-скриптом, который владелец запускает вручную по SSH (не workflow); `main` меняется только release-PR.
`deploy.yml` / `deploy/deploy-run.sh` для этого релиза **не использовать**: они мигрируют при работающих сервисах,
поднимают новый код до backfill и чистят образы отката (план §4.1).

Ничего из этого документа на VPS, staging или проде не запускалось. Всё, что требует сервера, — действия владельца.

---

## 1. Параметры и откуда взяты значения по умолчанию

Скрипт ничего не угадывает. Каждое значение по умолчанию сверяется с тем, что показывает живой compose-проект.
Несовпадение — отказ до любых действий. Тогда значение задаётся явно переменной окружения.

| Переменная | По умолчанию | Источник | Чем сверяется в preflight |
|---|---|---|---|
| `PROD_DIR` | `/root/pullup-trainer-bot` | `deploy/deploy-run.sh` (`repo_dir`), корневой `CLAUDE.md`, skill `deploy-and-verify` | метка `com.docker.compose.project.working_dir` контейнера `db` |
| `PROD_PROJECT` | `pullup-trainer-bot` | лог прод-деплоя run 36600938386 (`pullup-trainer-bot-{db,app,web}-1`), имя каталога = проект compose по умолчанию | метка `com.docker.compose.project` |
| `PROD_COMPOSE_FILES` | `$PROD_DIR/docker-compose.yml` | в репозитории нет override-файла | метка `com.docker.compose.project.config_files` (override на сервере → отказ) |
| `PROD_DB_NAME` | `pullup` | `docker-compose.yml` (`POSTGRES_DB:-pullup`), `app/services/qa_staging_guard.py` (`PROD_DB_NAMES`) | `POSTGRES_DB` контейнера `db` **и** имя БД в `DATABASE_URL` из `.env`; имя со `staging`/`test` → отказ |
| `PROD_MINI_APP_URL` | `https://app.bimoool.com` | план G8, `deploy/nginx/app.bimoool.com.conf` | apply: `MINI_APP_URL` в `.env` ровно равен ему; rehearse-check: обязан отличаться |
| `PROD_EXPECTED_FROM_REV` | `e7c2a4f9d1b3` | голова `37b989c` (последний прод-деплой, план §1.1) | `alembic_version` прода |
| `PROD_EXPECTED_TO_REV` | `b5d8e1f3a6c9` | единственный head `aa9270e` | `alembic heads` нового образа |
| `PROD_HEALTH_URL` | `http://<docker compose port web 8000>/health` | `app/web/main.py` `GET /health` (не `/api/hello`: тот требует initData), порт `MINI_APP_PORT:-8001` | порт не определился → отказ |
| `PROD_BACKUP_DIR` | `/root/backups` | план §3.2 | — (создаётся с правами 700/600) |
| `PROD_REQUIRED_ANCESTORS` | `628144fa5457c41512db41af214c97a085fcb4b6` | фикс `backfill --dry-run` (MissingGreenlet при уже смигрированных пользователях) | `git merge-base --is-ancestor`; `-` отключает |
| `PROD_KEEP_BACKUPS` / `PROD_QUIESCE_SECONDS` / `PROD_HEALTH_TIMEOUT` / `PROD_MIN_DISK_MB` / `PROD_MIN_MEM_MB` | 3 / 15 / 240 / 3072 / 400 | план G5, staging-скрипт | — |

Обязательные ключи `.env` (печатаются только имена): `BOT_TOKEN`, `DATABASE_URL`, `MINI_APP_URL`. Отдельно печатается,
какие `GOOGLE_SHEETS_*` заданы (тоже только имена). Значения не печатаются нигде; тест это проверяет.

**Требование к выкатываемому SHA:** он должен содержать `628144f`, иначе контрольный `backfill --dry-run` после apply
падает, и выкат останавливается с остановленными сервисами. На момент подготовки `aa9270e` его **не содержит**.
Выкатывать нужно merge-коммит release-PR, в котором есть `628144f`.

---

## 2. Установка скриптов на VPS (владелец, один раз на релиз)

Скрипты ставятся **вне** репозитория прода. Скрипт сам делает `git checkout` в `$PROD_DIR`, а bash читает исполняемый
файл по частям. Скрипт, лежащий внутри checkout, поменялся бы прямо во время выполнения.

```bash
# на машине владельца, из проверенного коммита с этими скриптами (<TOOLS_SHA>)
git show <TOOLS_SHA>:deploy/deploy-production-guarded-run.sh > deploy-production-guarded-run.sh
git show <TOOLS_SHA>:deploy/rollback-production-guarded.sh   > rollback-production-guarded.sh
sha256sum deploy-production-guarded-run.sh rollback-production-guarded.sh
scp deploy-production-guarded-run.sh rollback-production-guarded.sh root@<VPS>:/root/bin/
ssh root@<VPS> 'chmod 700 /root/bin/*-production-guarded*.sh && sha256sum /root/bin/*-production-guarded*.sh'   # те же хэши
```

Нужны на VPS: bash, GNU coreutils/findutils, `setsid`, `flock` (util-linux), `pgrep` (procps), `curl`, `docker compose`
с `run --label`. Всё проверяется в preflight.

---

## 3. Go / no-go (каждый пункт «да» или стоп)

1. CI зелёный на **точном** SHA (Tests, E2E, Security review, Code review). SHA содержит `628144f`.
2. Staging на том же дереве (`git diff --stat <staging SHA> <SHA>` пуст) и прошёл guarded-выкат.
3. Репетиция §4 пройдена на свежей копии прод-дампа, числа записаны (время миграции и backfill, onboarded, migrated).
4. `preflight` (§6.1) зелёный не раньше чем за час до окна. Свободно ≥ 3 ГБ диска, available RAM ≥ 400 МБ.
5. На время окна выключены staging-деплои (`deploy-staging.yml`, guarded staging). Скрипт откажется, если увидит
   запущенный `deploy-staging*-run.sh` или `deploy-run.sh`.
6. Объявление пользователям отправлено (§5). Владелец на связи ещё ≥ 2 часа после окна.
7. Внешняя копия последнего дампа и `.env`/`secrets/` у владельца (вне VPS, зашифрованно; дамп содержит ПДн).

---

## 4. Репетиция на копии прод-дампа (до окна, не на VPS)

Цель — тем же скриптом пройти `e7c2a4f9d1b3 → b5d8e1f3a6c9` + полный backfill + проверки + откат R3 на реальных
данных. Нужен **Linux** с Docker: `setsid`/`flock`/`/proc`, GNU `find -printf`. На macOS — внутри Linux-VM (не проверено).

1. Снять предварительный дамп прода (только чтение, сервисы работают):
   `ssh root@<VPS> 'cd /root/pullup-trainer-bot && docker exec $(docker compose ps -q db) sh -c "pg_dump -U \"\$POSTGRES_USER\" -Fc \"\$POSTGRES_DB\""' > prod-copy.dump`.
   Этот дамп годится только для репетиции, не для отката.
2. Отдельный каталог-клон репозитория (например `/srv/rehearsal/pullup-trainer-bot`), checkout `37b989c`, `.env` с
   **тестовым** `BOT_TOKEN` (не прод-токен: два polling-клиента на одном токене мешают друг другу) и
   `MINI_APP_URL=https://rehearsal.invalid`, `DATABASE_URL=…@db:5432/pullup`.
3. `docker compose -p pullup-rehearsal up -d db`, восстановить дамп (`pg_restore --no-owner -d pullup`), затем
   `docker compose -p pullup-rehearsal build app web && docker compose -p pullup-rehearsal up -d app web` — старый код,
   как на проде. `app` с тестовым токеном может перезапускаться: скрипту нужен только существующий контейнер.
4. Прогон:
   ```bash
   PROD_DIR=/srv/rehearsal/pullup-trainer-bot PROD_PROJECT=pullup-rehearsal PROD_BACKUP_DIR=/srv/rehearsal/backups \
     /path/deploy-production-guarded-run.sh <SHA> rehearse-check
   ```
   Режим идёт тем же путём, что apply: сборка → бэкап → стоп → финальный бэкап → миграция → backfill (dry-run, apply,
   повтор, контрольный dry-run) → инварианты. Затем поднимает **только web**, проверяет `/health` и снова его
   останавливает. Бот не стартует никогда. Режим отказывается работать на проде: проект `pullup-trainer-bot`, каталог
   `/root/pullup-trainer-bot` или прод-`MINI_APP_URL` → отказ.
5. Записать из вывода: `migration took`, `backfill apply took`, `onboarded`, `will_migrate`, отчёты в
   `prod-backfill-*/` (`1-dry-run.txt` … `5-repair-plan-dry-run.json`). **Любое `РАСХОЖДЕНИЕ` в отчёте backfill — стоп**:
   скрипт считает его отказом, и на проде будет так же.
6. Проверить продукт на копии (план §3.4 п. 9–10): старый образ на новой схеме (доказательство для R2), новый web
   для 2–3 реальных пользователей (план не «0 из 0», Журнал = legacy-история).
7. Репетиция отката: `…/rollback-production-guarded.sh R3 <manifest из вывода> check`, затем `apply ROLLBACK-R3-<run_id>`.
   Засечь время. Ожидаемо: `alembic_version = e7c2a4f9d1b3`, старые образы, мигрированная БД сохранена как
   `pullup_failed_<ts>`.
8. Уничтожить копию: `docker compose -p pullup-rehearsal down -v`, удалить дампы по правилам хранения.

Критерий: шаги 4–7 зелёные. Окно (§5) рассчитывается по замеренным временам.

---

## 5. Окно обслуживания и коммуникация

* Окно — 60 минут (D1; рекомендовано будни 03:00–04:00 МСК или время, когда владелец на связи). Простой — от фазы 4
  (стоп) до фазы 10 (старт). Оценка 10–20 минут: два дампа с пробным восстановлением, миграция — секунды, backfill —
  по репетиции, старт — 1–4 минуты. Сборка идёт **до** простоя.
* За 24 часа и за 1 час до окна — сообщение пользователям (рассылку делает владелец): «Бот и Личный кабинет
  будут недоступны с HH:MM до HH:MM (МСК). Сообщения боту в это время не будут обработаны — повторите их после».
  На старте бот вызывает `delete_webhook(drop_pending_updates=True)`, поэтому сообщения из окна теряются.
* Во время окна — статус в канале владельца. После отката — «обновление отложено, всё работает как раньше».
  При R3 дополнительно: «записи за HH:MM–HH:MM нужно внести заново», плюс адресно тем, кто платил в окно.

---

## 6. Выкат (владелец, root, в `tmux`)

### 6.1 Preflight (только чтение, можно запускать сколько угодно раз)

```bash
tmux new -s release
cd /root && git -C /root/pullup-trainer-bot fetch origin        # preflight сам не делает fetch: он ничего не пишет
/root/bin/deploy-production-guarded-run.sh <SHA> preflight
```

Печатает: HEAD прода и целевой SHA, `alembic current`, размер БД, счётчики legacy-таблиц, свободный диск и память,
последние бэкапы, контейнеры и образы проекта, имена ключей `.env` (обязательные и `GOOGLE_SHEETS_*`), URL healthcheck.
Ничего не пишет: без fetch, без временных файлов, без блокировки, без `docker tag/stop/build/run`. Любое расхождение
с §1 — отказ с причиной.

### 6.2 Apply

```bash
/root/bin/deploy-production-guarded-run.sh <SHA> apply PRODUCTION-APPLY-<первые 12 символов SHA> 2>&1 | tee /root/backups/release-<SHA7>.log
```

Без точного токена скрипт отказывается до любых действий. Фазы:

| # | Что делает | Пишет | Простой |
|---|---|---|---|
| 0 | preflight + `git fetch` + точный SHA + `628144f` в истории | — | нет |
| 1 | теги `local/prod-{app,web}:pre-<sha7>-<ts>` на ID работающих образов, manifest `prod-pre-<sha7>-<ts>.manifest` | manifest | нет |
| 2 | `git checkout --detach <SHA>`, сборка `app`, затем `web` (`COMPOSE_PARALLEL_LIMIT=1`) | образы | нет: контейнеры работают на прежних ID |
| 3 | бэкап **до** остановки: `pg_dump -Fc` + sha256 + `pg_restore -l` + пробное восстановление в `pullup_restore_check` | `prod-prestop-*.dump` | нет |
| 4 | `stop app web`; 0 чужих соединений; счётчик записей стабилен `PROD_QUIESCE_SECONDS` | — | **начало** |
| 5 | финальный бэкап (точка R3) с той же проверкой; счётчики восстановленной копии = живой БД; снимок хэшей ДО-таблиц | `prod-pre-*.dump` | да |
| 6 | `alembic heads` = ровно `b5d8e1f3a6c9`; `alembic upgrade head` (одна транзакция) | схема | да |
| 7 | каждая ДО-таблица (число строк + md5 ДО-колонок) идентична снимку | — | да |
| 8 | backfill: `--dry-run` (сверка onboarded с БД, БД не изменилась) → apply (без `РАСХОЖДЕНИЕ`, мигрировано = dry-run) → повтор (0 мигрировано, БД не изменилась) → контрольный `--dry-run` (0 к миграции) → `--converge-history` dry-run (`mutations=0`) → `repair_plan_convergence.py --all` dry-run (0 нарушений guard'ов) | таблицы v2 | да |
| 9 | ДО-таблицы всё ещё идентичны; онбордившиеся без плана = 0; у каждого плана ровно одна активная инклюзия; дублей `(origin, legacy_id)` нет; планов = onboarded | — | да |
| 10 | `up -d --no-build app web`; `/health` ≤ 240 с; app/web Running, не Restarting; запущены именно собранные ID | — | **конец** |
| 11 | итог и команда R3; ротация старых дампов (оставляет `PROD_KEEP_BACKUPS` предыдущих). `post-deploy-cleanup.sh` **не** запускается | — | — |

**Почему порядок жёсткий.** Писатели (бот и web) остановлены с фазы 4 до фазы 10, без трафика между миграцией и концом
проверок. Репетиция показала (REHEARSAL_REPORT §5): пишущие маршруты (например, `POST /program-inclusions`) создают
`TrainingPlan`. После этого backfill пропускает пользователя: он попадает на V5.6 и теряет историю факультативов.
Простой `GET /api/v2/plan` план не создаёт. Кроме того, хэши `users` законно меняются на GET-запросах (статус подписки),
поэтому все сравнения хэшей делаются до старта сервисов.

`repair_plan_convergence` в окне только проверяется (dry-run, решение D3 не принято). Ленивые мутации плана сделает
рантайм на первом `GET /plan`.

### 6.3 Сбой

* **До фазы 4** (сборка, бэкап до остановки, preflight): прод продолжает работать на прежних контейнерах, checkout и
  теги `:latest` возвращены к прежним. БД не тронута. Отката не нужно.
* **После фазы 4**: `app`/`web` **остаются остановленными** (даже если уже были запущены). Вывод и
  `prod-guarded-<sha7>-<ts>.FAILED.txt` содержат причину, фазу и **точную команду отката**: R1, если `alembic_version`
  не менялась и backfill не начинался, иначе R3.
* Сигнал (обрыв SSH, Ctrl-C, TERM) ведёт себя так же. One-off контейнеры запуска (метка `guarded.run=<run_id>`)
  останавливаются. После `SIGKILL` очистки нет: следующий запуск откажется из-за оставшихся контейнеров с меткой
  `guarded.run`. Их надо осмотреть, удалить вручную (`docker rm -f`) и проверить, что `app`/`web` остановлены.
* Повторный запуск после сбоя в фазах 6–9 без отката невозможен: ревизия уже `b5d8e1f3a6c9`, а скрипт ждёт
  `e7c2a4f9d1b3`. Нормальный путь — R3, затем новый apply. `PROD_EXPECTED_FROM_REV=b5d8e1f3a6c9` (продолжение)
  допустим только осознанно: дамп такого запуска уже послемиграционный, точкой R3 остаётся дамп первого запуска.

---

## 7. Откат

Окно решения — первые 30–60 минут. Чем дольше работает новый код, тем больше теряет R3. Все факты берутся из manifest
того выката. Сначала всегда `check` (только чтение: печатает, что будет сделано и что будет потеряно), затем `apply` с
токеном `ROLLBACK-<R1|R3>-<run_id>` (`run_id` есть в manifest и в выводе выката).

### 7.1 R1 — прежние образы, БД не меняется

```bash
/root/bin/rollback-production-guarded.sh R1 /root/backups/prod-pre-<sha7>-<ts>.manifest check
/root/bin/rollback-production-guarded.sh R1 /root/backups/prod-pre-<sha7>-<ts>.manifest apply ROLLBACK-R1-<run_id>
```

Допустим, только если `alembic_version` = `previous_alembic` manifest и в manifest нет `backfill_started_at`. Иначе
отказ. Порядок: `stop app web` → `git checkout --detach <previous_sha>` → `docker tag <прежний ID> <имя образа compose>`
→ `up -d --no-build app web` → `/health` → проверка, что запущены прежние ID. Потерь данных нет.

### 7.2 R2 — старый код на новой схеме (не автоматизирован)

Используется только если репетиция §4 п. 6 доказала совместимость `37b989c` с `b5d8e1f3a6c9`. Тогда это шаги R1 без
проверки ревизии (план §6.2 R2). Скрипт R2 не делает намеренно: совместимость на проде не доказана.

### 7.3 R3 — восстановление дампа до выката

```bash
/root/bin/rollback-production-guarded.sh R3 /root/backups/prod-pre-<sha7>-<ts>.manifest check
/root/bin/rollback-production-guarded.sh R3 /root/backups/prod-pre-<sha7>-<ts>.manifest apply ROLLBACK-R3-<run_id>
```

Порядок: проверка дампа (sha256 = manifest, оглавление, свободный диск ≥ 3 × дамп + 1 ГБ) → `stop app web`, 0 соединений
→ восстановление в **новую** БД `pullup_rb_<ts>` (`--single-transaction --exit-on-error`), в ней `alembic_version` =
`previous_alembic` и счётчики `users/workouts/elective_workouts/subscriptions` = manifest → **одной транзакцией**
`ALTER DATABASE pullup RENAME TO pullup_failed_<ts>; ALTER DATABASE pullup_rb_<ts> RENAME TO pullup` (атомарность
переименования проверена на `postgres:16`) → прежние образы и checkout → `up -d` → `/health` → проверка ID.
Живая БД не удаляется: она остаётся как `pullup_failed_<ts>`. Удалить её владелец может сам, когда данные окна
разобраны.

### 7.4 Окно потери данных R3

Теряется всё, что записано после `backup_at` manifest. Это вся активность с момента старта новой версии до остановки
перед откатом: тренировки (бот и Mini App), онбординги, замеры, настройки, **оплаты и продления подписок**, монеты и
ачивки. Данные остаются в `pullup_failed_<ts>`. После отката нужно:

1. сверить платежи за окно в кабинете Robokassa и в истории Stars, вручную продлить оплативших;
2. Google Sheets: курсоры `sheets_sync` откатились вместе с БД, строки окна могут продублироваться в инкрементальных
   листах. Проверить и при необходимости перегенерировать по образцу `scripts/backfill_sheets_username.py`;
3. отправить сообщение пользователям (§5).

### 7.5 Если прежних образов нет

`rollback-production-guarded.sh` откажется (`previous … image … no longer exists`). Так бывает, если кто-то запустил
`post-deploy-cleanup.sh` / `docker image prune` до конца наблюдения. Тогда старый код надо собрать из `previous_sha`
вручную, это не автоматизировано. Поэтому `post-deploy-cleanup.sh` — только после периода наблюдения (D6). Теги
`local/prod-*` dangling-очистка не трогает.

### 7.6 После любого отката

Не запускать `deploy.yml` / `deploy-run.sh` для этого SHA: старый `deploy-run.sh` после R2 упадёт на
`alembic upgrade head`, а после R3 мигрировал бы при работающих сервисах. Следующая попытка — только guarded-скриптом.

---

## 8. Смоук после выката (15 минут, аккаунт владельца и второй, не-админский)

1. `curl -fsS http://127.0.0.1:8001/health`; снаружи `https://app.bimoool.com/health`.
2. Бот: `/start`, нижнее меню, кнопка меню «Личный кабинет» открывает `app.bimoool.com`. В профиле админа **нет**
   «🧪 Fresh reset».
3. Старый пользователь: Mini App без ошибки, на «Планах» курс «Подтягивания» с прежними целями (не «0 из 0»), Журнал =
   прежние тренировки (группировка по локальному дню — ожидаемое изменение).
4. Новый пользователь: онбординг → V5.6 → тренировка → Журнал. Своя тренировка → старт → завершение → удаление.
5. SQL (только числа): `alembic_version = b5d8e1f3a6c9`; `count(training_plans)` ≥ onboarded до выката.
6. Наблюдение 24 часа (план §5.2): логи `ERROR|Traceback|UndefinedColumn`, `docker stats`, `free -m`, воркеры.
   Оповещения CI/деплоя не работают (#236).

---

## 9. Что не проверено и какие факты нужны с прода

* Скрипты **ни разу не запускались** на настоящем Docker/Postgres. Проверены только поток и fail-safe на заглушках
  (`tests/test_scripts/test_deploy_production_guarded.py`), `bash -n` и `shellcheck`. Первый живой прогон — репетиция §4.
* Факты прода, которые скрипт сверяет, но которые никто не видел: текущая `alembic_version` (ожидается `e7c2a4f9d1b3`),
  `POSTGRES_DB`/`DATABASE_URL` (ожидается `pullup`), метки compose-проекта (`working_dir`, `config_files` — нет ли
  override), порт web, `MINI_APP_URL` в `.env` ровно `https://app.bimoool.com`, размер БД, свободный диск и память,
  версия docker compose (`run --label`), наличие `setsid`/`flock`/`pgrep` у root. Любое расхождение даст отказ в preflight.
* Время двух дампов с пробным восстановлением и время backfill на прод-объёме неизвестны: замерить на репетиции.
* Поведение полного backfill на прод-форме данных (`РАСХОЖДЕНИЕ`, строгая идемпотентность по хэшам всех таблиц) — только
  на репетиции. Если повторный apply законно трогает какие-то поля (например, временные метки), скрипт откажет; это
  надо увидеть на репетиции, а не в окне.
* Совместимость старого кода с новой схемой (R2), поведение FSM в Redis после смены хендлеров, кэш старого бандла Mini App.
* `pg_restore --single-transaction` R3 на прод-дампе и атомарная перестановка БД — проверены только на пустой
  `postgres:16` локально; на прод-дампе — на репетиции §4 п. 7.
* Выкатываемый SHA должен содержать `628144f`; `aa9270e` его не содержит (§1).

## 10. Выкат из GitHub Actions (постоянный ручной путь)

Тот же guarded-скрипт, запуск — кнопкой в Actions вместо ручного SSH. `deploy.yml` остаётся заблокированным.

* **Workflow:** `production-deploy.yml` (preflight / apply) и `production-rollback.yml` (R1 / R3, check / apply). Оба запускаются только
  вручную (`workflow_dispatch`), в одной группе `concurrency: production` — второй запуск ждёт, текущий не отменяется.
* **Проверки до SSH:** точный 40-hex SHA; SHA содержит текущий `origin/main` **или** уже влит кнопкой merge (main содержит
  SHA и дерево файлов main с ним совпадает); на этом SHA зелёные `pytest`, `ruff`, `frontend build` и нет красных или
  незавершённых проверок; для apply — токен `PRODUCTION-APPLY-<первые 12 символов SHA>`.
  `tests.yml` запускается только на PR (в т.ч. на изменения `deploy/**` и workflow выката), поэтому выкатывается
  головной SHA release-PR — до или после его мержа в `main`, но не merge-коммит.
* **Ревизии Alembic** (`from_rev`, `to_rev`) задаются явно; guarded-скрипт сверяет их с живой БД и с образом. Без миграций
  в релизе обе равны текущему head (`b5d8e1f3a6c9` на 17.10.2026) — это штатный «повторный» прогон скрипта (§6).
* **Доступ:** отдельный ключ, секрет `PROD_GUARDED_SSH_KEY`, на сервере строка
  `restrict,command="/root/bin/prod-guarded-dispatch.sh" … gh-actions-prod-guarded` в `/root/.ssh/authorized_keys`.
  Диспетчер принимает только `prod-guarded <sha> preflight|apply <from> <to> [token]` и
  `prod-rollback R1|R3 /root/backups/<…>.manifest check|apply [token]`, окружение вызывающего не пропускает (`env -i`),
  второй параллельный запуск отклоняет (`flock`). Ключи `deploy.yml` и staging не меняются.
* **Настройка — один раз, от root на VPS** (веб-консоль DigitalOcean подходит), из проверенного коммита `<SHA>`:
  ```bash
  git -C /root/pullup-trainer-bot fetch -q origin <SHA> && git -C /root/pullup-trainer-bot show <SHA>:deploy/install-prod-actions-access.sh | bash -s -- <SHA>
  ```
  Скрипт ставит в `/root/bin` guarded-скрипты и диспетчер из этого коммита (печатает sha256), выпускает ключ, прописывает
  forced command, печатает приватный ключ один раз и удаляет его с сервера. Напечатанный ключ — в секрет
  `PROD_GUARDED_SSH_KEY`. Повторный запуск выпускает новый ключ и отзывает старый. После изменения guarded-скриптов в
  репозитории установщик запускают снова (самообновления нет; workflow предупреждает о расхождении).
* **Хост-ключ** берётся `ssh-keyscan` при каждом запуске (как и в прежних workflow через `appleboy/ssh-action`). Поддельный
  хост не получает ничего полезного: ключ ed25519 не переиспользуется для входа на настоящий сервер. Закрепить хост-ключ
  секретом можно позже отдельным изменением.
* **Порядок:** preflight → прочитать вывод → apply с токеном. Обрыв соединения во время apply — fail-safe скрипта
  (§6): `app`/`web` остаются остановленными, в логе Actions — точная команда отката, её параметры вводятся в
  `production-rollback.yml`.

## Already-migrated no-schema hotfix: verified read-only backfill path

For a candidate with the same Alembic head as the live database, the guarded
production runner now checks for onboarded users lacking a plan. If none are
missing, it runs the candidate's `scripts/backfill_multi_program.py --verify-only`
**before stopping app/web**. Verification failure aborts before downtime; it does
not fall back to a mutating repair. Initial migrations with missing plans retain
the existing full backfill flow and its strict guards.

`--verify-only` requires its own fresh transaction and uses PostgreSQL
`REPEATABLE READ, READ ONLY`. It checks plan/user/inclusion consistency, duplicate
keys, keyed coverage for every completed legacy workout and elective (including
users not in the onboarded count), existing catalog, and the existing history
convergence semantics. Missing/changed copies, unknown ownership states, history
mutations or ambiguity reject release. It never calls seed/normalization/calendar
materialization. Normal runtime may later advance the current calendar; release
verification deliberately does not require calendar convergence mutations to be zero.

After writers stop, phase 8 reruns verification twice. It still checks full database
fingerprints, `same_legacy`, post-apply dry-run/no-write controls, plan guards and
all existing final invariants. This is not a whitelist of mutable plan tables.
The verifier is only selected if pre-stop verification passed and the stopped
backfill dry-run still sees all onboarded users migrated. No plan/calendar or
historical repair is silently permitted by this mode.

Before using it on production:

1. Apply the implementation patch to the actual reviewed hotfix/main SHA; it does
   not include the REST fix itself. Require PostgreSQL tests and existing CI green
   on that combined SHA. Source files at bd80bc9 and d1b2375 were independently
   confirmed identical for the production runner/backfill; recheck newer bases.
2. On an isolated fresh production DB copy, disable outbound Telegram and rehearse
   the exact runner/candidate. Save verifier JSON, table fingerprints, rollback
   rehearsal and plan dry-run report. Inspect the row diff from the prior failed
   backfill separately; synthetic tests do not reproduce that database.
3. Review/install the production runner from the exact tested commit at the path
   used by the forced-command dispatcher. Record its sha256. Do not substitute
   a candidate without `--verify-only` support; it will safely refuse before stop.
4. Run read-only preflight, then only the previously authorized guarded operation
   with the exact candidate SHA. Existing rollback/runbook restrictions remain.

The candidate has no schema changes. This mode fixes deployment preservation;
it does not patch active session `engine_plan` or historical prescriptions. Keep
active-session recovery separate, preserving plan/snapshot/event replay consistency.
