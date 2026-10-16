#!/usr/bin/env bash
# PRODUCTION guarded deploy (MVP-1: legacy e7c2a4f9d1b3 -> b5d8e1f3a6c9 + полный legacy-сохраняющий backfill).
# Порядок, решения и что не проверено — docs/PRODUCTION_RUNBOOK.md. Не заменяет deploy.yml / deploy/deploy-run.sh
# (их для этого релиза НЕ использовать) и не вызывается ни одним workflow: запускает владелец вручную по SSH (root, tmux).
#
# Ставится ВНЕ репозитория (скрипт делает `git checkout` в каталоге прода, а bash читает исполняемый файл по частям):
#   /root/bin/deploy-production-guarded-run.sh и рядом /root/bin/rollback-production-guarded.sh (runbook §2).
#
#   deploy-production-guarded-run.sh <40-hex-sha> preflight
#   deploy-production-guarded-run.sh <40-hex-sha> rehearse-check
#   deploy-production-guarded-run.sh <40-hex-sha> apply PRODUCTION-APPLY-<первые 12 символов sha>
#
#   preflight       ТОЛЬКО ЧТЕНИЕ: печатает HEAD, alembic, размер БД, диск/память, последние бэкапы, контейнеры/образы,
#                   имена (не значения) обязательных переменных .env и переменных Google Sheets. Ничего не пишет: без
#                   `git fetch`, без временных файлов, без блокировки, без docker tag/stop/build/run.
#   rehearse-check  тот же путь, что apply, но ТОЛЬКО на НЕ-прод окружении (копия прод-дампа, runbook §4): отказ, если
#                   проект/каталог/MINI_APP_URL совпадают с продом. В конце поднимает только web (healthcheck) и снова
#                   останавливает его; бот (app) не стартует никогда (тестовый токен, двойной polling). Токен не нужен.
#   apply           выкат на прод; без точного токена подтверждения — отказ до любых действий.
#
# Фазы apply/rehearse-check (любая ошибка => fail-safe, см. ниже; авто-отката нет):
#   0 preflight + fetch + точный SHA   1 сохранить текущие образы (теги local/prod-*:pre-…) + manifest
#   2 checkout SHA + сборка app, затем web — ДО остановки (прод работает на прежних ID образов)
#   3 бэкап ДО остановки: pg_dump -Fc + sha256 + pg_restore -l + пробное восстановление (сбой => простоя не было)
#   4 остановить писателей (app, web; db/redis работают)   5 финальный бэкап при остановленных писателях (точка R3),
#     с той же проверкой + сверка счётчиков с живой БД   6 alembic upgrade head (одна транзакция)
#   7 проверка: ДО-таблицы не изменились   8 полный backfill scripts/backfill_multi_program.py: --dry-run -> apply ->
#     повтор (0 изменений) — ДО старта нового кода (новый код на первом GET создаёт пустой TrainingPlan, а backfill
#     пропускает пользователей с планом)   9 инварианты данных   10 старт app+web, healthcheck, проверка запущенных
#     образов   11 итог (post-deploy-cleanup НЕ запускается: он удалил бы образы отката), ротация старых бэкапов
#
# Fail-safe: ошибка/сигнал ДО остановки писателей => checkout и теги :latest возвращаются к прежним, прод работает как
# работал. ПОСЛЕ остановки => app/web остаются ОСТАНОВЛЕННЫМИ (даже если уже были запущены), печатается точная команда
# отката (R1 — если backfill не начинался и alembic не менялся; иначе R3). SIGKILL перехватить нельзя (runbook §6).
#
# Параметры (окружение; значения по умолчанию — из репозитория, источники в runbook §1). Неизвестное не угадывается:
# несовпадение с тем, что показывает compose-проект, — отказ.
#   PROD_DIR=/root/pullup-trainer-bot           каталог checkout (deploy/deploy-run.sh: repo_dir)
#   PROD_PROJECT=pullup-trainer-bot             compose-проект (метка com.docker.compose.project контейнеров)
#   PROD_COMPOSE_FILES=$PROD_DIR/docker-compose.yml  должно совпасть с меткой com.docker.compose.project.config_files
#   PROD_BACKUP_DIR=/root/backups               дампы, manifest, отчёты (вне репозитория и томов)
#   PROD_DB_NAME=pullup                         должно совпасть с POSTGRES_DB контейнера db и с именем БД в DATABASE_URL
#   PROD_MINI_APP_URL=https://app.bimoool.com   apply: MINI_APP_URL в .env обязан быть ровно им; rehearse: обязан отличаться
#   PROD_EXPECTED_FROM_REV=e7c2a4f9d1b3         ожидаемая текущая ревизия (= TO_REV: продолжение после прерванного выката)
#   PROD_EXPECTED_TO_REV=b5d8e1f3a6c9           единственный Alembic head выкатываемого SHA
#   PROD_HEALTH_URL                             по умолчанию http://<docker compose port web 8000>/health
#   PROD_REQUIRED_ANCESTORS=628144fa…        коммиты, которые обязан содержать SHA (через запятую): 628144f — фикс
#                                               MissingGreenlet в `backfill --dry-run` при уже смигрированных пользователях
#                                               (без него контрольный dry-run после apply падает); `-` — без проверки
#   PROD_KEEP_BACKUPS=3  PROD_QUIESCE_SECONDS=15  PROD_HEALTH_TIMEOUT=240  PROD_MIN_DISK_MB=3072  PROD_MIN_MEM_MB=400
# shellcheck disable=SC2016  # $POSTGRES_* намеренно раскрываются внутри контейнера db (sh -c '...'), не здесь
set -euo pipefail

usage() {
  echo "usage: $0 <40-hex-sha> preflight|rehearse-check" >&2
  echo "       $0 <40-hex-sha> apply PRODUCTION-APPLY-<first 12 hex of sha>   (got: $*)" >&2
}
if [[ $# -lt 2 || $# -gt 3 || ! "$1" =~ ^[0-9a-f]{40}$ || ! "$2" =~ ^(preflight|rehearse-check|apply)$ ]]; then
  usage "$@"; exit 2
fi
SHA="$1"; MODE="$2"; TOKEN="${3:-}"
if [ "$MODE" = "apply" ]; then
  [ "$TOKEN" = "PRODUCTION-APPLY-${SHA:0:12}" ] || {
    echo "refusing: apply requires the exact confirmation token PRODUCTION-APPLY-<first 12 hex of the sha> as the 3rd argument" >&2; exit 2; }
elif [ -n "$TOKEN" ]; then
  echo "refusing: a confirmation token is accepted only with apply" >&2; exit 2
fi

PROD_DIR="${PROD_DIR:-/root/pullup-trainer-bot}"
PROJECT="${PROD_PROJECT:-pullup-trainer-bot}"
COMPOSE_FILES="${PROD_COMPOSE_FILES:-$PROD_DIR/docker-compose.yml}"
BACKUP_DIR="${PROD_BACKUP_DIR:-/root/backups}"
DB_NAME_EXPECTED="${PROD_DB_NAME:-pullup}"
MINI_APP_URL_PROD="${PROD_MINI_APP_URL:-https://app.bimoool.com}"
EXPECTED_FROM_REV="${PROD_EXPECTED_FROM_REV:-e7c2a4f9d1b3}"
EXPECTED_TO_REV="${PROD_EXPECTED_TO_REV:-b5d8e1f3a6c9}"
HEALTH_URL="${PROD_HEALTH_URL:-}"
KEEP_BACKUPS="${PROD_KEEP_BACKUPS:-3}"
REQUIRED_ANCESTORS="${PROD_REQUIRED_ANCESTORS:-628144fa5457c41512db41af214c97a085fcb4b6}"
QUIESCE_SECONDS="${PROD_QUIESCE_SECONDS:-15}"; HEALTH_TIMEOUT="${PROD_HEALTH_TIMEOUT:-240}"
MIN_DISK_MB="${PROD_MIN_DISK_MB:-3072}"; MIN_MEM_MB="${PROD_MIN_MEM_MB:-400}"
# Только эти production-константы считаются «продом» для защиты rehearse-check (независимо от переопределений выше).
CANON_PROD_DIR="/root/pullup-trainer-bot"; CANON_PROD_PROJECT="pullup-trainer-bot"
REQUIRED_ENV_KEYS="BOT_TOKEN DATABASE_URL MINI_APP_URL"

# Значения попадают в SQL/команды — только безопасные символы, иначе отказ до любых действий.
bad_param() { echo "refusing: parameter $1='$2' is not allowed (must match $3)" >&2; exit 2; }
[[ "$PROD_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || bad_param PROD_DIR "$PROD_DIR" 'absolute path [A-Za-z0-9._/-]'
[[ "$BACKUP_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || bad_param PROD_BACKUP_DIR "$BACKUP_DIR" 'absolute path [A-Za-z0-9._/-]'
[[ "$COMPOSE_FILES" =~ ^/[A-Za-z0-9._/,-]+$ ]] || bad_param PROD_COMPOSE_FILES "$COMPOSE_FILES" 'absolute paths, comma-separated'
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || bad_param PROD_PROJECT "$PROJECT" '[a-z0-9_-]'
[[ "$DB_NAME_EXPECTED" =~ ^[a-z_][a-z0-9_]*$ ]] || bad_param PROD_DB_NAME "$DB_NAME_EXPECTED" '[a-z0-9_]'
[[ "$EXPECTED_FROM_REV" =~ ^[0-9a-f]{12}$ ]] || bad_param PROD_EXPECTED_FROM_REV "$EXPECTED_FROM_REV" '12 hex'
[[ "$EXPECTED_TO_REV" =~ ^[0-9a-f]{12}$ ]] || bad_param PROD_EXPECTED_TO_REV "$EXPECTED_TO_REV" '12 hex'
[[ "$MINI_APP_URL_PROD" =~ ^https://[A-Za-z0-9.-]+$ ]] || bad_param PROD_MINI_APP_URL "$MINI_APP_URL_PROD" 'https://host'
[[ -z "$HEALTH_URL" || "$HEALTH_URL" =~ ^http://(127\.0\.0\.1|localhost):[0-9]{2,5}/health$ ]] \
  || bad_param PROD_HEALTH_URL "$HEALTH_URL" 'http://127.0.0.1:<port>/health'
for p in KEEP_BACKUPS QUIESCE_SECONDS HEALTH_TIMEOUT MIN_DISK_MB MIN_MEM_MB; do
  [[ "${!p}" =~ ^[0-9]{1,6}$ ]] || bad_param "PROD_$p" "${!p}" 'integer'
done
[[ "$REQUIRED_ANCESTORS" =~ ^(-|[0-9a-f]{40}(,[0-9a-f]{40})*)$ ]] || bad_param PROD_REQUIRED_ANCESTORS "$REQUIRED_ANCESTORS" "'-' or 40-hex SHAs, comma-separated"
[ "$KEEP_BACKUPS" -ge 1 ] || bad_param PROD_KEEP_BACKUPS "$KEEP_BACKUPS" '>= 1'

SHA7="${SHA:0:7}"; TS="$(date -u +%Y%m%dT%H%M%SZ)"; RUN_ID="prod-$SHA7-$TS-$$"
ROLLBACK_BIN="$(cd "$(dirname "$0")" && pwd)/rollback-production-guarded.sh"
exec 7>&2                                 # исходный stderr: отчёт об отказе идёт сюда, даже если сигнал пришёл внутри `cmd 2> file`
WORK=""                                   # preflight временных файлов не создаёт
PHASE=0; PHASE_NAME="init"; WRITERS_STOPPED=0; CHECKED_OUT=0; MIGRATION_STARTED=0; BACKFILL_STARTED=0
PREV_SHA=""; PREV_REV=""; BACKUP_FILE=""; MANIFEST=""; SAVED_TAGS=(); DBC=""; DB_NAME=""
# shellcheck disable=SC2034  # читаются косвенно: ${!id} / ${!want}
declare PREV_ID_app="" PREV_ID_web="" PREV_REF_app="" PREV_REF_web="" BUILT_ID_app="" BUILT_ID_web=""
FAIL_RC=""; FAIL_REASON=""; CHILD=""

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { FAIL_RC="${FAIL_RC:-$1}"; FAIL_REASON="${FAIL_REASON:-$2}"; }   # первая причина побеждает
die() { fail 1 "$*"; exit "$FAIL_RC"; }   # причина печатается очисткой (on_exit) — ПОСЛЕ остановки сервисов
phase() { PHASE="$1"; PHASE_NAME="$2"; log "== [$1/11] $2"; }
dc() { docker compose -p "$PROJECT" "$@"; }
dbq() { docker exec -i "$DBC" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'  <<<"$1"; }
dbqf() { docker exec -i "$DBC" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1' < "$1"; }
# Долгие команды — в фоне + wait (сигнал прерывает wait сразу), в своей группе процессов (очистка гасит docker + плагин compose).
bgwait() { local rc=0; setsid "$@" <&0 & CHILD=$!; wait "$CHILD" || rc=$?; CHILD=""; return "$rc"; }
dcrun() { bgwait docker compose -p "$PROJECT" run --rm -T --label "guarded.run=$RUN_ID" "$@"; }
our_oneoffs() { docker ps -aq --filter "label=guarded.run=$RUN_ID" 2>/dev/null || true; }
mf() { [ -z "$MANIFEST" ] || printf '%s=%s\n' "$1" "$2" >> "$MANIFEST"; }   # manifest дописывается по ходу (откат читает маркеры)
envkey_set() { grep -qE "^$1=.+" "$PROD_DIR/.env"; }                          # значение НЕ печатается
envkey_is() { grep -qxF "$1=$2" "$PROD_DIR/.env"; }

rollback_hint() {
  [ -n "$MANIFEST" ] || return 0
  local run_id; run_id="$(sed -n 's/^run_id=//p' "$MANIFEST" 2>/dev/null | head -n1)"
  if [ "$BACKFILL_STARTED" = 1 ] || { [ "$MIGRATION_STARTED" = 1 ] && [ "$(dbq "select version_num from alembic_version" 2>/dev/null || echo unknown)" != "$PREV_REV" ]; }; then
    echo "rollback (data changed: R1 is NOT valid; R3 restores the pre-deploy dump — data written after the dump is lost, see runbook §7):"
    echo "  $ROLLBACK_BIN R3 $MANIFEST check"
    echo "  $ROLLBACK_BIN R3 $MANIFEST apply ROLLBACK-R3-$run_id"
  else
    echo "rollback (alembic_version unchanged and backfill not started: R1, previous images, no data change):"
    echo "  $ROLLBACK_BIN R1 $MANIFEST check"
    echo "  $ROLLBACK_BIN R1 $MANIFEST apply ROLLBACK-R1-$run_id"
  fi
}

summary() {
  echo "---- state for rollback (docs/PRODUCTION_RUNBOOK.md §7) ----"
  echo "mode            : $MODE   target sha: $SHA"
  echo "project / dir   : $PROJECT / $PROD_DIR   db: ${DB_NAME:-unknown}"
  echo "previous sha    : ${PREV_SHA:-unknown}   previous alembic: ${PREV_REV:-unknown}"
  echo "backup          : ${BACKUP_FILE:-not created yet}"
  echo "manifest        : ${MANIFEST:-not created yet}"
  echo "rollback images : ${SAVED_TAGS[*]:-none saved yet}"
  echo "work dir (logs) : ${WORK:-none}"
}

restore_previous_code() {   # до остановки писателей: вернуть checkout и :latest к прежним образам (ничего не останавливает)
  if [ "$CHECKED_OUT" = 1 ] && [ -n "$PREV_SHA" ]; then git -C "$PROD_DIR" checkout --quiet --detach "$PREV_SHA" >/dev/null 2>&1 || true; fi
  for svc in app web; do
    local id="PREV_ID_$svc" ref="PREV_REF_$svc"
    if [ -n "${!id}" ] && [ -n "${!ref}" ]; then docker tag "${!id}" "${!ref}" >/dev/null 2>&1 || true; fi
  done
}

on_signal() { trap '' PIPE; fail $((128 + $2)) "signal SIG$1"; exit "$FAIL_RC"; }
trap 'on_signal HUP 1' HUP
trap 'on_signal INT 2' INT
trap 'on_signal PIPE 13' PIPE
trap 'on_signal TERM 15' TERM
SIG_IGNORED_ON_ENTRY="$(awk '/^SigIgn:/{print $2}' /proc/$$/status 2>/dev/null || true)"

on_exit() {
  local rc=$? ids report
  trap '' HUP INT PIPE TERM
  rc="${FAIL_RC:-$rc}"
  [ "$rc" -ne 0 ] || exit 0
  [ -n "$FAIL_REASON" ] || FAIL_REASON="exit $rc"
  # 1) действия (не зависят от stdout): one-off контейнеры этого запуска, клиент compose, затем app/web
  ids="$(our_oneoffs)"
  # shellcheck disable=SC2086
  if [ -n "$ids" ]; then docker kill $ids >/dev/null 2>&1 || true; fi
  if [ -n "$CHILD" ]; then
    kill -TERM -- "-$CHILD" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 -- "-$CHILD" 2>/dev/null || break; sleep 0.25; done
    kill -KILL -- "-$CHILD" 2>/dev/null || true
    wait "$CHILD" 2>/dev/null || true
  fi
  ids="$(printf '%s\n%s\n' "$ids" "$(our_oneoffs)" | sed '/^$/d' | sort -u | tr '\n' ' ')"
  if [ -n "${ids// /}" ]; then
    # shellcheck disable=SC2086
    docker kill $ids >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
  if [ "$WRITERS_STOPPED" = 1 ]; then
    dc stop app web >/dev/null 2>&1 || true
    STATE_MSG="app/web are STOPPED and stay stopped (stopped again if they had already been started); nothing was restored automatically."
  elif [ "$CHECKED_OUT" = 1 ]; then
    restore_previous_code
    STATE_MSG="failed before app/web were stopped: production keeps running the previous containers; checkout and :latest tags were returned to the previous ones; the database was not touched."
  else
    STATE_MSG="failed before anything was changed."
  fi
  mf failed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ) phase=$PHASE"
  report="$(
    echo "ERROR: ${FAIL_REASON}"
    echo "!! PRODUCTION GUARDED ${MODE} FAILED at phase ${PHASE} (${PHASE_NAME}), exit ${rc}"
    echo "!! one-off containers of this run stopped: ${ids:-none}"
    echo "!! $STATE_MSG"
    if [ "$WRITERS_STOPPED" = 1 ]; then rollback_hint; fi
    summary
  )"
  # 2) отчёт в файл (не в preflight: он ничего не пишет), 3) вывод последним, ошибки записи игнорируются
  if [ -n "$WORK" ]; then
    printf '%s\n' "$report" > "$WORK/FAILED.txt" 2>/dev/null || true
    if [ -d "$BACKUP_DIR" ]; then cp "$WORK/FAILED.txt" "$BACKUP_DIR/prod-guarded-$SHA7-$TS.FAILED.txt" 2>/dev/null || true; fi
  fi
  printf '%s\n' "$report" >&7 2>/dev/null || true
  exit "$rc"
}
trap on_exit EXIT

# ------------------------------------------------------------------------------------------------ 0 preflight
phase 0 "preflight ($MODE): exact SHA, compose project identity, resources, env key names"
if [ -n "$SIG_IGNORED_ON_ENTRY" ]; then
  for pair in HUP:1 INT:2 PIPE:13 TERM:15; do
    if (( (16#$SIG_IGNORED_ON_ENTRY >> (${pair#*:} - 1)) & 1 )); then
      log "WARNING: SIG${pair%%:*} was ignored when this run started (nohup?) and cannot be trapped"
    fi
  done
fi
log "config: dir=$PROD_DIR project=$PROJECT compose_files=$COMPOSE_FILES backup_dir=$BACKUP_DIR db=$DB_NAME_EXPECTED expected_rev=$EXPECTED_FROM_REV->$EXPECTED_TO_REV"
if [ "$MODE" = "rehearse-check" ]; then
  [ "$PROJECT" != "$CANON_PROD_PROJECT" ] || die "rehearse-check refuses the production compose project '$PROJECT' (use a separate rehearsal project)"
  [ "$PROD_DIR" != "$CANON_PROD_DIR" ] || die "rehearse-check refuses the production directory $PROD_DIR"
fi
for tool in setsid pgrep flock sha256sum; do command -v "$tool" >/dev/null || die "$tool is required"; done
cd "$PROD_DIR"
{ [ -f docker-compose.yml ] && [ -f .env ]; } || die "docker-compose.yml/.env not found in $PROD_DIR"
[ -z "$(git status --porcelain)" ] || die "checkout in $PROD_DIR is not clean (git status --porcelain is not empty)"
PREV_SHA="$(git rev-parse HEAD)"
if [ "$MODE" != "preflight" ]; then git fetch --quiet origin || die "git fetch origin failed"; fi
if ! git cat-file -e "${SHA}^{commit}" 2>/dev/null; then
  [ "$MODE" = "preflight" ] && die "commit $SHA is not in the local repository (preflight does not fetch; apply/rehearse-check fetch it first)"
  die "commit $SHA is not available after fetch"
fi
[ "$(git rev-parse --verify --quiet "${SHA}^{commit}")" = "$SHA" ] || die "git resolves $SHA to a different commit"
if [ "$REQUIRED_ANCESTORS" != "-" ]; then
  for a in ${REQUIRED_ANCESTORS//,/ }; do
    git cat-file -e "${a}^{commit}" 2>/dev/null || die "required commit $a is not in the local repository"
    git merge-base --is-ancestor "$a" "$SHA" || die "target $SHA does not contain required commit $a (PROD_REQUIRED_ANCESTORS, runbook §1)"
  done
  log "target contains required commits: $REQUIRED_ANCESTORS"
fi
for f in docs/rehearsal/sql/gen_hash_queries.sql scripts/backfill_multi_program.py scripts/repair_plan_convergence.py; do
  git cat-file -e "${SHA}:${f}" 2>/dev/null || die "$f is missing in $SHA"
done
log "prod HEAD=$PREV_SHA target=$SHA"
# .env: только имена ключей, значения никогда не печатаются
missing=""; for k in $REQUIRED_ENV_KEYS; do envkey_set "$k" || missing="$missing $k"; done
log "required env keys (names only): $REQUIRED_ENV_KEYS — missing/empty:${missing:- none}"
sheets="$(grep -oE '^GOOGLE_SHEETS_[A-Z0-9_]*=.' .env 2>/dev/null | sed 's/=.$//' | sort -u | tr '\n' ' ' || true)"
log "Google Sheets export env keys set (names only): ${sheets:-none}"
log "env key names present: $(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | tr -d '=' | sort -u | tr '\n' ' ')"
[ -z "$missing" ] || die "required env keys missing or empty:$missing"
if [ "$MODE" = "rehearse-check" ]; then
  if envkey_is MINI_APP_URL "$MINI_APP_URL_PROD"; then die "rehearse-check: MINI_APP_URL is the production URL — this looks like production"; fi
  log "MINI_APP_URL differs from production (rehearsal)"
else
  envkey_is MINI_APP_URL "$MINI_APP_URL_PROD" || die "MINI_APP_URL in .env is not exactly $MINI_APP_URL_PROD"
  log "MINI_APP_URL == $MINI_APP_URL_PROD"
fi
log "docker compose version: $(docker compose version 2>&1 | head -n1)"
avail="$(df -Pm "$PROD_DIR" | awk 'NR==2{print $4}')"
mem="$(free -m 2>/dev/null | awk 'NR==2{print $7}')"
log "free disk ${avail} MB (min ${MIN_DISK_MB}); memory available ${mem:-?} MB (min ${MIN_MEM_MB}), swap used $(free -m 2>/dev/null | awk 'NR==3{print $3}') MB"
[ "${avail:-0}" -ge "$MIN_DISK_MB" ] || die "free disk ${avail} MB < ${MIN_DISK_MB} MB"
[ "${mem:-0}" -ge "$MIN_MEM_MB" ] || die "available memory ${mem:-?} MB < ${MIN_MEM_MB} MB"
DBC="$(dc ps -q db | head -n1)"
[ -n "$DBC" ] || die "db container of compose project $PROJECT not found"
[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$DBC")" = "$PROJECT" ] || die "db container is not in project $PROJECT"
wd="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$DBC")"
[ "$wd" = "$PROD_DIR" ] || die "compose project $PROJECT was created from '$wd', not from $PROD_DIR (set PROD_DIR/PROD_PROJECT explicitly)"
cf="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$DBC")"
[ "$cf" = "$COMPOSE_FILES" ] || die "compose project uses config files '$cf', expected '$COMPOSE_FILES' (set PROD_COMPOSE_FILES explicitly)"
[ "$(docker inspect -f '{{.State.Running}}' "$DBC")" = "true" ] || die "db container is not running"
DB_NAME="$(docker exec "$DBC" sh -c 'echo "$POSTGRES_DB"')"
[ "$DB_NAME" = "$DB_NAME_EXPECTED" ] || die "POSTGRES_DB of the db container is '$DB_NAME', expected '$DB_NAME_EXPECTED' (set PROD_DB_NAME explicitly)"
case "$DB_NAME" in *staging*|*test*) die "database name '$DB_NAME' looks like staging/test" ;; esac
url_db="$(sed -nE 's#^DATABASE_URL=[^/]*//[^/]*/([A-Za-z0-9_]+)([?].*)?$#\1#p' .env | head -n1)"
[ "$url_db" = "$DB_NAME" ] || die "database name in DATABASE_URL ('${url_db:-unparsed}') differs from POSTGRES_DB '$DB_NAME'"
PREV_REV="$(dbq "select version_num from alembic_version")"
log "alembic current=$PREV_REV db=$DB_NAME size=$(dbq "select pg_size_pretty(pg_database_size(current_database()))")"
log "legacy counts users/onboarded/workouts/electives/subscriptions: $(dbq "select (select count(*) from users)||'/'||(select count(*) from users where onboarding_completed_at is not null)||'/'||(select count(*) from workouts)||'/'||(select count(*) from elective_workouts)||'/'||(select count(*) from subscriptions)")"
case "$PREV_REV" in
  "$EXPECTED_FROM_REV") ;;
  *) die "unexpected alembic revision $PREV_REV (expected $EXPECTED_FROM_REV; set PROD_EXPECTED_FROM_REV only after reading runbook §6)" ;;
esac
log "last backups in $BACKUP_DIR: $(find "$BACKUP_DIR" -maxdepth 1 -name 'prod-pre-*.dump' -printf '%TY-%Tm-%Td %f; ' 2>/dev/null | sort -r | head -c 400 || true)"
log "containers of $PROJECT:"; { dc ps -a 2>&1 || true; } | sed 's/^/    /'
log "images of $PROJECT:"; { dc images 2>&1 || true; } | sed 's/^/    /'
for svc in app web; do
  cid="$(dc ps -aq "$svc" | head -n1)"
  [ -n "$cid" ] || die "no existing $svc container: cannot save its image for rollback"
  eval "PREV_ID_$svc=\$(docker inspect -f '{{.Image}}' \"\$cid\")"
  eval "PREV_REF_$svc=\$(docker inspect -f '{{.Config.Image}}' \"\$cid\")"
done
if [ -z "$HEALTH_URL" ]; then
  hp="$(dc port web 8000 2>/dev/null | head -n1 || true)"
  [[ "$hp" =~ ^(127\.0\.0\.1|localhost):[0-9]{2,5}$ ]] || die "cannot determine the web port (docker compose port web 8000 -> '${hp}'); set PROD_HEALTH_URL"
  HEALTH_URL="http://$hp/health"
fi
log "health url: $HEALTH_URL"
docker compose run --help 2>/dev/null | grep -q -- '--label' || die "this docker compose has no 'run --label'"
leftover="$(docker ps -aq --filter "label=guarded.run" 2>/dev/null || true)"
[ -z "$leftover" ] || die "one-off containers of an earlier guarded run still exist: ${leftover//$'\n'/ } — inspect and remove them first (runbook §6)"
if pgrep -f 'deploy-run\.sh' >/dev/null 2>&1; then die "the plain production deploy (deploy-run.sh) is running"; fi
if pgrep -f 'deploy-staging(-guarded)?-run\.sh' >/dev/null 2>&1; then die "a staging deploy is running (shared 1 GB VPS)"; fi

if [ "$MODE" = "preflight" ]; then
  log "PREFLIGHT OK (read-only): nothing was fetched, stopped, built, migrated, tagged or written; target $SHA, prod HEAD $PREV_SHA, alembic $PREV_REV"
  exit 0
fi

umask 077; mkdir -p "$BACKUP_DIR"
exec 8>"$BACKUP_DIR/.prod-guarded.lock"
flock -n 8 || die "another production guarded run holds $BACKUP_DIR/.prod-guarded.lock"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/prod-guarded.XXXXXX")"
mkdir -p "$WORK/tgt"
git show "${SHA}:docs/rehearsal/sql/gen_hash_queries.sql" > "$WORK/tgt/gen_hash_queries.sql"

# ------------------------------------------------------------------------------------------------ 1 rollback images
phase 1 "save current app/web images under own tags + manifest (rollback without Alembic)"
MANIFEST="$BACKUP_DIR/prod-pre-$SHA7-$TS.manifest"
{
  echo "# before-manifest of $RUN_ID (docs/PRODUCTION_RUNBOOK.md §7); read by rollback-production-guarded.sh"
  echo "run_id=$RUN_ID"
  echo "mode=$MODE"
  echo "target_sha=$SHA"
  echo "previous_sha=$PREV_SHA"
  echo "previous_alembic=$PREV_REV"
  echo "project=$PROJECT"
  echo "dir=$PROD_DIR"
  echo "compose_files=$COMPOSE_FILES"
  echo "db_name=$DB_NAME"
  echo "health_url=$HEALTH_URL"
} > "$MANIFEST"
for svc in app web; do
  id="PREV_ID_$svc"; ref="PREV_REF_$svc"; tag="local/prod-$svc:pre-$SHA7-$TS"
  docker tag "${!id}" "$tag"
  SAVED_TAGS+=("$tag")
  printf '%s_image_id=%s\n%s_compose_image=%s\n%s_saved_tag=%s\n' "$svc" "${!id}" "$svc" "${!ref}" "$svc" "$tag" >> "$MANIFEST"
  log "saved $svc image ${!id:0:19} (${!ref}) as $tag"
done

# ------------------------------------------------------------------------------------------------ 2 checkout + build
phase 2 "checkout $SHA and build app, then web — BEFORE stopping anything (production keeps running)"
CHECKED_OUT=1
git checkout --quiet --detach "$SHA"
[ "$(git rev-parse HEAD)" = "$SHA" ] || die "HEAD != $SHA after checkout"
[ -z "$(git status --porcelain)" ] || die "working tree is not clean after checkout"
export COMPOSE_PARALLEL_LIMIT=1
t0=$SECONDS
for svc in app web; do
  log "memory before build $svc: $(free -m 2>/dev/null | awk 'NR==2{print "available "$7" MB"}')"
  bgwait docker compose -p "$PROJECT" build "$svc" || die "build of $svc failed"
done
imgname() { dc config --images 2>/dev/null | grep -E "[-_]$1\$" | head -n1; }
for svc in app web; do
  name="$(imgname "$svc")"; [ -n "$name" ] || die "cannot resolve image name of $svc"
  id="$(docker image inspect -f '{{.Id}}' "$name")"; [ -n "$id" ] || die "built image $name not found"
  eval "BUILT_ID_$svc=\$id"
  mf "${svc}_built_id" "$id"
  log "built $svc: $name ${id:0:19}"
done
log "build took $((SECONDS - t0))s"

# ------------------------------------------------------------------------------------------------ backup helper
COUNTS_SQL="select /*q:legacy-counts*/ (select count(*) from users)||'/'||(select count(*) from workouts)||'/'||(select count(*) from elective_workouts)||'/'||(select count(*) from subscriptions)"
RCHK="${DB_NAME}_restore_check"
rq() { docker exec -i "$DBC" sh -c "psql -U \"\$POSTGRES_USER\" -d $RCHK -At -v ON_ERROR_STOP=1" <<<"$1"; }
BK_TOC=""; BK_COUNTS=""
make_backup() { # <file> — pg_dump -Fc, sha256, оглавление, пробное восстановление в отдельную БД -> BK_TOC, BK_COUNTS
  # не в $(…): подоболочка потеряла бы причину отказа (die) и PID долгой команды для очистки по сигналу
  local f="$1"
  bgwait docker exec "$DBC" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$f" || die "pg_dump failed ($f)"
  [ -s "$f" ] || die "backup file $f is empty"
  sha256sum "$f" > "$f.sha256"
  sha256sum -c --quiet "$f.sha256" || die "backup checksum does not verify ($f)"
  BK_TOC="$(docker exec -i "$DBC" pg_restore -l < "$f" | wc -l)" || die "pg_restore -l failed ($f)"
  [ "$BK_TOC" -gt 10 ] || die "backup table of contents too short ($BK_TOC lines, $f)"
  docker exec "$DBC" sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists $RCHK && createdb -U \"\$POSTGRES_USER\" $RCHK"
  bgwait docker exec -i "$DBC" sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $RCHK --no-owner --exit-on-error" < "$f" || die "test restore of $f failed"
  [ "$(rq "select version_num from alembic_version")" = "$PREV_REV" ] || die "restored alembic_version of $f differs from $PREV_REV"
  BK_COUNTS="$(rq "$COUNTS_SQL")" || die "restored copy of $f cannot be read"
  docker exec "$DBC" sh -c "dropdb -U \"\$POSTGRES_USER\" $RCHK"
}

# ------------------------------------------------------------------------------------------------ 3 pre-stop backup
phase 3 "pre-stop backup while production still runs: proves dump + restore work BEFORE any downtime"
PRESTOP_FILE="$BACKUP_DIR/prod-prestop-$SHA7-$TS.dump"
make_backup "$PRESTOP_FILE"
mf backup_prestop "$PRESTOP_FILE"
log "pre-stop backup OK: $PRESTOP_FILE ($(du -h "$PRESTOP_FILE" | cut -f1), $BK_TOC TOC entries, restore check passed); NOT the rollback point (writers were running)"

# ------------------------------------------------------------------------------------------------ 4 stop writers
phase 4 "stop writers (app = bot + workers, web = Mini App); db and redis stay up — DOWNTIME STARTS"
WRITERS_STOPPED=1
mf writers_stopped_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
dc stop app web
conns="$(dbq "select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid()")"
[ "$conns" = "0" ] || die "$conns other connection(s) to the database remain after stopping app/web"
W1="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
bgwait sleep "$QUIESCE_SECONDS"
W2="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
[ "$W1" = "$W2" ] || die "database is still being written to ($W1 -> $W2)"
log "no writers: 0 foreign connections, write counter stable at $W2"

# ------------------------------------------------------------------------------------------------ 5 final backup
phase 5 "final backup with writers stopped (the R3 rollback point) + verified restore + snapshot before"
BACKUP_FILE="$BACKUP_DIR/prod-pre-$SHA7-$TS.dump"
LEGACY_COUNTS="$(dbq "$COUNTS_SQL")"
make_backup "$BACKUP_FILE"
[ "$BK_COUNTS" = "$LEGACY_COUNTS" ] || die "restored table counts ($BK_COUNTS) differ from live ($LEGACY_COUNTS)"
W3="$(dbq "select coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0) from pg_stat_user_tables")"
[ "$W3" = "$W2" ] || die "database was written to during the backup ($W2 -> $W3)"
mf backup "$BACKUP_FILE"
mf backup_sha256 "$(cut -d' ' -f1 "$BACKUP_FILE.sha256")"
mf backup_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mf legacy_counts "$LEGACY_COUNTS"
log "final backup OK: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1), $BK_TOC TOC entries, sha256 in $BACKUP_FILE.sha256); restore check passed (users/workouts/electives/subscriptions = $LEGACY_COUNTS)"
dbqf "$WORK/tgt/gen_hash_queries.sql" > "$WORK/hq_legacy.sql"
[ -s "$WORK/hq_legacy.sql" ] || die "generated hash queries are empty"
dbqf "$WORK/hq_legacy.sql" > "$WORK/hq_before.txt"
[ "$(wc -l < "$WORK/hq_before.txt")" -eq "$(wc -l < "$WORK/hq_legacy.sql")" ] || die "hash query count mismatch (before)"
log "snapshot before: $(wc -l < "$WORK/hq_before.txt") pre-existing tables hashed (row count + md5 of all columns)"
same_legacy() { # <label>: каждая ДО-таблица (число строк и хэш ДО-колонок) идентична снимку «до»
  dbqf "$WORK/hq_legacy.sql" > "$WORK/hq_legacy_$1.txt"
  if ! diff <(sort "$WORK/hq_before.txt") <(sort "$WORK/hq_legacy_$1.txt") > "$WORK/hq_legacy_$1.diff"; then
    die "pre-existing (legacy) data changed $1: tables $(awk -F'|' '/^[<>]/{print $1}' "$WORK/hq_legacy_$1.diff" | sed 's/^[<>] //' | sort -u | tr '\n' ' ')"
  fi
  log "legacy data unchanged $1: $(wc -l < "$WORK/hq_legacy_$1.txt") tables identical to the snapshot before"
}

# ------------------------------------------------------------------------------------------------ 6 migration
phase 6 "alembic upgrade head (single transaction)"
dcrun app alembic heads > "$WORK/heads.txt" || die "alembic heads failed"
HEADS="$(grep -E '\(head\)' "$WORK/heads.txt" | awk '{print $1}')"
{ [ -n "$HEADS" ] && [ "$(printf '%s\n' "$HEADS" | wc -l)" -eq 1 ]; } || die "expected exactly one Alembic head, got: $HEADS"
[ "$HEADS" = "$EXPECTED_TO_REV" ] || die "Alembic head of $SHA is $HEADS, this run is written for $EXPECTED_TO_REV"
CUR="$(dbq "select version_num from alembic_version")"
[ "$CUR" = "$PREV_REV" ] || die "alembic revision changed under us ($PREV_REV -> $CUR)"
if [ "$CUR" = "$HEADS" ]; then
  log "WARNING: database already at head $HEADS (continuation run); THIS run's dump is post-migration — R3 must use the dump of the original run"
else
  MIGRATION_STARTED=1; mf migration_started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  t0=$SECONDS
  dcrun app alembic upgrade head || die "alembic upgrade head failed (single transaction: alembic_version should still be $PREV_REV)"
  [ "$(dbq "select version_num from alembic_version")" = "$HEADS" ] || die "alembic_version != head after upgrade"
  mf migration_committed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "migration took $((SECONDS - t0))s"
fi
log "alembic_version = $HEADS"

# ------------------------------------------------------------------------------------------------ 7 data check after migration
phase 7 "data check after migration: no pre-existing row changed"
same_legacy after-migration
dbqf "$WORK/tgt/gen_hash_queries.sql" > "$WORK/hq_all.sql"      # теперь — все таблицы, включая новые (v2)
[ -s "$WORK/hq_all.sql" ] || die "generated hash queries (all tables) are empty"
hash_all() { dbqf "$WORK/hq_all.sql" > "$WORK/hq_all_$1.txt"; }
hash_all migration

# ------------------------------------------------------------------------------------------------ 8 backfill
phase 8 "full legacy-preserving backfill (dry-run -> apply -> re-apply), BEFORE the new code starts"
REPORT_DIR="$BACKUP_DIR/prod-backfill-$SHA7-$TS"; mkdir -p "$REPORT_DIR"
backfill() { dcrun app python scripts/backfill_multi_program.py "$@"; }
num() { sed -nE "s/^ *$2: ([0-9]+)( .*)?\$/\\1/p" "$1" | head -n1; }   # <file> <label> — число из отчёта backfill
ONBOARDED_SQL="$(dbq "select count(*) from users where onboarding_completed_at is not null")"
backfill --dry-run > "$WORK/backfill_dry.txt" 2> "$WORK/backfill_dry.err" || die "backfill --dry-run failed (see $WORK/backfill_dry.err)"
cp "$WORK/backfill_dry.txt" "$REPORT_DIR/1-dry-run.txt"
grep -qx 'DRY-RUN (ничего не записано)' "$WORK/backfill_dry.txt" || die "backfill --dry-run did not report a dry run"
ONB="$(num "$WORK/backfill_dry.txt" 'Онбордившихся пользователей')"; WILL="$(num "$WORK/backfill_dry.txt" 'будет мигрировано')"
ALREADY="$(num "$WORK/backfill_dry.txt" 'уже было мигрировано \(пропущено\)')"
{ [ -n "$ONB" ] && [ -n "$WILL" ] && [ -n "$ALREADY" ]; } || die "cannot parse the backfill dry-run report ($REPORT_DIR/1-dry-run.txt)"
[ "$ONB" = "$ONBOARDED_SQL" ] || die "backfill sees $ONB onboarded users, database has $ONBOARDED_SQL"
[ $((WILL + ALREADY)) -eq "$ONB" ] || die "backfill dry-run: will migrate $WILL + already $ALREADY != onboarded $ONB"
hash_all dry-run
cmp -s "$WORK/hq_all_migration.txt" "$WORK/hq_all_dry-run.txt" || die "backfill --dry-run wrote to the database"
log "backfill dry-run: onboarded=$ONB will_migrate=$WILL already_migrated=$ALREADY (report $REPORT_DIR/1-dry-run.txt); database unchanged"
sed 's/^/    /' "$WORK/backfill_dry.txt"
BACKFILL_STARTED=1; mf backfill_started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
t0=$SECONDS
backfill > "$WORK/backfill_a1.txt" 2> "$WORK/backfill_a1.err" || die "backfill (apply) failed (see $WORK/backfill_a1.err); committed users stay migrated — R3 or re-run"
cp "$WORK/backfill_a1.txt" "$REPORT_DIR/2-apply.txt"
log "backfill apply took $((SECONDS - t0))s"
sed 's/^/    /' "$WORK/backfill_a1.txt"
grep -qx 'Прогон завершён' "$WORK/backfill_a1.txt" || die "backfill apply did not finish"
! grep -q 'РАСХОЖДЕНИЕ' "$WORK/backfill_a1.txt" || die "backfill apply reports РАСХОЖДЕНИЕ (expected vs actual totals differ), see $REPORT_DIR/2-apply.txt"
[ "$(num "$WORK/backfill_a1.txt" 'мигрировано в этом прогоне')" = "$WILL" ] || die "backfill apply migrated a different number of users than the dry-run ($WILL)"
hash_all apply1
same_legacy after-backfill
backfill > "$WORK/backfill_a2.txt" 2> "$WORK/backfill_a2.err" || die "backfill re-run failed"
cp "$WORK/backfill_a2.txt" "$REPORT_DIR/3-reapply.txt"
[ "$(num "$WORK/backfill_a2.txt" 'мигрировано в этом прогоне')" = "0" ] || die "backfill re-run migrated users again (not idempotent)"
[ "$(num "$WORK/backfill_a2.txt" 'уже было мигрировано \(пропущено\)')" = "$ONB" ] || die "backfill re-run did not skip all $ONB onboarded users"
hash_all apply2
cmp -s "$WORK/hq_all_apply1.txt" "$WORK/hq_all_apply2.txt" || die "backfill re-run changed the database (not idempotent)"
mf backfill_done_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# контрольный dry-run после apply: все онбордившиеся уже смигрированы, мигрировать нечего, БД не меняется
backfill --dry-run > "$WORK/backfill_dry2.txt" 2> "$WORK/backfill_dry2.err" || die "post-apply backfill --dry-run failed (see $WORK/backfill_dry2.err; needs 628144f)"
cp "$WORK/backfill_dry2.txt" "$REPORT_DIR/3b-post-apply-dry-run.txt"
[ "$(num "$WORK/backfill_dry2.txt" 'будет мигрировано')" = "0" ] || die "post-apply dry-run would still migrate users"
[ "$(num "$WORK/backfill_dry2.txt" 'уже было мигрировано \(пропущено\)')" = "$ONB" ] || die "post-apply dry-run does not see all $ONB onboarded users as migrated"
hash_all dry-run2
cmp -s "$WORK/hq_all_apply2.txt" "$WORK/hq_all_dry-run2.txt" || die "post-apply backfill --dry-run wrote to the database"
log "backfill idempotent: re-run migrated 0, skipped $ONB; post-apply dry-run: will migrate 0; database unchanged"
# Контроль сведения (только чтение): история — 0 изменений; план — 0 нарушений guard'ов (мутации сделает рантайм на GET /plan)
backfill --converge-history > "$WORK/converge_dry.txt" 2> "$WORK/converge_dry.err" || die "converge-history dry-run failed"
cp "$WORK/converge_dry.txt" "$REPORT_DIR/4-converge-history-dry-run.txt"
res="$({ grep '^RESULT-JSON ' "$WORK/converge_dry.txt" || true; } | tail -n1)"
[ -n "$res" ] || die "converge-history printed no RESULT-JSON line"
mut="$(printf '%s' "$res" | grep -oE '"mutations": [0-9]+' | grep -oE '[0-9]+$' || true)"
[ "$mut" = "0" ] || die "converge-history dry-run after backfill reports mutations=${mut:-?} (expected 0), see $REPORT_DIR/4-converge-history-dry-run.txt"
log "history convergence after backfill: mutations=0"
dcrun app python scripts/repair_plan_convergence.py --all > "$WORK/repair_dry.json" 2> "$WORK/repair_dry.err" || die "repair_plan_convergence --all (dry-run) failed or reported a guard violation"
cp "$WORK/repair_dry.json" "$REPORT_DIR/5-repair-plan-dry-run.json"
dcrun app python -c '
import json, sys
d = json.load(sys.stdin)
if d.get("error"):
    print("error: %s" % d["error"]); sys.exit(1)
bad = [u for u in d.get("users_detail", []) if u.get("guard_violations")]
print("plan convergence dry-run: users=%s total_mutations=%s guard_violations=%d" % (d.get("users"), d.get("total_mutations"), len(bad)))
sys.exit(1 if bad else 0)
' < "$WORK/repair_dry.json" || die "plan convergence dry-run: guard violations (see $REPORT_DIR/5-repair-plan-dry-run.json)"
hash_all control
cmp -s "$WORK/hq_all_apply2.txt" "$WORK/hq_all_control.txt" || die "a dry-run control step wrote to the database"

# ------------------------------------------------------------------------------------------------ 9 invariants
phase 9 "data invariants after backfill"
same_legacy final
inv() { # <name> <sql returning 0 when OK>
  local v; v="$(dbq "$2")"
  [ "$v" = "0" ] || die "invariant $1 violated ($v)"
  log "invariant $1: OK"
}
inv onboarded-without-plan "select /*inv:noplan*/ count(*) from users u where u.onboarding_completed_at is not null and not exists (select 1 from training_plans p where p.user_id = u.id)"
inv plans-without-one-active-inclusion "select /*inv:inclusion*/ count(*) from training_plans p where (select count(*) from program_inclusions i where i.training_plan_id = p.id and i.is_active) <> 1"
inv duplicate-legacy-copies "select /*inv:dups*/ count(*) from (select 1 from training_sessions where legacy_id is not null group by origin, legacy_id having count(*) > 1) d"
[ "$(dbq "select /*inv:plans*/ count(*) from training_plans")" = "$ONB" ] || die "invariant plans == onboarded ($ONB) violated"
log "invariant plans == onboarded ($ONB): OK"
[ "$(dbq "select version_num from alembic_version")" = "$HEADS" ] || die "alembic_version != head"
log "training_sessions by origin: $(dbq "select /*q:origins*/ coalesce(string_agg(coalesce(origin,'null')||'='||n, ' ' order by origin), '') from (select origin, count(*) n from training_sessions group by origin) s")"

# ------------------------------------------------------------------------------------------------ 10 start
if [ "$MODE" = "rehearse-check" ]; then
  phase 10 "rehearsal: start web only (bot never starts), healthcheck, stop web again"
  dc up -d --no-build web
  SERVICES="web"
else
  phase 10 "start app + web, healthcheck, verify the running build — DOWNTIME ENDS"
  mf start_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  dc up -d --no-build app web
  SERVICES="app web"
fi
deadline=$((SECONDS + HEALTH_TIMEOUT))
until bgwait curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; do
  [ "$SECONDS" -lt "$deadline" ] || die "healthcheck $HEALTH_URL did not pass within ${HEALTH_TIMEOUT}s"
  bgwait sleep 3
done
log "healthcheck OK: $HEALTH_URL"
for svc in $SERVICES; do
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

# ------------------------------------------------------------------------------------------------ 11 finish
phase 11 "finish (post-deploy-cleanup is NOT run: it would prune the rollback images)"
if [ "$MODE" = "rehearse-check" ]; then
  dc stop web
  mf rehearsal_ok_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  summary
  log "REHEARSAL OK sha=$SHA alembic=$HEADS onboarded=$ONB migrated=$WILL; app/web are STOPPED (rehearsal never leaves services running)"
  log "rehearse R3 next: $ROLLBACK_BIN R3 $MANIFEST check"
  exit 0
fi
mf deploy_ok_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# ротация: дампы ЭТОГО запуска + PROD_KEEP_BACKUPS предыдущих каждого вида; manifest-файлы не удаляются; только при полном успехе
for kind in prod-pre prod-prestop; do
  mapfile -t old_dumps < <(find "$BACKUP_DIR" -maxdepth 1 -name "$kind-*.dump" ! -name "$kind-$SHA7-$TS.dump" -printf '%T@ %p\n' | sort -rn | awk -v keep="$KEEP_BACKUPS" 'NR>keep{print $2}')
  for f in "${old_dumps[@]}"; do rm -f -- "$f" "$f.sha256"; log "rotated old backup $f"; done
done
summary
echo "rollback within the observation window (runbook §7; R3 loses everything written since $(sed -n 's/^backup_at=//p' "$MANIFEST")):"
echo "  R3: $ROLLBACK_BIN R3 $MANIFEST check   then   ... apply ROLLBACK-R3-$RUN_ID"
log "PRODUCTION GUARDED DEPLOY OK sha=$SHA alembic=$HEADS onboarded=$ONB migrated_now=$WILL services=started"
