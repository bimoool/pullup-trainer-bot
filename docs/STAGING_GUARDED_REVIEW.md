# Короткое независимое ревью: guarded staging deploy и SSH-dispatch (до установки на VPS)

Что ревьюится: **только то, что владелец поставит на сервер** — `deploy/deploy-staging-guarded-run.sh`, `deploy/deploy-staging-guarded-dispatch.sh`, `deploy/staging_data_check.sh`,
`deploy/staging-allowed-diff.txt`, `Dockerfile.web` (и `.github/workflows/deploy-staging-guarded.yml` — **не путь выката**, заготовка, §3.3 runbook). Ничего не установлено и не запущено на VPS; продовый деплой и существующие staging-файлы не изменены.

## Diff

```bash
git diff 4298f8b9727f91d4a150431fd0d9e06131944d27 <CANDIDATE_SHA> -- deploy .github/workflows/deploy-staging-guarded.yml Dockerfile.web
```
`4298f8b…` — код, который сейчас на staging, поэтому diff = ровно то, что появится на сервере (6 файлов: все новые, кроме `Dockerfile.web`).
Готовые файлы на кодовом коммите `5afd57e`: полный diff — `docs/rehearsal/review/guarded-deploy-vs-staging-4298f8b.patch`; только правки после первого ревью (от `3f10ecf`) —
`docs/rehearsal/review/guarded-deploy-review-fixes-since-3f10ecf.patch`. Хэши установочных файлов на `5afd57e` (сверять с `git show <SHA>:<file> | sha256sum` перед `install`, runbook §3.2):

```
5f08f3620b4cd5105bd731ec45dd422e10a30349aa10c124517b511e058ea8b0  deploy/deploy-staging-guarded-run.sh
e9db113af2dfde95c353bdd8d6babfa5f5c097c6debc6d91d21cba604dcd30c1  deploy/deploy-staging-guarded-dispatch.sh
430025698a69010cd649987ba2de36fbc5542a1a23afa4b52f70485178186e9c  deploy/staging_data_check.sh        # читается скриптом через `git show <SHA>:…`, на VPS отдельно не ставится
```
Если после ревью код этих файлов изменился, хэши и SHA в runbook обновляются в том же коммите.

## Findings первого независимого ревью — что сделано

| Finding | Исправление | Доказательство |
|---|---|---|
| Сигналы TERM/HUP/INT/PIPE: не было ненулевого выхода и fail-safe; вывод мог идти в закрытый stdout до очистки | `trap` на четыре сигнала → код 128+N, та же очистка, что при ошибке; порядок: kill one-off этого запуска → дождаться и завершить группу процессов команды → снова kill/rm всего с меткой запуска → `stop app web` → отчёт в файл → вывод в исходный stderr (fd 7); первая причина/код сохраняются; повторные сигналы во время очистки игнорируются | стаб-тесты: сигнал во время миграции, сведения, после `up` во время healthcheck, после healthcheck до проверки образов × TERM/HUP/INT; SIGPIPE (закрытый stdout); сигнал во время очистки не меняет причину |
| Долгая команда откладывала обработку сигнала | долгие команды через `bgwait` (фон + `wait`, своя группа процессов `setsid`) | тест «обработан < 10 с»; мутация «на переднем плане» ловится |
| One-off контейнер `compose run` мог писать после снятия `flock` | метка `guarded.run=<sha7>-<UTC>-<pid>` на каждом `compose run`; очистка останавливает **только** контейнеры этой метки (по ID; без глобального pkill/stop); `SIGKILL` (не `stop`: PID 1 игнорирует TERM, миграция успевала закоммититься); ожидание всей группы процессов команды (иначе переживший `docker` плагин compose создавал контейнер после очистки); preflight отказывает при оставшихся контейнерах прежнего запуска | настоящий Docker (песочница): TERM в момент `alembic upgrade` → БД осталась `c3f7a9e2d5b1` (откат транзакции), контейнеров с меткой 0; TERM ровно в момент `created` контейнера сведения → 0 контейнеров; стаб-тесты «клиент создаёт контейнер при выходе», «плагин переживает docker» |
| Сигнал, игнорируемый при запуске (`nohup` → HUP) | bash не может его перехватить — скрипт пишет `WARNING: SIGHUP was ignored…`; обрыв SSH всё равно завершает выкат через SIGPIPE | найдено при прогоне тестов под `nohup`; тест + мутация |
| SIGKILL | неперехватываем — задокументировано; следующий запуск отказывается в preflight, ручная процедура — runbook §3.5 | тест «оставшиеся контейнеры блокируют следующий запуск» |
| Entry point | ручной SSH-вызов guarded dispatcher; Actions-вариант недоступен до регистрации (в `main` не переносится) | runbook §3.3 |
| Идемпотентность history учитывала не все изменения (не было `classified`) | машинный результат `RESULT-JSON` (`mutations` = все `MUTATING_KEYS` сервиса, в т. ч. `classified`); нет строки — стоп | тест «classified=1 на повторе — стоп», «нет RESULT-JSON — стоп»; DB-тест на реальном выводе скрипта |
| Preflight поздно | ревизия Alembic, наличие `app`/`web`, существование `users.id`, `run --label`, старый деплой не идёт, `setsid`/`pgrep` — **до** остановки | тест «неизвестная ревизия — ничего не остановлено» |
| Переопределения тестового режима в боевом вызове | диспетчер: `env -u GUARDED_TEST -u PROJECT_OVERRIDE -u STAGING_DIR …` | тест диспетчера с подменённым путём run-скрипта |
| `sha256sum -c` до restore | в скрипте перед пробным восстановлением и в runbook §8.3 перед `dropdb` | тест «контрольная сумма не сходится — стоп до restore» |
| Rollback по «самому раннему тегу» | before-manifest с ID образов, именами compose, SHA, ревизией, путём и sha256 дампа; runbook §8 берёт ID из утверждённого manifest | тест manifest |
| Область plan/history | план чинится только пользователям с планом; история — всем подтверждённым; план не создаётся | стаб-тесты; настоящий Docker: users 3,5,12 → plan repair `[3]`, history 3 пользователя, `training_plans` у 5 и 12 не появились |
| Старый staging-workflow параллельно | общий lock-файл `/home/deploy/.deploy-staging.lock`; preflight отказывает при работающем `deploy-staging-run.sh`; готовая правка forced command старого ключа (`flock -n …`) и отключение workflow на окно | runbook §3.8 |

Mutation proof (каждая мутация валит свой тест): нет trap TERM; команда на переднем плане вместо `bgwait`; нет очистки one-off; повторный history без проверки; диспетчер без `env -u`;
нет preflight-проверки ревизии; план для всего списка; нет trap PIPE; нет `sha256sum -c`; нет ожидания умирающего клиента; ожидание только `docker` без группы процессов; нет предупреждения об игнорируемом при запуске сигнале.

## Чек-лист ревью (≈ 15 минут)

1. **Dispatch (`deploy-staging-guarded-dispatch.sh`).** Один литеральный regex `^\./deploy-staging-guarded\.sh <40-hex> (preflight|dry-run|apply) (yes|no)( (-|ids))?$`; всё иное — `rejected command`, exit 1;
   `flock -n` на общем `/home/deploy/.deploy-staging.lock`; затем `exec env -u …` run-скрипта с аргументами **только из `BASH_REMATCH`** (не из сырой строки). Никакого `eval`/`bash -c`/подстановок. Отдельный ключ, `no-pty,no-port-forwarding…` в `authorized_keys`;
   существующие ключи и `deploy-staging-dispatch.sh` не затронуты.
2. **Область записи.** Единственные пути, пишущие БД: фаза 6 (`alembic upgrade head`), фаза 8 `--apply` (только при `apply` и **непустом списке** `users.id`; `apply` с `-` отказывается до любых действий), `restore_check` (временная БД, удаляется).
   `preflight` выходит после фазы 0 (только `git fetch` и `/tmp/guarded-deploy.*`).
3. **Защита staging от prod.** Проект `pullup-staging` зашит константой; db-контейнер обязан нести label проекта и имя БД с `staging`; переопределения (`STAGING_DIR`, `BACKUP_DIR`, …) работают **только** при `GUARDED_TEST=1`
   и на VPS игнорируются (проверить, что `GUARDED_TEST` не выставляется ни в workflow, ни в dispatch).
4. **Порядок и остановка.** `trap on_exit` + trap TERM/HUP/INT/PIPE: при любой ошибке или сигнале — kill one-off этого запуска, затем `dc stop app web`, отчёт, вывод; `up -d` встречается один раз, после всех проверок данных (фаза 9). Нет `|| true` на проверках (`|| true` только у чтения отчётов, остановки в trap и cleanup после успеха).
5. **Миграция только с известной ревизии** (`c3f7a9e2d5b1`), иначе стоп; «уже head» — предупреждение (после предыдущего dry-run).
6. **Backup.** `pg_dump -Fc` → `/home/deploy/backups`, `pg_restore -l`, пробное восстановление с той же `alembic_version`/счётчиками, затем `DROP`. Скрипт **ничего не удаляет** из `backups/` и не откатывает сам.
7. **Данные.** `staging_data_check.sh` не пишет в БД; хэши только ДО-колонок; допустимое изменение — `program_inclusions` (+ предикат `work_sets`); после сведения — 6 таблиц, у append-only таблиц старые строки не меняются.
8. **Сведение.** `--all` только dry-run; `--user-ids` обязателен для записи (и в скриптах: `--all --apply` и `--converge-history --apply` без списка отклоняются; `converge_history_all(apply=True)` без списка бросает `ValueError`); неразрешённые факультативы печатаются и сохраняются, их список после 1-го и 2-го `--apply` обязан совпасть.
9. **Workflow (не путь выката).** `workflow_dispatch`; входы валидируются regex до SSH; секрет `VPS_STAGING_GUARDED_SSH_KEY` отдельный; `permissions: contents: read`; `concurrency` без отмены; `converge=apply` без `users` отклоняется; `preflight`+`start=yes` отклоняется.
10. **`Dockerfile.web`.** Копируется `package-lock.json`, `npm ci` (проверено реальным `docker build`).

## Что ревью не покрывает (проверить после установки первым `preflight`)

Версия Docker Compose на VPS (**неизвестна**; `2.40.3` в labels — версия создания контейнеров), наличие `flock`/`curl`/`awk`/`sha256sum`, права пользователя `deploy` на `docker`, поведение sshd и `appleboy/ssh-action` при команде до 60 минут,
серверный `post-deploy-cleanup.sh`, пик памяти сборки при ≈ 704 МиБ, реальные данные staging.

Режимы и что они меняют — `docs/STAGING_RC_RUNBOOK.md` §3.1a. Доказательства — `docs/STAGING_RC_REHEARSAL.md` §12.
