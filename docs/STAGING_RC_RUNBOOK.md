# Staging runbook: release candidate #322 + #323 (PR #324)

**Только подготовка. Ни одна команда этого документа не выполнялась на staging; деплой делает владелец.**

> **Статус готовности: BLOCKER, деплой на staging не разрешён.**
> 1. Ждём финалы двух исправлений: **(IDB)** ворота drain-before-projection при сбое чтения IndexedDB и **(legacy convergence)**
>    случай отредактированных/удалённых копий факультативов. В этом документе они **не** реализованы. Полный gate — после их объединения.
> 2. CI E2E на кандидате красный (2 из 2), причина не подтверждена — `docs/STAGING_RC_CI_E2E.md`.
> 3. Деплой — только через **guarded staging entrypoint** (§3): точный SHA, проверенный backup, остановленные app/web, последовательная сборка,
>    миграция, проверки данных, запуск только после успеха. **Он не установлен на VPS** (команды владельцу — §3.2) и ни разу не запускался на реальном сервере.
> 4. Версия Docker Compose CLI на VPS **неизвестна** (`2.40.3` в labels контейнеров — версия, создавшая контейнеры, а не доказательство текущей CLI).
> 5. HOLD на `--apply` convergence — §6.2 (скрипт сам проверяет его в режиме `apply`).

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

## 3. Деплой: guarded staging entrypoint (действие владельца; на VPS ничего не устанавливалось и не запускалось)

### 3.0 Почему не старый `deploy-staging-run.sh` и не hold-override

Старый wrapper (со слов владельца: `set -euo pipefail; git fetch; git checkout "$branch"; git pull --ff-only; docker compose -p pullup-staging build app web;
run --rm app alembic upgrade head; up -d; healthcheck :8002; /usr/local/bin/post-deploy-cleanup.sh`; остальное и серверный cleanup **не проверены**) принимает ветку, не фиксирует SHA,
не делает backup и convergence, не останавливает писателей и сам запускает `app`/`web` до любой проверки данных; откат им после миграции невозможен
(старый `alembic upgrade head` падает на `b5d8e1f3a6c9`, проверено). Вариант `profiles`-override с ожидаемым провалом healthcheck **отвергнут как финальный путь**
(красный workflow как норма, скрытые строки скрипта). Старый wrapper не меняется и остаётся как есть; прод-деплой не затрагивается.

### 3.1 Что выкатывается и чем

| Файл (в ветке кандидата) | Роль |
|---|---|
| `deploy/deploy-staging-guarded-run.sh` | сам выкат (9 фаз ниже); ставится на VPS вручную как `/home/deploy/deploy-staging-guarded-run.sh` |
| `deploy/deploy-staging-guarded-dispatch.sh` | forced command **отдельного** SSH-ключа; принимает ровно `./deploy-staging-guarded.sh <40-hex-sha> <dry-run\|apply> <yes\|no>` и блокировку `flock` |
| `.github/workflows/deploy-staging-guarded.yml` | `workflow_dispatch`: вход `sha` (точный, не ветка), `converge` (`dry-run`\|`apply`), `start` (`no`\|`yes`); валидирует вход, проверяет, что SHA есть в репозитории и несёт нужные файлы |
| `deploy/staging_data_check.sh`, `deploy/staging-allowed-diff.txt`, `docs/rehearsal/sql/gen_hash_queries.sql` | проверки данных (§6); скрипт читает их через `git show <SHA>:…` — из выкатываемого коммита |

Переиспользовано без изменений: `docker compose -p pullup-staging …` (проект, порт 8002, healthcheck URL — как в `deploy-staging-run.sh`), `scripts/repair_plan_convergence.py --all`,
`scripts/backfill_multi_program.py --converge-history`, `/usr/local/bin/post-deploy-cleanup.sh` (после полного успеха, как в `deploy/deploy-run.sh`). Новых фреймворков нет: один shell-скрипт, один dispatcher, один workflow.

**Фазы** (любая ошибка ⇒ `app`/`web` остаются **остановленными**, сохранённые образы и backup на месте, авто-отката нет):

| # | Фаза | Что гарантирует |
|---|---|---|
| 0 | preflight | аргументы строго 40-hex/режимы; `docker-compose.yml`+`.env` на месте; рабочее дерево чистое; `git fetch` и коммит существует; файлы проверок есть **в этом SHA**; db-контейнер принадлежит проекту `pullup-staging`, имя БД содержит `staging`; свободно ≥ 2 ГБ диска; логируются версия Compose и память |
| 1 | сохранить образы | текущие образы `app`/`web` получают теги `local/staging-{app,web}:pre-<sha7>-<UTC>` (откат без Alembic, §8.2); нет контейнера ⇒ стоп |
| 2 | остановить писателей | `stop app web`; 0 чужих соединений с БД; счётчик записей `sum(n_tup_ins+n_tup_upd+n_tup_del)` не меняется за 15 с |
| 3 | backup | `pg_dump -Fc` → `/home/deploy/backups/staging-pre-<sha7>-<UTC>.dump` + `.sha256`; оглавление; **восстановление в `restore_check`**: та же `alembic_version`, те же счётчики; счётчик записей не изменился; снимок «до» (хэши ДО-колонок всех таблиц с `id`) |
| 4 | checkout | `git checkout --detach <SHA>`; `HEAD == SHA`, дерево чистое |
| 5 | сборка | `COMPOSE_PARALLEL_LIMIT=1`: `build app`, затем `build web` (последовательно, лог памяти); запоминаются ID собранных образов |
| 6 | миграция | один Alembic head; `alembic_version` должна быть `c3f7a9e2d5b1` (или уже head — тогда предупреждение), иначе стоп; `upgrade head` (одна транзакция); версия = head |
| 7 | проверки данных | `staging_data_check.sh after-migration`: число строк ДО-таблиц не изменилось, изменённые таблицы ⊆ `staging-allowed-diff.txt`, предикат `work_sets`, `origin` ∈ допустимых |
| 8 | convergence | dry-run обоих скриптов (`guard_violations` = 0, БД не изменилась). `apply`: `hold-check` (риск дублей факультативов) = 0 → `--apply` → повторный `--apply` без изменений → `after-convergence` (меняться могли только 6 таблиц; ранее существовавшие строки `training_sessions`/`session_blocks`/`set_logs` не изменены; дублей `(origin, legacy_id)` нет) |
| 9 | старт | `start=yes`: `up -d --no-build app web`; healthcheck `http://127.0.0.1:8002/health` ≤ 240 с; контейнеры запущены, не перезапускаются, **образ запущенного контейнера = образу, собранному в фазе 5**; health `app`/`web` не `unhealthy`; `HEAD == SHA`; `alembic_version = head`; затем `post-deploy-cleanup.sh`. `start=no`: проверки пройдены, сервисы **остаются остановленными** (код 0, сообщение «NOT started») |

Итог «success» (код 0 и строка `GUARDED DEPLOY OK`) — **только** при полном успехе всех фаз при `start=yes`. `start=no` печатает `VERIFIED (services NOT started)`.

### 3.2 Установка на VPS (команды владельцу; я их не выполнял и не выполняю)

Делается один раз, до первого запуска, **после** финального candidate SHA (скрипты берутся из него). Каждый шаг — отдельное решение владельца.

```bash
# (a) на машине владельца: ключ для guarded-деплоя (отдельный от существующих)
ssh-keygen -t ed25519 -N '' -C guarded-staging -f ./guarded_staging_key        # приватный ключ -> GitHub secret VPS_STAGING_GUARDED_SSH_KEY, затем удалить файл

# (b) на VPS под пользователем deploy: скрипты ИЗ КОММИТА КАНДИДАТА (проверить хэши до установки)
git -C /home/deploy/pullup-trainer-bot-staging fetch origin                       # меняет только .git; рабочее дерево не трогает
for f in deploy-staging-guarded-run.sh deploy-staging-guarded-dispatch.sh; do
  git -C /home/deploy/pullup-trainer-bot-staging show <CANDIDATE_SHA>:deploy/$f > /home/deploy/$f.new
  sha256sum /home/deploy/$f.new                                                   # сверить с хэшем из ревью PR
  install -m 755 /home/deploy/$f.new /home/deploy/$f && rm /home/deploy/$f.new
done
command -v flock curl awk sha256sum docker git df free du mktemp                   # все должны найтись

# (c) forced command в ~/.ssh/authorized_keys — ОДНА новая строка (публичный ключ из (a)); существующие строки не менять
command="/home/deploy/deploy-staging-guarded-dispatch.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA… guarded-staging
```
В GitHub: secret `VPS_STAGING_GUARDED_SSH_KEY` (+ уже существующий `VPS_HOST`). Существующий forced-command, `deploy-staging-dispatch.sh` и прод-ключ **не меняются** и не обходятся: у guarded-ключа свой
forced command, принимающий один литеральный паттерн. Чтобы выкат шёл обновлённым скриптом, после смены `deploy-staging-guarded-run.sh` его снова ставят вручную (самообновления нет).

### 3.3 Порядок запусков

1. **Предпроверка:** Actions → *Deploy Staging (guarded)* → `sha` = окончательный candidate SHA, `converge` = `dry-run`, `start` = `no`. Результат: backup, миграция, проверки данных, dry-run convergence; `app`/`web` остановлены. Миграция при этом **применяется** (состояние БД = `b5d8e1f3a6c9`); последующий запуск пропустит `upgrade` с предупреждением, а pre-migration backup — файл предыдущего запуска (его не удалять). Если предпроверка не нужна — сразу п. 2.
2. **Выкат:** тот же SHA, `converge` = `apply` (только после принятого фикса legacy convergence), `start` = `yes`.
3. После `GUARDED DEPLOY OK`: §3.4 и §7. Ошибка — §3.5 и §8; **сервисы сами не запускаются**.

Деплой-ветка больше не нужна: workflow принимает точный SHA, достаточно, чтобы коммит был на `origin` (`git fetch origin` на сервере). «Заморозка» — это сам SHA; перед запуском сверить, что
SHA = записанному при принятии gate (`git ls-remote origin <ветка кандидата>` и `git diff --stat <GATE_CODE_SHA> <SHA> -- . ':!docs'` — только принятые фиксы).

### 3.4 Проверка факта выката (кроме встроенной в фазу 9)

```bash
cd /home/deploy/pullup-trainer-bot-staging
git rev-parse HEAD; git status --short                                         # == SHA; пусто
docker compose -p pullup-staging ps -a; docker compose -p pullup-staging images
docker exec pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # b5d8e1f3a6c9
ls -l /home/deploy/backups/                                                    # дамп, .sha256 (переносить копию вне VPS)
docker images --format '{{.Repository}}:{{.Tag}}' | grep '^local/staging-'     # образы для отката
```
Образ не несёт SHA (в нём нет `.git`): «запущена эта сборка» подтверждается равенством ID образа запущенного контейнера образу, собранному этим запуском, и `HEAD == SHA` на момент сборки.

### 3.5 Сбой по фазам (во всех случаях `app`/`web` остановлены)

| Фаза сбоя | Состояние БД и кода | Что делать |
|---|---|---|
| 0 (preflight) | ничего не менялось, `app`/`web` работают как раньше | исправить причину, повторить |
| 1–3 (образы, остановка, backup) | `app`/`web` остановлены; БД, образы и дерево не менялись; backup (если дошло) цел | `docker compose -p pullup-staging start app web` (те же контейнеры и образы); разобрать причину |
| 4–6 (checkout, сборка, миграция) | БД не менялась (при сбое миграции — атомарно `c3f7a9e2d5b1`); рабочее дерево на новом SHA; теги образов `pullup-staging-app/-web` **могли уже указывать на новые образы** | вернуть старые образы под имена compose (§8.2: `docker tag local/staging-{app,web}:pre-… <имя из docker compose images>`), `git checkout --detach <прежний SHA>`, затем `docker compose -p pullup-staging up -d --no-build app web`; разобрать причину |
| 7–9 | схема `b5d8e1f3a6c9`, данные возможно сведены | §8: код (если convergence не применялась) или данные (если применялась) |

Логи фаз — `/tmp/guarded-deploy.*` (путь печатается в конце), состояние для отката — в блоке `state for rollback` вывода.

### 3.6 Воспроизводимая сборка фронтенда — исправлено

`Dockerfile.web` копировал только `package.json` и делал `npm install` (диапазоны `^`/`~` резолвились заново на каждой сборке). Исправлено отдельным коммитом (`b1d00f2`): копируются `package.json` и
`package-lock.json`, команда `npm ci`. **Проверено реальной сборкой Docker** (демон в песочнице, `docker build -f Dockerfile.web`, базовый образ `node:20-slim` = Node v20.20.2 / npm 10.8.2,
`python:3.12-slim`): `npm ci` и `vite build` прошли; контейнер отдаёт `/health`, `/` и ассет; установленные версии (145 пакетов) совпали с `package-lock.json` (0 расхождений); имена
собранных ассетов (`index-C7H_6_JJ.js`, `index-CQDMHGK4.css`) совпали с локальной сборкой по lock-файлу. **Условия проверки (непроверенное):** песочница ходит в сеть через прокси,
поэтому использованы локальные копии базовых образов с корпоративным CA и заглушкой `apt-get install procps` (Debian-зеркала заблокированы); базовые образы взяты с зеркала `mirror.gcr.io`
(тот же digest, что `node:20-slim`); образ `app` и реальный `apt-get`, а также сборка на VPS (RAM ≈ 704 МиБ, свой Docker/BuildKit) не проверялись.

### 3.7 Как это проверено без VPS и что осталось непроверенным

* **Реальный Docker/Compose в песочнице** (Compose v5.6.0, изолированный демон): мини-«staging» (проект `pullup-staging`, код `4298f8b`, данные схемы `c3f7`), реальный запуск скрипта на коммите `3f8e919`
  (отличие от финального — только текст одного сообщения об ошибке): **S1** `apply`+`yes` — все 9 фаз, образы запущенных контейнеров = собранным; **F1** `apply` на данных с рискованными факультативами — стоп на hold-check,
  `app`/`web` остановлены, backup и образы целы; **F2** неверный health URL — стоп в фазе 9, `app`/`web` остановлены; **S2** `dry-run`+`no` — успех, сервисы остановлены. Откат §8.3+§8.2 теми же командами —
  данные из дампа, сохранённые образы, `up -d --no-build`: `alembic_version = c3f7a9e2d5b1`, health OK, образы = сохранённым. В песочнице `app`-контейнер подменён простым процессом (нет Telegram), health `app` — заглушка.
* **Тест потока** `tests/test_scripts/test_deploy_staging_guarded.py` (заглушки docker/git/curl, 30 проверок; мутации «trap не останавливает», «старт до проверок данных», «убрана сверка счётчиков восстановленной копии» ловятся).
* **Проверки данных** `staging_data_check.sh` на реальных репетиционных БД: позитивный путь и 6 негативных (подмена данных падает).
* **Не проверено:** запуск на VPS (версия Compose CLI неизвестна; `docker compose run -T`, `up -d --no-build`, `stop`, `config --images` на сервере; права пользователя `deploy`; наличие `flock`/`curl`/`awk`); поведение sshd с `no-pty` и
  `appleboy/ssh-action` для 60-минутной команды; серверный `post-deploy-cleanup.sh`; сборка при ≈ 704 МиБ (ограничение — последовательные сборки, пик не измерен); реальные данные staging; запуск самого GitHub workflow.

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

Бэкапа на staging нет (§1.1), БД `pullup_staging` — 10 МБ. **В guarded-выкате backup делает фаза 3 (§3.1)** с теми же проверками; команды ниже — для ручного повторения/проверки
и для ситуации, когда нужен ещё один дамп. Это команды **только для проекта `pullup-staging`**, с именами из §1.1
и защитой: проверка отказывается работать, если контейнер не принадлежит compose-проекту `pullup-staging` (на VPS есть прод и
`reeltrack-*`). Рабочую БД команды не меняют. **Выполнять только при остановленных `app` и `web` (фаза 2, §3.1): записей нет**, —
иначе дамп и «счётчики до» не соответствуют состоянию на момент миграции. Запускать как скрипт (`bash backup.sh`), а не
вставлять `set -e` в интерактивную консоль.

**Backup считается проверенным, когда выполнено всё** (скрипт не идёт к checkout/сборке без этого):
1. дамп-файл создан, `sha256` записан, размер > 0, `pg_restore -l` показывает оглавление (> 10 записей);
2. восстановление в `restore_check` прошло без ошибок, `alembic_version` там = `c3f7a9e2d5b1`;
3. счётчики в `restore_check` равны счётчикам рабочей БД, снятым в той же остановленной системе (§6.1);
4. после дампа счётчик записей (`sum(n_tup_ins+n_tup_upd+n_tup_del)` из фазы 2) **не изменился** — за время backup никто не писал;
5. копия дампа лежит **вне VPS** (на сервере один диск; скрипт этого не делает).

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

### 6.1 До деплоя (только счётчики, без персональных данных; снимать при остановленных `app`/`web`, фаза 2 §3.1). **Снимок «до» (1) и проверки §6.2.0/§6.2.1/§6.3 выполняет сам guarded-скрипт (фазы 3, 7, 8); ручные запросы ниже — для независимой сверки**

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

Порядок строго такой; `app`/`web` всё это время остановлены (фаза 2 §3.1).

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

Критерии: сбой любой фазы guarded-скрипта (§3.5), FAIL в §7, решение владельца. **При сбое скрипта `app`/`web` уже остановлены и остаются остановленными**; скрипт сам
ничего не восстанавливает — он печатает сводку: целевой/предыдущий SHA, путь к дампу, теги сохранённых образов, рабочий каталог.

Что подготавливает сам скрипт (фазы 1 и 3, до любых изменений): теги `local/staging-app:pre-<sha7>-<UTC>` и `local/staging-web:pre-<sha7>-<UTC>` на запущенные образы
(их не удалит `docker image prune -f`) и проверенный дамп `/home/deploy/backups/staging-pre-<sha7>-<UTC>.dump` (+ `.sha256`; `pg_restore -l`, пробное восстановление в
`restore_check`). Ветку отката создавать не нужно: guarded-скрипт принимает SHA.

### 8.1 Старый wrapper на новой revision — НЕ работает (доказано)

`deploy-staging-run.sh` выполняет `alembic upgrade head` старым кодом `4298f8b`. При `alembic_version = b5d8e1f3a6c9` он падает
(`Can't locate revision identified by 'b5d8e1f3a6c9'`, exit 255) до `up -d`. Проверено на копии БД. Wrapper пригоден для отката кода только когда `alembic_version`
снова `c3f7a9e2d5b1` (после `pg_restore`, 8.3). Править строку `alembic_version` вручную нельзя (8.3).

### 8.2 Откат кода без данных: сохранённые образы, без Alembic

Сценарий: миграция прошла (схема `b5d8e1f3a6c9`), **convergence не применялась** (скрипт остановился в фазах 6–8 до `--apply`, либо `converge=dry-run`). Старый код Alembic
при старте не запускает: репетиция — `4298f8b` против новой схемы, 20/20 GET → 200, старт/подходы/завершение live-сессии и запись в Журнал работают
(`docs/STAGING_RC_REHEARSAL.md` §4, §9). Бот (`app.main`) без Telegram не запускался.
```bash
cd /home/deploy/pullup-trainer-bot-staging
docker compose -p pullup-staging stop app web
# вернуть имена, под которыми compose ищет образы (имена — из `docker compose -p pullup-staging config --images`)
docker tag local/staging-app:pre-<sha7>-<UTC> <ИМЯ_ОБРАЗА_APP>
docker tag local/staging-web:pre-<sha7>-<UTC> <ИМЯ_ОБРАЗА_WEB>
git checkout --detach 4298f8b9727f91d4a150431fd0d9e06131944d27         # дерево = образам
docker compose -p pullup-staging up -d --no-build app web             # без сборки и Alembic
curl -sf http://127.0.0.1:8002/health
```
Ограничения: (а) только до convergence — после неё старый интерфейс показывает задвоенные строки плана (репетиция: 4→7, 2→5); (б) схема остаётся новой — следующий деплой
старой веткой wrapper'ом упадёт (8.1); (в) на реальной VPS не проверено.
Эта процедура (теги → `up -d --no-build` → запущенный образ = сохранённый) проверена на настоящем Docker/Compose в песочнице
(`docs/STAGING_RC_REHEARSAL.md` §12), но не на VPS.

### 8.3 После convergence — откат требует возврата данных

После `--apply` данные изменены: новые `plan_items`/`plan_weeks`, `status='removed'`, новые копии `training_sessions` с `legacy_id`, `work_sets = 4`. **Это не вернуть ни сменой
`alembic_version`, ни `alembic downgrade`:**
* `alembic downgrade c3f7a9e2d5b1` откатывает схему; данные сведения и backfill остаются (репетиция: plan_items +19, plan_weeks +3, training_sessions +3, `work_sets=4`);
* ручная правка `alembic_version` при новой схеме: следующий `alembic upgrade head` падает на первой ревизии (`DuplicateTableError: relation "exercise_categories" already exists`).

Единственный путь — **`pg_restore` из дампа** скрипта. Теряет всё записанное после дампа (окно выката записей не содержит — писатели остановлены в фазе 2). Деструктивно:
только по решению владельца.
```bash
cd /home/deploy/pullup-trainer-bot-staging
docker compose -p pullup-staging stop app web
docker exec pullup-staging-db-1 sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker exec -i pullup-staging-db-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < /home/deploy/backups/staging-pre-<sha7>-<UTC>.dump
docker exec pullup-staging-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'   # = c3f7a9e2d5b1
# затем код: 8.2 (сохранённые образы)
```
После отката: счётчики и ДО-хэши равны «до» (§6.1), `alembic_version = c3f7a9e2d5b1`, `git rev-parse HEAD` = `4298f8b…`, health `http://127.0.0.1:8002/health`. Redis (FSM) дамп не затрагивает.
Проверено в песочнице на настоящем Postgres + Docker: восстановление дампа возвращает данные и `alembic_version`, старые образы поднимаются через `up -d --no-build`.

## 9. Известные риски и открытые вопросы

- **BLOCKER: два обязательных фикса не готовы** (ждём финалы): (1) IDB — ворота drain-before-projection при сбое чтения IndexedDB
  (`docs/STAGING_RC_CI_E2E.md`); (2) legacy convergence — отредактированные/удалённые копии факультативов (`docs/STAGING_RC_REHEARSAL.md` §8). Без них деплой не готов.
  После них: перепрогон unit-тестов ворот, edited-copy сценария, CI E2E, полный gate на окончательном SHA; затем деплой по §3 именно этим SHA. Код ветки с тех пор ушёл дальше
  `ef607c0` (Dockerfile.web, deploy-файлы, тесты) — «gate прошёл на ef607c0» относится только к коду приложения до этих коммитов.
- **Версия Docker Compose на VPS — НЕИЗВЕСТНА.** «2.40.3» в labels контейнеров — версия, создавшая контейнеры, не доказательство текущей CLI. Скрипт пишет `docker compose version` в лог
  (фаза 0); поведение `run -T`, `up -d --no-build`, `config --images` на VPS не проверено.
- **Guarded entrypoint ни разу не запускался на VPS.** Проверен на настоящем Docker/Compose в песочнице и тестами потока управления (§3.7); не проверены: установка по §3.2,
  `flock`/`curl`/`sha256sum` на VPS, поведение sshd/`appleboy/ssh-action` при команде до 60 мин, серверная копия `post-deploy-cleanup.sh`, реальные данные.
- **Сборка при ≈ 704 МиБ available:** `COMPOSE_PARALLEL_LIMIT=1` и сборка app → web уменьшают пик, но он не измерен; при OOM скрипт останавливается в фазе 5 (БД не тронута, образы сохранены).
- **Воспроизводимость фронтенда:** исправлено (`b1d00f2`, `npm ci` по lock), проверено реальной сборкой образа Node (§3.6); версии зависимостей фиксирует lock.
- **Staging получает скачок на 67 коммитов и 7 миграций за один выкат**; реальные данные (10 МБ) не видела ни одна репетиция (числа в `docs/STAGING_RC_REHEARSAL.md` синтетические).
- **Неспаренные копии факультативов.** `converge-history` связывает копию с legacy-строкой по точному совпадению `(performed_at, блоки)`; отредактированная не спаривается; при хронологии
  «электив не старше плана» возможен дубль/воскрешение (`hold-check` в фазе 8 останавливает выкат до исправления).
- **Миграция `e3b9c5d7a2f1` неаддитивна** (UPDATE `progression_state`), уже в BASE; её `downgrade()` backfill не откатывает.
- **CI E2E красный** на `ef607c0` (2 из 2); причина не подтверждена — `docs/STAGING_RC_CI_E2E.md`.
