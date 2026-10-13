# Короткое независимое ревью: guarded staging deploy и SSH-dispatch (до установки на VPS)

Что ревьюится: **только то, что владелец поставит на сервер** — `deploy/deploy-staging-guarded-run.sh`, `deploy/deploy-staging-guarded-dispatch.sh`, `deploy/staging_data_check.sh`,
`deploy/staging-allowed-diff.txt`, `.github/workflows/deploy-staging-guarded.yml`, `Dockerfile.web`. Ничего не установлено и не запущено на VPS; продовый деплой и существующие staging-файлы не изменены.

## Diff

```bash
git diff 4298f8b9727f91d4a150431fd0d9e06131944d27 <CANDIDATE_SHA> -- deploy .github/workflows/deploy-staging-guarded.yml Dockerfile.web
```
`4298f8b…` — код, который сейчас на staging, поэтому diff = ровно то, что появится на сервере/в CI (506 строк, 6 файлов: все новые, кроме `Dockerfile.web`).
Готовый файл на кодовом коммите `3f10ecf`: `docs/rehearsal/review/guarded-deploy-vs-staging-4298f8b.patch`. Хэши установочных файлов на `3f10ecf`
(сверять с `git show <SHA>:<file> | sha256sum` перед `install`, runbook §3.2):

```
a9a98722e50605ae81a0e5bf17d77bf430ef37c0ce15bfc162c78bc825f3e34e  deploy/deploy-staging-guarded-run.sh
c138736f9d4595ff0af1d709ab958b2bc348f828141cd7f0645f5b1430563271  deploy/deploy-staging-guarded-dispatch.sh
430025698a69010cd649987ba2de36fbc5542a1a23afa4b52f70485178186e9c  deploy/staging_data_check.sh        # читается скриптом через `git show <SHA>:…`, на VPS отдельно не ставится
```
Если после ревью код этих файлов изменился, хэши и SHA в runbook обновляются в том же коммите.

## Чек-лист ревью (≈ 15 минут)

1. **Dispatch (`deploy-staging-guarded-dispatch.sh`, 21 строка).** Один литеральный regex `^\./deploy-staging-guarded\.sh <40-hex> (preflight|dry-run|apply) (yes|no)( (-|ids))?$`; всё иное — `rejected command`, exit 1;
   `flock -n`; затем `exec` run-скрипта с аргументами **только из `BASH_REMATCH`** (не из сырой строки). Никакого `eval`/`bash -c`/подстановок. Отдельный ключ, `no-pty,no-port-forwarding…` в `authorized_keys`;
   существующие ключи и `deploy-staging-dispatch.sh` не затронуты.
2. **Область записи.** Единственные пути, пишущие БД: фаза 6 (`alembic upgrade head`), фаза 8 `--apply` (только при `apply` и **непустом списке** `users.id`; `apply` с `-` отказывается до любых действий), `restore_check` (временная БД, удаляется).
   `preflight` выходит после фазы 0 (только `git fetch` и `/tmp/guarded-deploy.*`).
3. **Защита staging от prod.** Проект `pullup-staging` зашит константой; db-контейнер обязан нести label проекта и имя БД с `staging`; переопределения (`STAGING_DIR`, `BACKUP_DIR`, …) работают **только** при `GUARDED_TEST=1`
   и на VPS игнорируются (проверить, что `GUARDED_TEST` не выставляется ни в workflow, ни в dispatch).
4. **Порядок и остановка.** `trap on_exit`: при любой ошибке после остановки писателей — `dc stop app web`; `up -d` встречается один раз, после всех проверок данных (фаза 9). Нет `|| true` на проверках (`|| true` только у чтения отчётов, остановки в trap и cleanup после успеха).
5. **Миграция только с известной ревизии** (`c3f7a9e2d5b1`), иначе стоп; «уже head» — предупреждение (после предыдущего dry-run).
6. **Backup.** `pg_dump -Fc` → `/home/deploy/backups`, `pg_restore -l`, пробное восстановление с той же `alembic_version`/счётчиками, затем `DROP`. Скрипт **ничего не удаляет** из `backups/` и не откатывает сам.
7. **Данные.** `staging_data_check.sh` не пишет в БД; хэши только ДО-колонок; допустимое изменение — `program_inclusions` (+ предикат `work_sets`); после сведения — 6 таблиц, у append-only таблиц старые строки не меняются.
8. **Сведение.** `--all` только dry-run; `--user-ids` обязателен для записи (и в скриптах: `--all --apply` и `--converge-history --apply` без списка отклоняются; `converge_history_all(apply=True)` без списка бросает `ValueError`); неразрешённые факультативы печатаются и сохраняются, их список после 1-го и 2-го `--apply` обязан совпасть.
9. **Workflow.** `workflow_dispatch`; входы валидируются regex до SSH; секрет `VPS_STAGING_GUARDED_SSH_KEY` отдельный; `permissions: contents: read`; `concurrency` без отмены; `converge=apply` без `users` отклоняется; `preflight`+`start=yes` отклоняется.
10. **`Dockerfile.web`.** Копируется `package-lock.json`, `npm ci` (проверено реальным `docker build`).

## Что ревью не покрывает (проверить после установки первым `preflight`)

Версия Docker Compose на VPS (**неизвестна**; `2.40.3` в labels — версия создания контейнеров), наличие `flock`/`curl`/`awk`/`sha256sum`, права пользователя `deploy` на `docker`, поведение sshd и `appleboy/ssh-action` при команде до 60 минут,
серверный `post-deploy-cleanup.sh`, пик памяти сборки при ≈ 704 МиБ, реальные данные staging.

Режимы и что они меняют — `docs/STAGING_RC_RUNBOOK.md` §3.1a. Доказательства — `docs/STAGING_RC_REHEARSAL.md` §12.
