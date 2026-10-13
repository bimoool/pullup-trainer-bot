#!/usr/bin/env bash
# STAGING-ONLY guarded deploy. Не трогает прод (`deploy.yml`, `deploy/deploy-run.sh`) и не заменяет `deploy-staging-run.sh`.
#
# Копия для ревью; на VPS ставится вручную владельцем как /home/deploy/deploy-staging-guarded-run.sh и вызывается ТОЛЬКО из
# deploy-staging-guarded-dispatch.sh (forced command отдельного SSH-ключа). Порядок установки — docs/STAGING_RC_RUNBOOK.md §3.2.
#
#   deploy-staging-guarded-run.sh <40-hex-sha> <dry-run|apply> <yes|no>
#     sha       точный проверенный коммит (detached checkout, без `git pull` плавающей ветки)
#     converge  dry-run: сведение только проверяется (ничего не пишет); apply: сведение применяется (после принятого фикса)
#     start     yes: запустить app/web после ВСЕХ успешных проверок; no: проверить всё и оставить app/web остановленными
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

if [[ $# -ne 3 || ! "$1" =~ ^[0-9a-f]{40}$ || ! "$2" =~ ^(dry-run|apply)$ || ! "$3" =~ ^(yes|no)$ ]]; then
  echo "usage: $0 <40-hex-sha> <dry-run|apply> <yes|no>   (got: $*)" >&2
  exit 2
fi
SHA="$1"; CONVERGE="$2"; START="$3"
SHA7="${SHA:0:7}"; TS="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d /tmp/guarded-deploy.XXXXXX)"
PHASE=0; PHASE_NAME="init"; WRITERS_STOPPED=0
PREV_SHA=""; PREV_REV=""; BACKUP_FILE=""; SAVED_TAGS=(); DBC=""
BUILT_ID_app=""; BUILT_ID_web=""

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
phase() { PHASE="$1"; PHASE_NAME="$2"; log "== [$1/9] $2"; }
dc() { docker compose -p "$PROJECT" "$@"; }
dbq() { bash -c "$STAGING_PSQL" <<<"$1"; }

summary() {
  echo "---- state for rollback (docs/STAGING_RC_RUNBOOK.md §8) ----"
  echo "target sha      : $SHA   (converge=$CONVERGE start=$START)"
  echo "previous sha    : ${PREV_SHA:-unknown}   previous alembic: ${PREV_REV:-unknown}"
  echo "backup          : ${BACKUP_FILE:-not created yet}"
  echo "rollback images : ${SAVED_TAGS[*]:-none saved yet}"
  echo "work dir (logs) : $WORK"
}

on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "!! GUARDED DEPLOY FAILED at phase ${PHASE} (${PHASE_NAME}), exit ${rc}" >&2
    if [ "$WRITERS_STOPPED" = 1 ]; then
      dc stop app web >/dev/null 2>&1 || true
      echo "!! app/web are STOPPED and stay stopped (stopped again if they had already been started); nothing was restored automatically." >&2
    else
      echo "!! failed before app/web were touched: nothing was changed." >&2
    fi
    summary >&2
  fi
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

# ------------------------------------------------------------------------------------------------ 1 rollback images
phase 1 "save current app/web images under our own tags (rollback without Alembic)"
for svc in app web; do
  cid="$(dc ps -aq "$svc" | head -n1)"
  [ -n "$cid" ] || die "no existing $svc container: cannot save its image for rollback"
  img="$(docker inspect -f '{{.Image}}' "$cid")"
  tag="local/staging-$svc:pre-$SHA7-$TS"
  docker tag "$img" "$tag"
  SAVED_TAGS+=("$tag")
  log "saved $svc image ${img:0:19} as $tag"
done

# ------------------------------------------------------------------------------------------------ 2 stop writers
phase 2 "stop writers (app = bot+workers, web = Mini App); db and redis stay up"
WRITERS_STOPPED=1
dc stop app web
conns="$(dbq "select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid()")"
[ "$conns" = "0" ] || die "$conns other connection(s) to the database remain after stopping app/web"
W1="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
sleep "$QUIESCE_SECONDS"
W2="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
[ "$W1" = "$W2" ] || die "database is still being written to ($W1 -> $W2)"
log "no writers: 0 foreign connections, write counter stable at $W2"

# ------------------------------------------------------------------------------------------------ 3 backup
phase 3 "backup + verified restore + data snapshot (before)"
umask 077; mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/staging-pre-$SHA7-$TS.dump"
docker exec "$DBC" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$BACKUP_FILE"
[ -s "$BACKUP_FILE" ] || die "backup file is empty"
sha256sum "$BACKUP_FILE" > "$BACKUP_FILE.sha256"
toc="$(docker exec -i "$DBC" pg_restore -l < "$BACKUP_FILE" | wc -l)"
[ "$toc" -gt 10 ] || die "backup table of contents too short ($toc lines)"
docker exec "$DBC" sh -c 'dropdb -U "$POSTGRES_USER" --if-exists restore_check && createdb -U "$POSTGRES_USER" restore_check'
docker exec -i "$DBC" sh -c 'pg_restore -U "$POSTGRES_USER" -d restore_check --no-owner' < "$BACKUP_FILE"
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
  dc build "$svc"
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
HEADS="$(dc run --rm -T app alembic heads | grep -E '\(head\)' | awk '{print $1}')"
[ -n "$HEADS" ] && [ "$(printf '%s\n' "$HEADS" | wc -l)" -eq 1 ] || die "expected exactly one Alembic head, got: $HEADS"
CUR="$(dbq "select version_num from alembic_version")"
if [ "$CUR" = "$HEADS" ]; then
  log "WARNING: database already at head $HEADS (a previous run migrated it); the pre-migration backup is the one from that earlier run"
elif [ "$CUR" = "$EXPECTED_FROM_REV" ]; then
  dc run --rm -T app alembic upgrade head
  [ "$(dbq "select version_num from alembic_version")" = "$HEADS" ] || die "alembic_version != head after upgrade"
else
  die "unexpected alembic revision $CUR (expected $EXPECTED_FROM_REV or head $HEADS)"
fi
log "alembic_version = $HEADS"

# ------------------------------------------------------------------------------------------------ 7 data checks
phase 7 "data checks after migration (expected transformations only)"
"$WORK/tgt/staging_data_check.sh" after-migration "$WORK/data" "$WORK/tgt/staging-allowed-diff.txt"

# ------------------------------------------------------------------------------------------------ 8 convergence
phase 8 "convergence ($CONVERGE)"
conv_json_check() { # <file> <expect_zero_mutations 0|1>
  dc run --rm -T app python -c '
import json, sys
d = json.load(sys.stdin)
bad = [u for u in d["users_detail"] if u.get("guard_violations")]
print("mode=%s total_mutations=%s guard_violations=%d" % (d["mode"], d["total_mutations"], len(bad)))
sys.exit(1 if bad or (sys.argv[1] == "1" and d["total_mutations"] != 0) else 0)
' "$2" < "$1"
}
repair() { dc run --rm -T app python scripts/repair_plan_convergence.py --all "$@"; }
history() { dc run --rm -T app python scripts/backfill_multi_program.py --converge-history "$@"; }
repair > "$WORK/conv_dry.json" 2> "$WORK/conv_dry.err"; conv_json_check "$WORK/conv_dry.json" 0
history > "$WORK/hist_dry.txt" 2> "$WORK/hist_dry.err"
"$WORK/tgt/staging_data_check.sh" same-as-migration "$WORK/data"
if [ "$CONVERGE" = "apply" ]; then
  "$WORK/tgt/staging_data_check.sh" hold-check
  repair --apply > "$WORK/conv_a1.json" 2> "$WORK/conv_a1.err"; conv_json_check "$WORK/conv_a1.json" 0
  repair --apply > "$WORK/conv_a2.json" 2> "$WORK/conv_a2.err"; conv_json_check "$WORK/conv_a2.json" 1
  history --apply > "$WORK/hist_a1.txt" 2> "$WORK/hist_a1.err"
  history --apply > "$WORK/hist_a2.txt" 2> "$WORK/hist_a2.err"
  if grep -Eq '(привязано|создано|обновлено|замещено)[^:]*: *[1-9]' "$WORK/hist_a2.txt"; then die "history convergence is not idempotent (second --apply changed something)"; fi
  "$WORK/tgt/staging_data_check.sh" after-convergence "$WORK/data"
else
  log "convergence NOT applied (dry-run mode): runtime convergence will run on the first GET /plan of the new build"
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
until curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; do
  [ "$SECONDS" -lt "$deadline" ] || die "healthcheck $HEALTH_URL did not pass within ${HEALTH_TIMEOUT}s"
  sleep 3
done
log "healthcheck OK: $HEALTH_URL"
for svc in app web; do
  cid="$(dc ps -q "$svc" | head -n1)"; [ -n "$cid" ] || die "$svc container missing after up"
  [ "$(docker inspect -f '{{.State.Running}}' "$cid")" = "true" ] || die "$svc is not running"
  [ "$(docker inspect -f '{{.State.Restarting}}' "$cid")" = "false" ] || die "$svc is restarting"
  want="BUILT_ID_$svc"; got="$(docker inspect -f '{{.Image}}' "$cid")"
  [ "$got" = "${!want}" ] || die "$svc runs image ${got:0:19}, not the one built by this run (${!want:0:19})"
  until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")" != "starting" ]; do
    [ "$SECONDS" -lt "$deadline" ] || die "$svc healthcheck still 'starting' after ${HEALTH_TIMEOUT}s"; sleep 3
  done
  st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  [ "$st" = "healthy" ] || [ "$st" = "none" ] || die "$svc health status is '$st'"
  log "running $svc: image ${got:0:19} == built by this run; health=$st"
done
[ "$(git rev-parse HEAD)" = "$SHA" ] || die "HEAD != $SHA after start"
[ "$(dbq "select version_num from alembic_version")" = "$HEADS" ] || die "alembic_version != head after start"

if [ -x "$CLEANUP_BIN" ]; then "$CLEANUP_BIN" || true; fi   # как в deploy-run.sh: только после полного успеха, ошибки очистки не валят выкат
summary
log "GUARDED DEPLOY OK sha=$SHA alembic=$HEADS converge=$CONVERGE services=started"
