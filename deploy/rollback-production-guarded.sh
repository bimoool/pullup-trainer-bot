#!/usr/bin/env bash
# Откат PRODUCTION guarded-выката (docs/PRODUCTION_RUNBOOK.md §7). Пара к deploy-production-guarded-run.sh, ставится рядом
# с ним ВНЕ репозитория (/root/bin/). Все факты (каталог, compose-проект, имя БД, образы, дамп) берутся из manifest того
# выката, который откатывается, — ничего не угадывается; несовпадение с живым окружением — отказ.
#
#   rollback-production-guarded.sh R1|R3 <manifest> check
#   rollback-production-guarded.sh R1|R3 <manifest> apply ROLLBACK-<R1|R3>-<run_id из manifest>
#
#   check  ТОЛЬКО ЧТЕНИЕ: проверяет manifest, образы, дамп (sha256, оглавление), текущее состояние и печатает, что будет
#          сделано и какие данные будут потеряны. Ничего не останавливает и не пишет.
#   R1     прежние образы, БД НЕ меняется. Допустим, только если alembic_version == previous_alembic manifest и backfill
#          не начинался (маркера backfill_started_at нет). Иначе — отказ (нужен R3).
#   R3     восстановление дампа ДО выката: app/web остановить -> дамп восстановить в НОВУЮ БД <db>_rb_<ts> и проверить
#          (alembic, счётчики legacy-таблиц = manifest) -> атомарно (одна транзакция) переименовать текущую БД в
#          <db>_failed_<ts> (НЕ удаляется: из неё можно вручную достать данные окна) и восстановленную — в <db> ->
#          прежние образы -> старт -> healthcheck. Теряется всё, что записано после backup_at manifest.
# Любая ошибка => app/web ОСТАНОВЛЕНЫ, печатается состояние. Повторный запуск безопасен (на каждом шаге проверка).
#
# Параметры (окружение): PROD_HEALTH_TIMEOUT=240, PROD_MIN_DISK_MB=1024 (сверх 3 x размер дампа).
# shellcheck disable=SC2016  # $POSTGRES_* намеренно раскрываются внутри контейнера db (sh -c '...'), не здесь
set -euo pipefail

usage() {
  echo "usage: $0 R1|R3 <manifest> check" >&2
  echo "       $0 R1|R3 <manifest> apply ROLLBACK-<R1|R3>-<run_id from the manifest>   (got: $*)" >&2
}
if [[ $# -lt 3 || $# -gt 4 || ! "$1" =~ ^R[13]$ || ! "$3" =~ ^(check|apply)$ || ! "$2" =~ ^/[A-Za-z0-9._/-]+\.manifest$ ]]; then
  usage "$@"; exit 2
fi
KIND="$1"; MANIFEST="$2"; MODE="$3"; TOKEN="${4:-}"
if [ "$MODE" = "check" ] && [ -n "$TOKEN" ]; then echo "refusing: a confirmation token is accepted only with apply" >&2; exit 2; fi
[ -f "$MANIFEST" ] || { echo "refusing: manifest $MANIFEST not found" >&2; exit 2; }
HEALTH_TIMEOUT="${PROD_HEALTH_TIMEOUT:-240}"; MIN_DISK_MB="${PROD_MIN_DISK_MB:-1024}"
[[ "$HEALTH_TIMEOUT" =~ ^[0-9]{1,6}$ && "$MIN_DISK_MB" =~ ^[0-9]{1,7}$ ]] || { echo "refusing: PROD_HEALTH_TIMEOUT/PROD_MIN_DISK_MB must be integers" >&2; exit 2; }

m() { sed -n "s/^$1=//p" "$MANIFEST" | tail -n1; }   # последнее значение ключа
need() { local v; v="$(m "$1")"; [[ -n "$v" && "$v" =~ $2 ]] || { echo "refusing: manifest key $1 is missing or malformed ('$v')" >&2; exit 2; }; printf '%s' "$v"; }
RUN_ID="$(need run_id '^prod-[0-9a-f]{7}-[0-9TZ]+-[0-9]+$')"
if [ "$MODE" = "apply" ] && [ "$TOKEN" != "ROLLBACK-$KIND-$RUN_ID" ]; then
  echo "refusing: apply requires the exact confirmation token ROLLBACK-$KIND-<run_id from the manifest> as the 4th argument" >&2; exit 2
fi
PREV_SHA="$(need previous_sha '^[0-9a-f]{40}$')"
PREV_REV="$(need previous_alembic '^[0-9a-f]{12}$')"
PROJECT="$(need project '^[a-z0-9][a-z0-9_-]*$')"
PROD_DIR="$(need dir '^/[A-Za-z0-9._/-]+$')"
COMPOSE_FILES="$(need compose_files '^/[A-Za-z0-9._/,-]+$')"
DB_NAME="$(need db_name '^[a-z_][a-z0-9_]*$')"
HEALTH_URL="$(need health_url '^http://(127\.0\.0\.1|localhost):[0-9]{2,5}/health$')"
for svc in app web; do
  need "${svc}_image_id" '^sha256:[0-9a-z-]+$' >/dev/null
  need "${svc}_compose_image" '^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?$' >/dev/null
done
APP_ID="$(m app_image_id)"; WEB_ID="$(m web_image_id)"; APP_REF="$(m app_compose_image)"; WEB_REF="$(m web_compose_image)"
if [ "$KIND" = "R3" ]; then
  BACKUP="$(need backup '^/[A-Za-z0-9._/-]+\.dump$')"
  BACKUP_SHA="$(need backup_sha256 '^[0-9a-f]{64}$')"
  BACKUP_AT="$(need backup_at '^[0-9T:Z-]+$')"
  LEGACY_COUNTS="$(need legacy_counts '^[0-9]+(/[0-9]+){3}$')"
fi

TS="$(date -u +%Y%m%d%H%M%S)"
exec 7>&2
PHASE="init"; WRITERS_STOPPED=0; SWAPPED=0; DBC=""; FAIL_RC=""; FAIL_REASON=""; CHILD=""
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { FAIL_RC="${FAIL_RC:-$1}"; FAIL_REASON="${FAIL_REASON:-$2}"; }
die() { fail 1 "$*"; exit "$FAIL_RC"; }
step() { PHASE="$1"; log "== $KIND: $1"; }
dc() { docker compose -p "$PROJECT" "$@"; }
dbq() { docker exec -i "$DBC" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1' <<<"$1"; }
adminq() { docker exec -i "$DBC" sh -c 'psql -U "$POSTGRES_USER" -d postgres -At -v ON_ERROR_STOP=1' <<<"$1"; }
onq() { docker exec -i "$DBC" sh -c "psql -U \"\$POSTGRES_USER\" -d $1 -At -v ON_ERROR_STOP=1" <<<"$2"; }
bgwait() { local rc=0; setsid "$@" <&0 & CHILD=$!; wait "$CHILD" || rc=$?; CHILD=""; return "$rc"; }
COUNTS_SQL="select /*q:legacy-counts*/ (select count(*) from users)||'/'||(select count(*) from workouts)||'/'||(select count(*) from elective_workouts)||'/'||(select count(*) from subscriptions)"

loss_window() {
  if [ "$KIND" = "R1" ]; then
    echo "data loss: none (the database is not changed; R1 only switches app/web back to the previous images)"
  else
    echo "DATA LOSS WINDOW: everything written to '$DB_NAME' after $BACKUP_AT (UTC, the pre-deploy dump) — workouts, onboardings,"
    echo "  payments/subscription extensions, settings made in the new Mini App — is NOT in the restored database."
    echo "  It stays in the database '${DB_NAME}_failed_<UTC timestamp of the apply run>' (kept, not dropped) for manual recovery;"
    echo "  reconcile Robokassa/Stars payments made in that window (runbook §7.4)."
  fi
}

on_signal() { trap '' PIPE; fail $((128 + $2)) "signal SIG$1"; exit "$FAIL_RC"; }
trap 'on_signal HUP 1' HUP
trap 'on_signal INT 2' INT
trap 'on_signal PIPE 13' PIPE
trap 'on_signal TERM 15' TERM
on_exit() {
  local rc=$?
  trap '' HUP INT PIPE TERM
  rc="${FAIL_RC:-$rc}"
  [ "$rc" -ne 0 ] || exit 0
  [ -n "$FAIL_REASON" ] || FAIL_REASON="exit $rc"
  if [ -n "$CHILD" ]; then kill -TERM -- "-$CHILD" 2>/dev/null || true; wait "$CHILD" 2>/dev/null || true; fi
  if [ "$WRITERS_STOPPED" = 1 ]; then dc stop app web >/dev/null 2>&1 || true; fi
  {
    echo "ERROR: $FAIL_REASON"
    echo "!! ROLLBACK $KIND ($MODE) FAILED at step '$PHASE', exit $rc"
    if [ "$WRITERS_STOPPED" = 1 ]; then echo "!! app/web are STOPPED and stay stopped."; else echo "!! nothing was stopped or changed."; fi
    if [ "$SWAPPED" = 1 ]; then echo "!! the database '$DB_NAME' IS the restored pre-deploy dump now; the failed state is kept as '${DB_NAME}_failed_$TS'."; fi
    echo "manifest: $MANIFEST   previous sha: $PREV_SHA   previous alembic: $PREV_REV"
  } >&7 2>/dev/null || true
  exit "$rc"
}
trap on_exit EXIT

# ------------------------------------------------------------------------------------------------ checks (read-only)
step "checks (read-only): manifest vs live compose project, images, $([ "$KIND" = R3 ] && echo "dump, ")database state"
for tool in setsid sha256sum; do command -v "$tool" >/dev/null || die "$tool is required"; done
cd "$PROD_DIR"
{ [ -f docker-compose.yml ] && [ -f .env ]; } || die "docker-compose.yml/.env not found in $PROD_DIR"
DBC="$(dc ps -q db | head -n1)"
[ -n "$DBC" ] || die "db container of project $PROJECT not found"
[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$DBC")" = "$PROJECT" ] || die "db container is not in project $PROJECT"
[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$DBC")" = "$PROD_DIR" ] || die "compose project $PROJECT is not from $PROD_DIR"
[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$DBC")" = "$COMPOSE_FILES" ] || die "compose config files differ from the manifest"
[ "$(docker inspect -f '{{.State.Running}}' "$DBC")" = "true" ] || die "db container is not running"
[ "$(docker exec "$DBC" sh -c 'echo "$POSTGRES_DB"')" = "$DB_NAME" ] || die "POSTGRES_DB of the db container differs from the manifest ($DB_NAME)"
for pair in "app:$APP_ID" "web:$WEB_ID"; do
  docker image inspect -f '{{.Id}}' "${pair#*:}" >/dev/null 2>&1 || die "previous ${pair%%:*} image ${pair#*:} no longer exists (pruned?) — R1/R3 code switch impossible, see runbook §7.5"
done
git cat-file -e "${PREV_SHA}^{commit}" 2>/dev/null || die "previous commit $PREV_SHA not found in $PROD_DIR"
[ -z "$(git status --porcelain)" ] || die "checkout in $PROD_DIR is not clean"
CUR_REV="$(dbq "select version_num from alembic_version")"
log "live: HEAD=$(git rev-parse HEAD) alembic=$CUR_REV; manifest: previous_sha=$PREV_SHA previous_alembic=$PREV_REV"
if [ "$KIND" = "R1" ]; then
  [ "$CUR_REV" = "$PREV_REV" ] || die "R1 is not valid: alembic_version is $CUR_REV, not $PREV_REV (migrations ran) — use R3"
  [ -z "$(m backfill_started_at)" ] || die "R1 is not valid: the backfill has started (manifest backfill_started_at) — use R3"
else
  { [ -f "$BACKUP" ] && [ -f "$BACKUP.sha256" ]; } || die "backup $BACKUP or its .sha256 is missing"
  sha256sum -c --quiet "$BACKUP.sha256" || die "backup checksum file does not verify"
  [ "$(sha256sum "$BACKUP" | cut -d' ' -f1)" = "$BACKUP_SHA" ] || die "backup sha256 differs from the manifest"
  toc="$(docker exec -i "$DBC" pg_restore -l < "$BACKUP" | wc -l)" || die "pg_restore -l failed"
  [ "$toc" -gt 10 ] || die "backup table of contents too short ($toc lines)"
  need_mb=$(( $(du -m "$BACKUP" | cut -f1) * 3 + MIN_DISK_MB ))
  avail="$(df -Pm "$PROD_DIR" | awk 'NR==2{print $4}')"
  [ "${avail:-0}" -ge "$need_mb" ] || die "free disk ${avail} MB < ${need_mb} MB needed for a second copy of the database"
  for d in "${DB_NAME}_rb_$TS" "${DB_NAME}_failed_$TS"; do
    [ -z "$(adminq "select 1 from pg_database where datname='$d'")" ] || die "database $d already exists"
  done
  log "backup OK: $BACKUP ($(du -h "$BACKUP" | cut -f1), $toc TOC entries, sha256 matches the manifest); free disk ${avail} MB"
fi
loss_window
if [ "$MODE" = "check" ]; then
  log "CHECK OK (read-only): $KIND is possible; nothing was stopped or changed. Apply: $0 $KIND $MANIFEST apply ROLLBACK-$KIND-$RUN_ID"
  exit 0
fi

# ------------------------------------------------------------------------------------------------ stop writers
step "stop app/web (db stays up)"
WRITERS_STOPPED=1
dc stop app web
conns="$(dbq "select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid()")"
[ "$conns" = "0" ] || die "$conns other connection(s) to $DB_NAME remain after stopping app/web"

if [ "$KIND" = "R3" ]; then
  # ---------------------------------------------------------------------------------------------- restore
  RB="${DB_NAME}_rb_$TS"; FAILED="${DB_NAME}_failed_$TS"
  step "restore the pre-deploy dump into a NEW database $RB (the live database is not touched yet)"
  docker exec "$DBC" sh -c "createdb -U \"\$POSTGRES_USER\" $RB"
  bgwait docker exec -i "$DBC" sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $RB --no-owner --exit-on-error --single-transaction" < "$BACKUP" \
    || die "pg_restore into $RB failed (live database unchanged; $RB can be dropped)"
  [ "$(onq "$RB" "select version_num from alembic_version")" = "$PREV_REV" ] || die "restored alembic_version differs from $PREV_REV"
  [ "$(onq "$RB" "$COUNTS_SQL")" = "$LEGACY_COUNTS" ] || die "restored legacy counts differ from the manifest ($LEGACY_COUNTS)"
  log "restored copy verified: alembic=$PREV_REV users/workouts/electives/subscriptions=$LEGACY_COUNTS"
  step "swap databases atomically: $DB_NAME -> $FAILED (kept), $RB -> $DB_NAME"
  conns="$(adminq "select count(*) from pg_stat_activity where datname in ('$DB_NAME','$RB')")"
  [ "$conns" = "0" ] || die "$conns connection(s) to $DB_NAME/$RB — cannot rename"
  adminq "ALTER DATABASE $DB_NAME RENAME TO $FAILED; ALTER DATABASE $RB RENAME TO $DB_NAME;" >/dev/null || die "database swap failed (single transaction: nothing renamed)"
  SWAPPED=1
  [ "$(dbq "select version_num from alembic_version")" = "$PREV_REV" ] || die "live alembic_version after swap differs from $PREV_REV"
  [ "$(dbq "$COUNTS_SQL")" = "$LEGACY_COUNTS" ] || die "live legacy counts after swap differ from the manifest"
  log "database $DB_NAME = pre-deploy dump ($BACKUP_AT); failed state kept as $FAILED"
fi

# ------------------------------------------------------------------------------------------------ previous code
step "previous code: checkout $PREV_SHA, :latest -> previous image IDs, start"
git checkout --quiet --detach "$PREV_SHA"
[ "$(git rev-parse HEAD)" = "$PREV_SHA" ] || die "HEAD != $PREV_SHA after checkout"
docker tag "$APP_ID" "$APP_REF"
docker tag "$WEB_ID" "$WEB_REF"
dc up -d --no-build app web
deadline=$((SECONDS + HEALTH_TIMEOUT))
until bgwait curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; do
  [ "$SECONDS" -lt "$deadline" ] || die "healthcheck $HEALTH_URL did not pass within ${HEALTH_TIMEOUT}s"
  bgwait sleep 3
done
for pair in "app:$APP_ID" "web:$WEB_ID"; do
  svc="${pair%%:*}"; want="${pair#*:}"
  cid="$(dc ps -q "$svc" | head -n1)"; [ -n "$cid" ] || die "$svc container missing after up"
  [ "$(docker inspect -f '{{.State.Running}}' "$cid")" = "true" ] || die "$svc is not running"
  [ "$(docker inspect -f '{{.State.Restarting}}' "$cid")" = "false" ] || die "$svc is restarting"
  [ "$(docker inspect -f '{{.Image}}' "$cid")" = "$want" ] || die "$svc does not run the previous image $want"
  log "running $svc: previous image ${want:0:19}"
done
[ "$(dbq "select version_num from alembic_version")" = "$PREV_REV" ] || die "alembic_version is not $PREV_REV after rollback"
printf 'rollback_%s_done_at=%s\n' "$KIND" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MANIFEST"
loss_window
log "ROLLBACK $KIND OK: previous sha $PREV_SHA, alembic $PREV_REV, app/web on previous images, healthcheck $HEALTH_URL passed"
log "do NOT run deploy.yml / deploy-run.sh for this SHA again; next attempt only via the guarded script (runbook §7.6)"
