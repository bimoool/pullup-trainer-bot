#!/usr/bin/env bash
# STAGING-ONLY guarded deploy. Не трогает прод (`deploy.yml`, `deploy/deploy-run.sh`) и не заменяет `deploy-staging-run.sh`.
#
# Копия для ревью; на VPS ставится вручную владельцем как /home/deploy/deploy-staging-guarded-run.sh и вызывается ТОЛЬКО из
# deploy-staging-guarded-dispatch.sh (forced command отдельного SSH-ключа). Порядок установки — docs/STAGING_RC_RUNBOOK.md §3.2.
#
#   deploy-staging-guarded-run.sh <40-hex-sha> <preflight|dry-run|apply> <yes|no> [<users>]
#     sha       точный проверенный коммит (detached checkout, без `git pull` плавающей ветки)
#     converge  preflight: ТОЛЬКО ЧТЕНИЕ — фаза 0 и выход (не останавливает сервисы, не пишет в БД, не собирает, не мигрирует;
#                          единственная запись — `git fetch` в репозиторий staging и временный каталог /tmp/guarded-deploy.*);
#               dry-run:   НЕ read-only — останавливает app/web, пишет backup, переключает checkout, собирает образы и ВЫПОЛНЯЕТ МИГРАЦИЮ БД;
#                          convergence только проверяется (транзакции откатываются);
#               apply:     то же + применяет convergence ТОЛЬКО к пользователям из <users>
#     start     yes: запустить app/web после ВСЕХ успешных проверок; no: проверить всё и оставить app/web остановленными
#     users     `-` (по умолчанию) или список внутренних users.id через запятую, подтверждённый владельцем по выводу dry-run.
#               `-`: dry-run сводит/читает ВСЕХ пользователей (только чтение, показывает неразрешённые случаи); apply с `-` запрещён.
#               Список: dry-run и apply ограничены этими пользователями; остальные не меняются ни одним скриптом сведения.
#
# Сигналы: TERM/HUP/INT/PIPE (в т. ч. обрыв SSH и закрытый stdout) => ненулевой код и та же fail-safe очистка, что при ошибке:
# сначала останавливаются one-off контейнеры ЭТОГО запуска (метка guarded.run=<RUN_ID>) и app/web, потом пишется отчёт
# в файл, и только потом — вывод (ошибки вывода игнорируются). Исходная причина/код отказа сохраняются (первая побеждает).
# SIGKILL перехватить нельзя: при нём очистка не выполняется — следующий запуск увидит оставшиеся контейнеры с меткой
# guarded.run и откажется работать (preflight), app/web надо проверить вручную (runbook §3.5).
#
# Фазы (любая ошибка => app/web остаются ОСТАНОВЛЕННЫМИ; сохранённые образы и backup остаются; авто-отката нет):
#   0 preflight  1 сохранить текущие образы  2 остановить писателей  3 backup + проверка восстановления + снимок «до»
#   4 checkout SHA  5 сборка app, затем web (последовательно)  6 миграция  7 проверки данных  8 convergence  9 старт + healthcheck + проверка сборки
#
# Переиспользует: docker compose (тот же проект pullup-staging и порт 8002, что в deploy-staging-run.sh), scripts/repair_plan_convergence.py,
# scripts/backfill_multi_program.py --converge-history, deploy/post-deploy-cleanup.sh, docs/rehearsal/sql/gen_hash_queries.sql,
# deploy/staging_data_check.sh. Версия Docker Compose на VPS НЕ известна (2.40.3 в labels — версия создания контейнера) —
# скрипт её логирует и использует только `stop`, `build`, `run --rm -T`, `up -d --no-build`, `ps`, `config --images`.
set -euo pipefail

PROJECT="pullup-staging"
EXPECTED_FROM_REV="c3f7a9e2d5b1"          # ревизия staging, на которую рассчитан этот выкат (runbook §1.1)
EXPECTED_TO_REV="b5d8e1f3a6c9"            # единственный Alembic head кандидата (runbook §4); иной head — стоп

if [ "${GUARDED_TEST:-0}" = "1" ]; then   # переопределения — только для тестов с заглушками; на VPS игнорируются
  STAGING_DIR="${STAGING_DIR:?}"; BACKUP_DIR="${BACKUP_DIR:?}"; HEALTH_URL="${HEALTH_URL:?}"
  PROJECT="${PROJECT_OVERRIDE:-$PROJECT}"
  QUIESCE_SECONDS="${QUIESCE_SECONDS:-1}"; HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-20}"; MIN_DISK_MB="${MIN_DISK_MB:-1}"
  CLEANUP_BIN="${CLEANUP_BIN:-/nonexistent}"
else
  STAGING_DIR="/home/deploy/pullup-trainer-bot-staging"; BACKUP_DIR="/home/deploy/backups"
  HEALTH_URL="http://127.0.0.1:8002/health"
  QUIESCE_SECONDS=15; HEALTH_TIMEOUT=240; MIN_DISK_MB=2048
  CLEANUP_BIN="/usr/local/bin/post-deploy-cleanup.sh"
fi

if [[ $# -lt 3 || $# -gt 4 || ! "$1" =~ ^[0-9a-f]{40}$ || ! "$2" =~ ^(preflight|dry-run|apply)$ || ! "$3" =~ ^(yes|no)$ \
      || ! "${4:--}" =~ ^(-|[0-9]+(,[0-9]+){0,99})$ ]]; then
  echo "usage: $0 <40-hex-sha> <preflight|dry-run|apply> <yes|no> [<users.id,users.id,...>|-]   (got: $*)" >&2
  exit 2
fi
SHA="$1"; CONVERGE="$2"; START="$3"; USERS="${4:--}"
if [ "$CONVERGE" = "apply" ] && [ "$USERS" = "-" ]; then
  echo "refusing: converge=apply requires an explicit owner-confirmed users.id list (convergence is never applied to all users)" >&2
  exit 2
fi
if [ "$CONVERGE" = "preflight" ] && [ "$START" = "yes" ]; then
  echo "refusing: preflight never starts services (use start=no)" >&2
  exit 2
fi
SHA7="${SHA:0:7}"; TS="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d /tmp/guarded-deploy.XXXXXX)"
RUN_ID="$SHA7-$TS-$$"
exec 7>&2                                 # исходный stderr: отчёт об отказе идёт сюда, даже если сигнал пришёл внутри `cmd 2> file`                     # метка one-off контейнеров этого запуска (docker compose run --label guarded.run=…)
PHASE=0; PHASE_NAME="init"; WRITERS_STOPPED=0
PREV_SHA=""; PREV_REV=""; BACKUP_FILE=""; MANIFEST=""; SAVED_TAGS=(); DBC=""
BUILT_ID_app=""; BUILT_ID_web=""
FAIL_RC=""; FAIL_REASON=""; CHILD=""

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { FAIL_RC="${FAIL_RC:-$1}"; FAIL_REASON="${FAIL_REASON:-$2}"; }   # первая причина побеждает
die() { fail 1 "$*"; exit "$FAIL_RC"; }   # причина печатается очисткой (on_exit) — ПОСЛЕ остановки сервисов
phase() { PHASE="$1"; PHASE_NAME="$2"; log "== [$1/9] $2"; }
dc() { docker compose -p "$PROJECT" "$@"; }
dbq() { bash -c "$STAGING_PSQL" <<<"$1"; }
# Долгие команды — в фоне + wait: wait прерывается сигналом сразу (иначе bash ждёт конца команды), а PID известен очистке.
# stdin передаётся явно (<&0): фоновой команде без этого достался бы /dev/null.
bgwait() { local rc=0; "$@" <&0 & CHILD=$!; wait "$CHILD" || rc=$?; CHILD=""; return "$rc"; }
# One-off контейнеры compose run — с меткой этого запуска, чтобы очистка остановила именно их (а не чужие контейнеры).
dcrun() { bgwait docker compose -p "$PROJECT" run --rm -T --label "guarded.run=$RUN_ID" "$@"; }
our_oneoffs() { docker ps -aq --filter "label=guarded.run=$RUN_ID" 2>/dev/null || true; }

summary() {
  echo "---- state for rollback (docs/STAGING_RC_RUNBOOK.md §8) ----"
  echo "target sha      : $SHA   (converge=$CONVERGE start=$START users=$USERS)"
  echo "previous sha    : ${PREV_SHA:-unknown}   previous alembic: ${PREV_REV:-unknown}"
  echo "backup          : ${BACKUP_FILE:-not created yet}"
  echo "before-manifest : ${MANIFEST:-not created yet}   (rollback image IDs: §8.2)"
  echo "rollback images : ${SAVED_TAGS[*]:-none saved yet}"
  echo "work dir (logs) : $WORK"
}

on_signal() {   # <SIG> <номер>
  trap '' PIPE                             # дальнейшие записи в закрытый stdout не должны прерывать очистку
  fail $((128 + $2)) "signal SIG$1"
  exit "$FAIL_RC"
}
trap 'on_signal HUP 1' HUP
trap 'on_signal INT 2' INT
trap 'on_signal PIPE 13' PIPE
trap 'on_signal TERM 15' TERM

on_exit() {
  local rc=$? ids
  trap '' HUP INT PIPE TERM                # очистка не прерывается повторным сигналом
  rc="${FAIL_RC:-$rc}"
  [ "$rc" -ne 0 ] || exit 0
  [ -n "$FAIL_REASON" ] || FAIL_REASON="exit $rc"
  # 1) сначала действия — не зависят от stdout
  if [ -n "$CHILD" ]; then
    # клиент (docker compose run/build …) должен завершиться ДО поиска контейнеров: иначе он успевает создать one-off
    # контейнер уже после очистки (проверено на настоящем Docker: остался контейнер в состоянии created)
    kill -TERM "$CHILD" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 "$CHILD" 2>/dev/null || break; sleep 0.25; done
    kill -KILL "$CHILD" 2>/dev/null || true
    wait "$CHILD" 2>/dev/null || true
  fi
  ids="$(our_oneoffs)"
  if [ -n "$ids" ]; then
    # shellcheck disable=SC2086
    docker stop -t 10 $ids >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
  if [ "$WRITERS_STOPPED" = 1 ]; then
    dc stop app web >/dev/null 2>&1 || true
    STATE_MSG="app/web are STOPPED and stay stopped (stopped again if they had already been started); nothing was restored automatically."
  else
    STATE_MSG="failed before app/web were touched: nothing was changed."
  fi
  # 2) отчёт в файл (рядом с логами и, если уже есть, рядом с backup)
  {
    echo "ERROR: ${FAIL_REASON}"
    echo "!! GUARDED DEPLOY FAILED at phase ${PHASE} (${PHASE_NAME}), exit ${rc}"
    echo "!! one-off containers of this run stopped: ${ids:-none}"
    echo "!! $STATE_MSG"
    summary
  } > "$WORK/FAILED.txt" 2>/dev/null || true
  if [ -d "$BACKUP_DIR" ]; then cp "$WORK/FAILED.txt" "$BACKUP_DIR/guarded-$SHA7-$TS.FAILED.txt" 2>/dev/null || true; fi
  # 3) вывод последним; ошибки записи (обрыв SSH) игнорируются, код выхода — исходный
  cat "$WORK/FAILED.txt" >&7 2>/dev/null || true
  exit "$rc"
}
trap on_exit EXIT

# ------------------------------------------------------------------------------------------------ 0 preflight
phase 0 "preflight (staging only, exact SHA, free resources)"
cd "$STAGING_DIR"
[ -f docker-compose.yml ] && [ -f .env ] || die "docker-compose.yml/.env not found in $STAGING_DIR"
[ -z "$(git status --porcelain)" ] || die "staging checkout is not clean"
PREV_SHA="$(git rev-parse HEAD)"
git fetch --quiet origin
git cat-file -e "${SHA}^{commit}" 2>/dev/null || die "commit $SHA is not available after fetch"
mkdir -p "$WORK/tgt" "$WORK/data"
for f in deploy/staging_data_check.sh docs/rehearsal/sql/gen_hash_queries.sql deploy/staging-allowed-diff.txt; do
  git show "${SHA}:${f}" > "$WORK/tgt/$(basename "$f")" || die "$f is missing in $SHA (is this the guarded-deploy candidate?)"
done
chmod +x "$WORK/tgt/staging_data_check.sh"; bash -n "$WORK/tgt/staging_data_check.sh"
log "docker compose version: $(docker compose version 2>&1 | head -n1)  (VPS CLI version not verified before this run)"
avail="$(df -Pm "$STAGING_DIR" | awk 'NR==2{print $4}')"
[ "${avail:-0}" -ge "$MIN_DISK_MB" ] || die "free disk ${avail} MB < ${MIN_DISK_MB} MB"
log "free disk ${avail} MB; memory: $(free -m 2>/dev/null | awk 'NR==2{print "available "$7" MB"} NR==3{print ", swap used "$3" MB"}' | tr -d '\n')"
DBC="$(dc ps -q db | head -n1)"
[ -n "$DBC" ] || die "db container of project $PROJECT not found"
[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$DBC")" = "$PROJECT" ] || die "db container is not in project $PROJECT"
[ "$(docker inspect -f '{{.State.Running}}' "$DBC")" = "true" ] || die "db container is not running"
STAGING_PSQL="docker exec -i $DBC sh -c 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -v ON_ERROR_STOP=1'"
export STAGING_PSQL
PREV_REV="$(dbq "select version_num from alembic_version")"
log "staging: HEAD=$PREV_SHA alembic=$PREV_REV db-container=$DBC"
DB_NAME="$(docker exec "$DBC" sh -c 'echo "$POSTGRES_DB"')"
case "$DB_NAME" in *staging*) ;; *) die "database name '$DB_NAME' does not contain 'staging' — refusing to continue" ;; esac
# --- всё ниже проверяется ДО любой остановки/записи
case "$PREV_REV" in
  "$EXPECTED_FROM_REV"|"$EXPECTED_TO_REV") ;;
  *) die "unexpected alembic revision $PREV_REV (expected $EXPECTED_FROM_REV, or $EXPECTED_TO_REV after an earlier run)" ;;
esac
for svc in app web; do
  [ -n "$(dc ps -aq "$svc" | head -n1)" ] || die "no existing $svc container: cannot save its image for rollback"
done
docker compose run --help 2>/dev/null | grep -q -- '--label' \
  || die "this docker compose has no 'run --label': one-off containers could not be tracked and stopped on failure"
leftover="$(docker ps -aq --filter "label=guarded.run" 2>/dev/null || true)"
[ -z "$leftover" ] || die "one-off containers of an earlier guarded run still exist (killed run?): $(echo $leftover) — inspect and remove them first (runbook §3.5)"
command -v pgrep >/dev/null || die "pgrep is required (check that the old staging deploy is not running)"
if pgrep -f 'deploy-staging-run\.sh' >/dev/null 2>&1; then
  die "the old staging deploy (deploy-staging-run.sh) is running right now — refusing to run in parallel (runbook §3.8)"
fi
if [ "$USERS" != "-" ]; then
  known="$(dbq "select count(*) from users where id in ($USERS)")"
  [ "$known" = "$(printf '%s\n' "${USERS//,/ }" | tr ' ' '\n' | sort -u | grep -c .)" ] || die "some users.id in '$USERS' do not exist"
  PLAN_USERS="$(dbq "select coalesce(string_agg(user_id::text, ',' order by user_id), '') from training_plans where user_id in ($USERS)")"
  NOPLAN_USERS="$(dbq "select coalesce(string_agg(u.id::text, ',' order by u.id), '') from users u where u.id in ($USERS) and not exists (select 1 from training_plans p where p.user_id = u.id)")"
  log "scope: history convergence for users=$USERS; plan repair only for users with a plan=[${PLAN_USERS}]; without plan (history only, no plan is created)=[${NOPLAN_USERS}]"
fi

if [ "$CONVERGE" = "preflight" ]; then
  log "PREFLIGHT OK (read-only): sha=$SHA is available and ships the guarded files; staging HEAD=$PREV_SHA alembic=$PREV_REV; nothing was stopped, built, migrated or written"
  exit 0
fi

# ------------------------------------------------------------------------------------------------ 1 rollback images
phase 1 "save current app/web images under our own tags (rollback without Alembic)"
umask 077; mkdir -p "$BACKUP_DIR"
MANIFEST="$BACKUP_DIR/staging-pre-$SHA7-$TS.manifest"
{
  echo "# before-manifest of guarded run $RUN_ID (docs/STAGING_RC_RUNBOOK.md §8.2): rollback uses THESE image IDs"
  echo "previous_sha=$PREV_SHA"
  echo "previous_alembic=$PREV_REV"
} > "$MANIFEST"
for svc in app web; do
  cid="$(dc ps -aq "$svc" | head -n1)"
  img="$(docker inspect -f '{{.Image}}' "$cid")"
  ref="$(docker inspect -f '{{.Config.Image}}' "$cid")"
  tag="local/staging-$svc:pre-$SHA7-$TS"
  docker tag "$img" "$tag"
  SAVED_TAGS+=("$tag")
  printf '%s_image_id=%s\n%s_compose_image=%s\n%s_saved_tag=%s\n' "$svc" "$img" "$svc" "$ref" "$svc" "$tag" >> "$MANIFEST"
  log "saved $svc image ${img:0:19} ($ref) as $tag"
done

# ------------------------------------------------------------------------------------------------ 2 stop writers
phase 2 "stop writers (app = bot+workers, web = Mini App); db and redis stay up"
WRITERS_STOPPED=1
dc stop app web
conns="$(dbq "select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid()")"
[ "$conns" = "0" ] || die "$conns other connection(s) to the database remain after stopping app/web"
W1="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
bgwait sleep "$QUIESCE_SECONDS"
W2="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
[ "$W1" = "$W2" ] || die "database is still being written to ($W1 -> $W2)"
log "no writers: 0 foreign connections, write counter stable at $W2"

# ------------------------------------------------------------------------------------------------ 3 backup
phase 3 "backup + verified restore + data snapshot (before)"
BACKUP_FILE="$BACKUP_DIR/staging-pre-$SHA7-$TS.dump"
bgwait docker exec "$DBC" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$BACKUP_FILE"
[ -s "$BACKUP_FILE" ] || die "backup file is empty"
sha256sum "$BACKUP_FILE" > "$BACKUP_FILE.sha256"
printf 'backup=%s\nbackup_sha256=%s\n' "$BACKUP_FILE" "$(cut -d' ' -f1 "$BACKUP_FILE.sha256")" >> "$MANIFEST"
sha256sum -c --quiet "$BACKUP_FILE.sha256" || die "backup checksum does not verify"
toc="$(docker exec -i "$DBC" pg_restore -l < "$BACKUP_FILE" | wc -l)"
[ "$toc" -gt 10 ] || die "backup table of contents too short ($toc lines)"
docker exec "$DBC" sh -c 'dropdb -U "$POSTGRES_USER" --if-exists restore_check && createdb -U "$POSTGRES_USER" restore_check'
bgwait docker exec -i "$DBC" sh -c 'pg_restore -U "$POSTGRES_USER" -d restore_check --no-owner' < "$BACKUP_FILE"
rq() { docker exec "$DBC" sh -c "psql -U \"\$POSTGRES_USER\" -d restore_check -At -c \"$1\""; }
[ "$(rq "select version_num from alembic_version")" = "$PREV_REV" ] || die "restored alembic_version differs from live"
COUNTS_SQL="select (select count(*) from users)||'/'||(select count(*) from subscriptions)||'/'||(select count(*) from program_inclusions)||'/'||(select count(*) from training_sessions)||'/'||(select count(*) from plan_items)"
[ "$(rq "$COUNTS_SQL")" = "$(dbq "$COUNTS_SQL")" ] || die "restored table counts differ from live"
docker exec "$DBC" sh -c 'dropdb -U "$POSTGRES_USER" restore_check'
W3="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
[ "$W3" = "$W2" ] || die "database was written to during the backup ($W2 -> $W3)"
log "backup OK: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1), $toc TOC entries, sha256 in $BACKUP_FILE.sha256); restore check passed"
"$WORK/tgt/staging_data_check.sh" before "$WORK/data" "$WORK/tgt/gen_hash_queries.sql"

# ------------------------------------------------------------------------------------------------ 4 checkout
phase 4 "checkout the exact SHA (detached)"
git checkout --quiet --detach "$SHA"
[ "$(git rev-parse HEAD)" = "$SHA" ] || die "HEAD != $SHA after checkout"
[ -z "$(git status --porcelain)" ] || die "working tree is not clean after checkout"
log "HEAD=$SHA"

# ------------------------------------------------------------------------------------------------ 5 build
phase 5 "build app, then web — sequentially (limited memory)"
export COMPOSE_PARALLEL_LIMIT=1
for svc in app web; do
  log "memory before build $svc: $(free -m 2>/dev/null | awk 'NR==2{print "available "$7" MB"}')"
  bgwait docker compose -p "$PROJECT" build "$svc"
done
imgname() { dc config --images 2>/dev/null | grep -E "[-_]$1\$" | head -n1; }
for svc in app web; do
  name="$(imgname "$svc")"; [ -n "$name" ] || die "cannot resolve image name of $svc"
  id="$(docker image inspect -f '{{.Id}}' "$name")"; [ -n "$id" ] || die "built image $name not found"
  eval "BUILT_ID_$svc=\$id"
  log "built $svc: $name ${id:0:19}"
done

# ------------------------------------------------------------------------------------------------ 6 migration
phase 6 "migration (single transaction)"
dcrun app alembic heads > "$WORK/heads.txt"
HEADS="$(grep -E '\(head\)' "$WORK/heads.txt" | awk '{print $1}')"
[ -n "$HEADS" ] && [ "$(printf '%s\n' "$HEADS" | wc -l)" -eq 1 ] || die "expected exactly one Alembic head, got: $HEADS"
[ "$HEADS" = "$EXPECTED_TO_REV" ] || die "Alembic head of $SHA is $HEADS, this guarded run is written for $EXPECTED_TO_REV"
CUR="$(dbq "select version_num from alembic_version")"
if [ "$CUR" = "$HEADS" ]; then
  log "WARNING: database already at head $HEADS (a previous run migrated it); the pre-migration backup is the one from that earlier run"
elif [ "$CUR" = "$EXPECTED_FROM_REV" ]; then
  dcrun app alembic upgrade head
  [ "$(dbq "select version_num from alembic_version")" = "$HEADS" ] || die "alembic_version != head after upgrade"
else
  die "unexpected alembic revision $CUR (expected $EXPECTED_FROM_REV or head $HEADS)"
fi
log "alembic_version = $HEADS"

# ------------------------------------------------------------------------------------------------ 7 data checks
phase 7 "data checks after migration (expected transformations only)"
"$WORK/tgt/staging_data_check.sh" after-migration "$WORK/data" "$WORK/tgt/staging-allowed-diff.txt"

# ------------------------------------------------------------------------------------------------ 8 convergence
phase 8 "convergence ($CONVERGE, users=$USERS)"
conv_json_check() { # <file> <expect_zero_mutations 0|1>
  dcrun app python -c '
import json, sys
d = json.load(sys.stdin)
if d.get("error"):
    print("error: %s" % d["error"]); sys.exit(1)
bad = [u for u in d["users_detail"] if u.get("guard_violations")]
print("mode=%s users=%s total_mutations=%s guard_violations=%d" % (d["mode"], d["users"], d["total_mutations"], len(bad)))
sys.exit(1 if bad or (sys.argv[1] == "1" and d["total_mutations"] != 0) else 0)
' "$2" < "$1"
}
# сведение истории: машинный результат — последняя строка `RESULT-JSON {...}` (mutations = все изменяющие счётчики,
# в т. ч. classified «origin проставлен…»); текстовый блок «Не разрешено» сохраняется для людей
hist_json_check() { # <file> <expect_zero_mutations 0|1>
  { grep '^RESULT-JSON ' "$1" || true; } | tail -n1 | sed 's/^RESULT-JSON //' > "$1.json"
  [ -s "$1.json" ] || die "history convergence printed no RESULT-JSON line ($1)"
  dcrun app python -c '
import json, sys
d = json.load(sys.stdin)
print("history mode=%s users=%s mutations=%s counts=%s unresolved=%d" % (d["mode"], d["users"], d["mutations"], json.dumps(d["counts"], sort_keys=True), len(d["unresolved"])))
sys.exit(1 if sys.argv[1] == "1" and d["mutations"] != 0 else 0)
' "$2" < "$1.json"
}
hist_unresolved() { sed -n '/^Не разрешено/,/^RESULT-JSON /p' "$1" | grep -v '^RESULT-JSON '; }
SCOPE_REPAIR=(--all); SCOPE_HISTORY=(); RUN_REPAIR=1
if [ "$USERS" != "-" ]; then
  SCOPE_HISTORY=(--user-ids "$USERS")
  # план чинится только тем, у кого он есть; пользователь без плана получает только сведение истории (план не создаётся)
  if [ -n "$PLAN_USERS" ]; then SCOPE_REPAIR=(--user-ids "$PLAN_USERS"); else RUN_REPAIR=0; fi
fi
repair()  { dcrun app python scripts/repair_plan_convergence.py "${SCOPE_REPAIR[@]}" "$@"; }
history() { dcrun app python scripts/backfill_multi_program.py --converge-history "${SCOPE_HISTORY[@]}" "$@"; }
REPORT_DIR="$BACKUP_DIR/convergence-${SHA7}-${TS}"
mkdir -p "$REPORT_DIR"
if [ "$RUN_REPAIR" = 1 ]; then
  repair > "$WORK/conv_dry.json" 2> "$WORK/conv_dry.err"; conv_json_check "$WORK/conv_dry.json" 0
else
  log "plan repair skipped: none of users=$USERS has a training plan (history only)"; echo '{}' > "$WORK/conv_dry.json"
fi
history > "$WORK/hist_dry.txt" 2> "$WORK/hist_dry.err"; hist_json_check "$WORK/hist_dry.txt" 0
"$WORK/tgt/staging_data_check.sh" same-as-migration "$WORK/data"
# неразрешённые факультативы (копия НЕ создана, ничего не привязано) — с user_id и причиной; сохраняются и показываются всегда
hist_unresolved "$WORK/hist_dry.txt" > "$REPORT_DIR/unresolved-dry-run.txt" || true
cp "$WORK/conv_dry.json" "$WORK/hist_dry.txt" "$REPORT_DIR/"
if [ -s "$REPORT_DIR/unresolved-dry-run.txt" ]; then
  log "UNRESOLVED electives (dry-run, scope users=$USERS) — saved to $REPORT_DIR/unresolved-dry-run.txt:"; cat "$REPORT_DIR/unresolved-dry-run.txt"
else
  log "unresolved electives (dry-run, scope users=$USERS): none"
fi
if [ "$CONVERGE" = "apply" ]; then
  if [ "$RUN_REPAIR" = 1 ]; then
    repair --apply > "$WORK/conv_a1.json" 2> "$WORK/conv_a1.err"; conv_json_check "$WORK/conv_a1.json" 0
    repair --apply > "$WORK/conv_a2.json" 2> "$WORK/conv_a2.err"; conv_json_check "$WORK/conv_a2.json" 1
  else
    echo '{}' > "$WORK/conv_a1.json"; echo '{}' > "$WORK/conv_a2.json"
  fi
  history --apply > "$WORK/hist_a1.txt" 2> "$WORK/hist_a1.err"; hist_json_check "$WORK/hist_a1.txt" 0
  history --apply > "$WORK/hist_a2.txt" 2> "$WORK/hist_a2.err"
  hist_json_check "$WORK/hist_a2.txt" 1 || die "history convergence is not idempotent (second --apply changed something, see RESULT-JSON mutations/counts)"
  hist_unresolved "$WORK/hist_a1.txt" > "$REPORT_DIR/unresolved-apply.txt" || true
  hist_unresolved "$WORK/hist_a2.txt" > "$WORK/unresolved_a2.txt" || true
  cmp -s "$REPORT_DIR/unresolved-apply.txt" "$WORK/unresolved_a2.txt" || die "unresolved electives changed between the first and second --apply (not stable)"
  cp "$WORK/conv_a1.json" "$WORK/conv_a2.json" "$WORK/hist_a1.txt" "$WORK/hist_a2.txt" "$WORK"/hist_*.txt.json "$REPORT_DIR/"
  "$WORK/tgt/staging_data_check.sh" after-convergence "$WORK/data"
  log "convergence applied ONLY to users=$USERS; unresolved after apply: $(grep -c 'user_id=' "$REPORT_DIR/unresolved-apply.txt" || true) (kept as is, see $REPORT_DIR/unresolved-apply.txt)"
else
  log "convergence NOT applied (mode $CONVERGE): runtime plan convergence will run per user on the first GET /plan of the new build; history convergence has no runtime path"
fi

# ------------------------------------------------------------------------------------------------ 9 start
if [ "$START" = "no" ]; then
  log "start=no: all checks passed; app/web remain STOPPED by request"
  summary
  log "GUARDED DEPLOY VERIFIED (services NOT started) sha=$SHA"
  exit 0
fi
phase 9 "start app/web, healthcheck, verify the running build"
dc up -d --no-build app web
deadline=$((SECONDS + HEALTH_TIMEOUT))
until bgwait curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; do
  [ "$SECONDS" -lt "$deadline" ] || die "healthcheck $HEALTH_URL did not pass within ${HEALTH_TIMEOUT}s"
  bgwait sleep 3
done
log "healthcheck OK: $HEALTH_URL"
for svc in app web; do
  cid="$(dc ps -q "$svc" | head -n1)"; [ -n "$cid" ] || die "$svc container missing after up"
  [ "$(docker inspect -f '{{.State.Running}}' "$cid")" = "true" ] || die "$svc is not running"
  [ "$(docker inspect -f '{{.State.Restarting}}' "$cid")" = "false" ] || die "$svc is restarting"
  want="BUILT_ID_$svc"; got="$(docker inspect -f '{{.Image}}' "$cid")"
  [ "$got" = "${!want}" ] || die "$svc runs image ${got:0:19}, not the one built by this run (${!want:0:19})"
  until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")" != "starting" ]; do
    [ "$SECONDS" -lt "$deadline" ] || die "$svc healthcheck still 'starting' after ${HEALTH_TIMEOUT}s"; bgwait sleep 3
  done
  st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  [ "$st" = "healthy" ] || [ "$st" = "none" ] || die "$svc health status is '$st'"
  log "running $svc: image ${got:0:19} == built by this run; health=$st"
done
[ "$(git rev-parse HEAD)" = "$SHA" ] || die "HEAD != $SHA after start"
[ "$(dbq "select version_num from alembic_version")" = "$HEADS" ] || die "alembic_version != head after start"

if [ -x "$CLEANUP_BIN" ]; then "$CLEANUP_BIN" || true; fi   # как в deploy-run.sh: только после полного успеха, ошибки очистки не валят выкат
summary
log "GUARDED DEPLOY OK sha=$SHA alembic=$HEADS converge=$CONVERGE users=$USERS services=started"
