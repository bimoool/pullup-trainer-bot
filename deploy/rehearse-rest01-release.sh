#!/usr/bin/env bash
# Репетиция выката REST01 (PR #342) на ИЗОЛИРОВАННОЙ копии production-БД. Один файл, без ручных шагов.
#
#   rehearse-rest01-release.sh <40-hex candidate sha>        # репетиция (по умолчанию с контрольным прогоном)
#   rehearse-rest01-release.sh cleanup                        # снести остатки репетиции (проект, тома, каталог)
#
# Что делает (docs/PRODUCTION_RUNBOOK.md §4, но без production-каталога/контейнеров/БД/портов):
#   1. клонирует публичный репозиторий в $BASE (НЕ из /root/pullup-trainer-bot), берёт из него прежний код (prod HEAD),
#      проверяет sha256 нового раннера (= установленного на сервере) и сохраняет прежний раннер для контроля;
#   2. поднимает отдельный compose-проект $PROJECT (свой том, свой порт 127.0.0.1:$WEB_PORT) и восстанавливает в него
#      КОПИЮ дампа $DUMP (файл читается, не меняется). Production-БД и её контейнер не открываются;
#   3. Telegram отключён трижды: фейковый BOT_TOKEN, api.telegram.org -> 127.0.0.1 в контейнерах, сервис app вообще не
#      запускается (контейнер только создаётся); режим rehearse-check не стартует бота никогда;
#   4. КОНТРОЛЬ (CONTROL=1): ПРЕЖНИЙ раннер на кандидате d1b2375 воспроизводит отказ фазы 8 и даёт построчный diff
#      plan_weeks/plan_items/program_inclusions — это и есть недостающий факт диагноза;
#   5. ЦЕЛЬ: на свежем восстановлении НОВЫЙ раннер (rehearse-check): verify-only до остановки и дважды после, все хэш-,
#      same_legacy-, dry-run-, plan-guard-контроли и инварианты; затем независимо от раннера — отпечаток всех таблиц
#      до/после (должен совпасть), собственный verify-only и подсчёт незавершённых legacy-занятий с неверным отдыхом.
#   6. по умолчанию удаляет копию данных (тома, дамп-копию, построчные выгрузки); сохраняет только отчёты без данных.
#
# Ничего не пишет в production: единственное обращение к проду — чтение файла дампа. Активные занятия не меняются
# (подсчёт идёт по копии). Рассылку не запускает.
set -euo pipefail

BASE="${REHEARSE_BASE:-/srv/rehearsal-rest01}"
REPO_URL="${REHEARSE_REPO_URL:-https://github.com/bimoool/pullup-trainer-bot.git}"
PROJECT="${REHEARSE_PROJECT:-pullup-rehearsal-rest01}"
DUMP="${REHEARSE_DUMP:-/root/backups/prod-pre-9fb76da-20261019T203942Z.dump}"
OLD_CODE_SHA="${REHEARSE_OLD_CODE_SHA:-bd80bc9d5cc3683aa6eccdbba182a8fe4d9571d2}"          # prod HEAD (preflight 2026-10-20)
CONTROL_SHA="${REHEARSE_CONTROL_SHA:-d1b237567d732d4d670232d8a060f9849c3132a8}"            # кандидат упавшего выката (дерево = 9fb76da)
NEW_RUNNER_SHA256="${REHEARSE_NEW_RUNNER_SHA256:-37d6c627e072aae7fbbdb8e07ba97c4b8a69087d627359a6f9aa90f94f6f656d}"
FROM_REV="${REHEARSE_FROM_REV:-b5d8e1f3a6c9}"
WEB_PORT="${REHEARSE_WEB_PORT:-18781}"
MIN_MEM_MB="${REHEARSE_MIN_MEM_MB:-700}"        # на старте; прод-раннер сам требует 400
ABORT_MEM_MB="${REHEARSE_ABORT_MEM_MB:-300}"    # сторож: ниже — немедленно снести репетицию, чтобы не задеть прод
MIN_DISK_MB="${REHEARSE_MIN_DISK_MB:-6144}"
CONTROL="${REHEARSE_CONTROL:-1}"
KEEP="${REHEARSE_KEEP:-0}"                       # 1 — не удалять копию данных после репетиции
CANON_PROD_DIR="/root/pullup-trainer-bot"; CANON_PROD_PROJECT="pullup-trainer-bot"

CLONE="$BASE/pullup-trainer-bot"; BIN="$BASE/bin"; REPORTS="$BASE/reports"; BACKUPS="$BASE/backups"; SQLD="$BASE/sql"; SNAP="$BASE/snap"
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { printf '[%s] REHEARSAL REFUSED/FAILED: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; exit 1; }
dc() { (cd "$CLONE" && docker compose -p "$PROJECT" "$@"); }
lowprio() { if command -v ionice >/dev/null 2>&1; then nice -n 19 ionice -c3 "$@"; else nice -n 19 "$@"; fi; }

# --------------------------------------------------------------------------------------------- cleanup
project_cleanup() {
  [ "$PROJECT" != "$CANON_PROD_PROJECT" ] || die "refusing to touch the production compose project"
  if [ -d "$CLONE" ]; then
    # одноразовые контейнеры раннера ЭТОГО проекта (метка guarded.run + проект репетиции); чужие/прод не трогаем
    local ids; ids="$(docker ps -aq --filter label=guarded.run --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true)"
    [ -z "$ids" ] || docker rm -f $ids >/dev/null 2>&1 || true
    dc down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  # образы репетиции (теги проекта и откатные теги раннера local/prod-*:pre-<sha7>-<ts> от ЭТОГО проекта не отличить по метке — не трогаем)
  docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^${PROJECT}-(app|web):" | xargs -r docker rmi >/dev/null 2>&1 || true
  # откатные теги local/prod-*:pre-*, созданные раннером ЭТОЙ репетиции (список «до» записан при старте)
  if [ -f "$BASE/.tags-before" ]; then
    docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^local/prod-(app|web):pre-' | sort | comm -13 "$BASE/.tags-before" - | xargs -r docker rmi >/dev/null 2>&1 || true
  fi
}
if [ "${1:-}" = "cleanup" ]; then
  [ "$BASE" != "$CANON_PROD_DIR" ] && [[ "$BASE" == /srv/rehearsal-* ]] || die "cleanup only for a /srv/rehearsal-* base (got $BASE)"
  project_cleanup; rm -rf -- "$CLONE" "$BIN" "$BACKUPS" "$SQLD" "$SNAP"; log "cleanup done (reports kept in $REPORTS)"; exit 0
fi

[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <40-hex candidate sha> | cleanup" >&2; exit 2; }
SHA="$1"; SHA7="${SHA:0:7}"; TS="$(date -u +%Y%m%dT%H%M%SZ)"

# --------------------------------------------------------------------------------------------- guards
[ "$(id -u)" = 0 ] || die "run as root (docker, /root/backups)"
[ "$(uname -s)" = Linux ] || die "Linux required"
for t in docker git curl python3 flock sha256sum free df awk nice; do command -v "$t" >/dev/null || die "$t is required"; done
docker compose version >/dev/null 2>&1 || die "docker compose is required"
[[ "$BASE" =~ ^/srv/rehearsal-[A-Za-z0-9._-]+$ ]] || die "REHEARSE_BASE must match /srv/rehearsal-<name> (got $BASE)"
[ "$PROJECT" != "$CANON_PROD_PROJECT" ] && [[ "$PROJECT" =~ ^pullup-rehearsal-[a-z0-9-]+$ ]] || die "REHEARSE_PROJECT must be pullup-rehearsal-<name>"
[[ "$WEB_PORT" =~ ^[0-9]{5}$ && "$WEB_PORT" -ge 18000 ]] || die "REHEARSE_WEB_PORT must be a 5-digit port >= 18000"
python3 -I -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1])))' "$WEB_PORT" 2>/dev/null || die "port $WEB_PORT on 127.0.0.1 is in use"
[ -f "$DUMP" ] && [ -s "$DUMP" ] || die "dump $DUMP not found"
[ -f "$DUMP.sha256" ] || die "$DUMP.sha256 not found (the guarded runner writes it next to every dump)"
sha256sum -c --quiet "$DUMP.sha256" || die "dump checksum does not verify"
existing="$(docker ps -a --format '{{.Label "com.docker.compose.project"}}' | grep -x "$PROJECT" || true)"
[ -z "$existing" ] || die "compose project $PROJECT already exists: run '$0 cleanup' first"
[ ! -e "$CLONE" ] || die "$CLONE already exists: run '$0 cleanup' first"
if pgrep -f 'deploy-production-guarded-run\.sh|rollback-production-guarded\.sh' >/dev/null 2>&1; then die "a production guarded run/rollback is active — never rehearse alongside it"; fi
mem="$(free -m | awk 'NR==2{print $7}')"; avail="$(df -Pm /srv | awk 'NR==2{print $4}')"
log "host: memory available ${mem} MB (need ${MIN_MEM_MB}), free disk on /srv ${avail} MB (need ${MIN_DISK_MB}), swap used $(free -m | awk 'NR==3{print $3}') MB"
[ "$mem" -ge "$MIN_MEM_MB" ] || die "available memory ${mem} MB < ${MIN_MEM_MB} MB: this host is too small to rehearse next to production. Run the same script on another Linux host with Docker (copy the dump and its .sha256 there; set REHEARSE_DUMP)"
[ "$avail" -ge "$MIN_DISK_MB" ] || die "free disk ${avail} MB < ${MIN_DISK_MB} MB"

mkdir -p "$BASE" "$BIN" "$REPORTS" "$BACKUPS" "$SQLD" "$SNAP"; chmod 700 "$BASE"
RUN_REPORT="$REPORTS/rehearsal-$SHA7-$TS"; mkdir -p "$RUN_REPORT"
docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^local/prod-(app|web):pre-' | sort > "$BASE/.tags-before" || true
exec > >(tee -a "$RUN_REPORT/rehearsal.log") 2>&1
log "REHEARSAL REST01 candidate=$SHA project=$PROJECT base=$BASE dump=$DUMP (read-only) control=$CONTROL"

MAIN_PID=$$
( while true; do
    m="$(free -m | awk 'NR==2{print $7}')"
    if [ "${m:-9999}" -lt "$ABORT_MEM_MB" ]; then echo "[watchdog] memory available ${m} MB < ${ABORT_MEM_MB} MB: aborting the rehearsal to protect production" >&2
      pkill -TERM -f "docker.*compose.* -p $PROJECT " 2>/dev/null || true
      docker ps -q --filter "label=com.docker.compose.project=$PROJECT" | xargs -r docker kill >/dev/null 2>&1 || true
      kill -TERM "$MAIN_PID" 2>/dev/null; exit 0; fi
    sleep 5
  done ) &
WATCHDOG=$!
finish() {
  rc=$?; kill "$WATCHDOG" 2>/dev/null || true
  if [ "$KEEP" = 1 ]; then log "REHEARSE_KEEP=1: data copy kept ($PROJECT, $BASE); remove with: $0 cleanup"
  else
    log "removing the data copy (compose project volumes, dump copy, row-level exports)"
    project_cleanup || true; rm -rf -- "$CLONE" "$SNAP" "$BACKUPS" "$SQLD" 2>/dev/null || true
  fi
  [ "$rc" = 0 ] && log "RESULT: rehearsal passed. Report: $RUN_REPORT" || log "RESULT: rehearsal FAILED (exit $rc). Report/logs: $RUN_REPORT"
  exit "$rc"
}
trap finish EXIT
trap 'exit 143' TERM INT

# --------------------------------------------------------------------------------------------- 1 code and runners
log "== [1] clone (public repo, not the production directory) and pin the tools"
git clone --quiet "$REPO_URL" "$CLONE"
cd "$CLONE"
for ref in "$SHA" "$OLD_CODE_SHA" "$CONTROL_SHA"; do
  git cat-file -e "${ref}^{commit}" 2>/dev/null || git fetch --quiet origin "$ref" || die "cannot fetch $ref from $REPO_URL (is the PR branch pushed?)"
  git cat-file -e "${ref}^{commit}" || die "$ref is not available"
done
git merge-base --is-ancestor 628144fa5457c41512db41af214c97a085fcb4b6 "$SHA" || die "candidate does not contain 628144f"
git show "$SHA:deploy/deploy-production-guarded-run.sh" > "$BIN/runner-new.sh"
got="$(sha256sum "$BIN/runner-new.sh" | awk '{print $1}')"
[ "$got" = "$NEW_RUNNER_SHA256" ] || die "runner of $SHA has sha256 $got, expected $NEW_RUNNER_SHA256 (the installed one)"
git show "$CONTROL_SHA:deploy/deploy-production-guarded-run.sh" > "$BIN/runner-old.sh"
git show "$SHA:deploy/rollback-production-guarded.sh" > "$BIN/rollback-production-guarded.sh"
chmod 700 "$BIN"/*.sh
log "new runner sha256 $got == installed; old (control) runner sha256 $(sha256sum "$BIN/runner-old.sh" | awk '{print $1}')"
git show "$SHA:scripts/backfill_multi_program.py" > "$BIN/backfill.py.check"; grep -q -- '--verify-only' "$BIN/backfill.py.check" || die "candidate has no --verify-only"; rm -f "$BIN/backfill.py.check"

# --------------------------------------------------------------------------------------------- 2 isolated environment
log "== [2] isolated environment: own project, own volume, port 127.0.0.1:$WEB_PORT, Telegram disabled"
PGPW="$(python3 -I -c 'import secrets; print(secrets.token_hex(12))')"
cat > .env <<ENV
BOT_TOKEN=0:rehearsal-disabled-not-a-real-token
POSTGRES_USER=pullup
POSTGRES_PASSWORD=$PGPW
POSTGRES_DB=pullup
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://pullup:$PGPW@db:5432/pullup
REDIS_URL=redis://redis:6379/0
LOG_LEVEL=INFO
ADMIN_IDS=
MINI_APP_URL=https://rehearsal.invalid
MINI_APP_PORT=$WEB_PORT
ROBOKASSA_MERCHANT_LOGIN=
ROBOKASSA_PASSWORD_1=
ROBOKASSA_PASSWORD_2=
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_CREDENTIALS_PATH=
GITHUB_TOKEN=
ENV
chmod 600 .env
cat > docker-compose.override.yml <<'YML'
services:
  app:
    restart: "no"
    extra_hosts: ["api.telegram.org:127.0.0.1"]
  web:
    restart: "no"
    extra_hosts: ["api.telegram.org:127.0.0.1"]
YML
mkdir -p secrets
printf '.env\ndocker-compose.override.yml\nsecrets/\n' >> .git/info/exclude
CF="$CLONE/docker-compose.yml,$CLONE/docker-compose.override.yml"

mkdir -p "$SQLD"
cat > "$SQLD/fingerprint.sql" <<'SQL'
select format('select %L||''|''||count(*)||''|''||coalesce(md5(string_agg(md5(t::text), '''' order by md5(t::text))),''-'') from %I t', tablename, tablename)
from pg_tables where schemaname = 'public' order by tablename
\gexec
SQL
cat > "$SQLD/active_wrong_rest.sql" <<'SQL'
-- Незавершённые (status = started) нативные занятия legacy STEP-курса (не V5.6) и их отдых; блок 0 = А, блок 1 = Б.
create temp view rest_scan as
select s.id as session_id, s.user_id, coalesce(s.engine_version, 1) as engine_version, s.engine_status,
       (s.engine_plan->'blocks'->0->'sets'->0->>'rest_after_seconds')::int as a_rest,
       (s.engine_plan->'blocks'->1->'sets'->0->>'rest_after_seconds')::int as b_rest,
       (s.engine_plan->'blocks'->0->>'rest_after_block_seconds')::int as gap,
       coalesce(nullif(u.rest_seconds_block_a, 0), 240) as exp_a,
       coalesce(nullif(u.rest_seconds_block_b, 0), 180) as exp_b,
       coalesce(nullif(u.big_break_seconds, 0), 900) as exp_gap,
       (select count(*) from set_logs l join session_blocks b on b.id = l.session_block_id where b.session_id = s.id) as logged_sets
from training_sessions s
join program_inclusions pi on pi.id = s.program_inclusion_id
join users u on u.id = s.user_id
where s.origin = 'native' and s.status = 'started'
  and pi.snapshot->>'progression_strategy_type' = 'step'
  and coalesce(pi.progression_state->>'program_version', '') <> 'pullups_v5_6';
select 'active_legacy_step_sessions|' || count(*) from rest_scan
union all select 'engine_v2_active|' || count(*) from rest_scan where engine_version = 2 and engine_status = 'active'
union all select 'engine_v1_started_not_engine_plan_based|' || count(*) from rest_scan where engine_version = 1
union all select 'engine_v2_active_with_generic_90|' || count(*) from rest_scan where engine_version = 2 and engine_status = 'active' and (a_rest = 90 or b_rest = 90)
union all select 'engine_v2_active_wrong_vs_expected|' || count(*) from rest_scan
  where engine_version = 2 and engine_status = 'active' and (a_rest is distinct from exp_a or b_rest is distinct from exp_b or gap is distinct from exp_gap)
union all select 'distinct_users_wrong|' || count(distinct user_id) from rest_scan
  where engine_version = 2 and engine_status = 'active' and (a_rest is distinct from exp_a or b_rest is distinct from exp_b or gap is distinct from exp_gap)
union all select 'wrong_with_logged_sets_to_preserve|' || count(*) from rest_scan
  where engine_version = 2 and engine_status = 'active' and logged_sets > 0 and (a_rest is distinct from exp_a or b_rest is distinct from exp_b or gap is distinct from exp_gap);
\echo ---- ids (session_id,user_id,engine_version,a_rest,b_rest,gap,exp_a,exp_b,exp_gap,logged_sets)
select session_id || ',' || user_id || ',' || engine_version || ',' || coalesce(a_rest::text, '-') || ',' || coalesce(b_rest::text, '-') || ',' || coalesce(gap::text, '-')
       || ',' || exp_a || ',' || exp_b || ',' || exp_gap || ',' || logged_sets
from rest_scan order by session_id;
SQL
cat > "$SNAP/diff_rows.py" <<'PY'
import json, sys
before, after, out = sys.argv[1:4]
def load(p):
    rows = {}
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            r = json.loads(line); rows[r["id"]] = r
    return rows
b, a = load(before), load(after)
added = sorted(set(a) - set(b)); removed = sorted(set(b) - set(a))
changed = {}
for i in sorted(set(a) & set(b)):
    cols = [c for c in a[i] if a[i].get(c) != b[i].get(c)]
    if cols: changed[i] = cols
colcount = {}
for cols in changed.values():
    for c in cols: colcount[c] = colcount.get(c, 0) + 1
print(f"rows before={len(b)} after={len(a)} added={len(added)} removed={len(removed)} changed={len(changed)}")
print("changed columns:", json.dumps(colcount, sort_keys=True))
with open(out, "w", encoding="utf-8") as f:
    f.write(f"added ids: {added[:200]}\nremoved ids: {removed[:200]}\n")
    for i, cols in list(changed.items())[:200]:
        for c in cols:
            f.write(f"changed id={i} col={c}: {str(b[i].get(c))[:160]!r} -> {str(a[i].get(c))[:160]!r}\n")
PY

psql_db() { dc exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1' ; }

# --------------------------------------------------------------------------------------------- state helpers
prepare_state() { # прежний код (prod HEAD) + восстановленная копия дампа; app/web только СОЗДАНЫ (бот и Telegram не стартуют)
  log "-- prepare: prior code $OLD_CODE_SHA (prod HEAD), restored copy of the dump"
  git checkout --quiet --detach "$OLD_CODE_SHA"
  COMPOSE_PARALLEL_LIMIT=1 lowprio docker compose -p "$PROJECT" build app web
  dc up -d db redis
  local i; for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q db)" 2>/dev/null || true)" = healthy ] && break; sleep 2; done
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q db)")" = healthy ] || die "rehearsal db did not become healthy"
  [ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$(dc ps -q db)")" = "$PROJECT" ] || die "db container is not in the rehearsal project"
  cp -- "$DUMP" "$BACKUPS/dump-copy.dump"
  docker cp "$BACKUPS/dump-copy.dump" "$(dc ps -q db):/tmp/prod-copy.dump"
  dc exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error /tmp/prod-copy.dump && rm -f /tmp/prod-copy.dump'
  local rev; rev="$(echo "select version_num from alembic_version" | psql_db)"
  [ "$rev" = "$FROM_REV" ] || die "restored alembic_version is $rev, expected $FROM_REV"
  dc create app web
  local label; label="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$(dc ps -q db)")"
  if [ "$label" != "$CF" ]; then
    case ",$label," in *",$CLONE/docker-compose.yml,"*) ;; *) die "unexpected compose config_files label '$label'" ;; esac
    case ",$label," in *",$CLONE/docker-compose.override.yml,"*) ;; *) die "unexpected compose config_files label '$label'" ;; esac
    log "compose config_files label is '$label' (same two files, different order/format): using it for the runner check"; CF="$label"
  fi
  log "restored: alembic=$rev users/onboarded/workouts/electives/subscriptions = $(echo "select (select count(*) from users)||'/'||(select count(*) from users where onboarding_completed_at is not null)||'/'||(select count(*) from workouts)||'/'||(select count(*) from elective_workouts)||'/'||(select count(*) from subscriptions)" | psql_db)"
}
snapshot() { # <label>: отпечатки ВСЕХ таблиц + построчные выгрузки трёх таблиц календаря (удаляются вместе с копией)
  psql_db < "$SQLD/fingerprint.sql" > "$SNAP/fp_$1.txt"
  local t; for t in plan_weeks plan_items program_inclusions; do
    echo "select row_to_json(t)::text from $t t order by id" | psql_db > "$SNAP/${t}_$1.jsonl"
  done
  log "snapshot $1: $(wc -l < "$SNAP/fp_$1.txt") tables fingerprinted"
}
run_runner() { # <runner> <candidate sha> <logfile>; возвращает код выхода раннера
  local rc=0
  ( cd "$CLONE" && PROD_DIR="$CLONE" PROD_PROJECT="$PROJECT" PROD_BACKUP_DIR="$BACKUPS" PROD_COMPOSE_FILES="$CF" \
      PROD_EXPECTED_FROM_REV="$FROM_REV" PROD_EXPECTED_TO_REV="$FROM_REV" PROD_HEALTH_TIMEOUT=360 PROD_MIN_MEM_MB=400 \
      COMPOSE_PARALLEL_LIMIT=1 lowprio "$1" "$2" rehearse-check ) > "$3" 2>&1 || rc=$?
  return "$rc"
}

# --------------------------------------------------------------------------------------------- 3 control run (old runner)
CONTROL_RESULT="skipped"
if [ "$CONTROL" = 1 ]; then
  log "== [3] CONTROL: the previous runner on the failed candidate must reproduce the phase-8 abort"
  prepare_state; snapshot control-before
  rc=0; run_runner "$BIN/runner-old.sh" "$CONTROL_SHA" "$RUN_REPORT/control-runner.log" || rc=$?
  snapshot control-after
  if [ "$rc" != 0 ] && grep -q 'pre-existing (legacy) data changed after-backfill' "$RUN_REPORT/control-runner.log"; then
    CONTROL_RESULT="reproduced: $(grep -o 'pre-existing (legacy) data changed after-backfill: tables [a-z_ ]*' "$RUN_REPORT/control-runner.log" | head -1 || true)"
    log "control reproduced the production failure: $CONTROL_RESULT"
    for t in plan_weeks plan_items program_inclusions; do
      log "row diff $t: $(python3 -I "$SNAP/diff_rows.py" "$SNAP/${t}_control-before.jsonl" "$SNAP/${t}_control-after.jsonl" "$RUN_REPORT/rowdiff-$t.txt" | tr '\n' ' ')"
    done
  elif [ "$rc" = 0 ]; then
    CONTROL_RESULT="NOT reproduced: the previous runner passed on this copy (calendar did not move) — root cause stays a hypothesis"
    log "WARNING: $CONTROL_RESULT"
  else
    die "control run failed for a different reason (see $RUN_REPORT/control-runner.log): $(grep -m1 -E 'FAILED at phase|REFUSED|ERROR' "$RUN_REPORT/control-runner.log" || echo unknown)"
  fi
  project_cleanup_state() { dc down -v --remove-orphans >/dev/null 2>&1 || true; }
  ids="$(docker ps -aq --filter label=guarded.run --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true)"; [ -z "$ids" ] || docker rm -f $ids >/dev/null
  project_cleanup_state
fi

# --------------------------------------------------------------------------------------------- 4 target run (new runner)
log "== [4] TARGET: fresh restore, the NEW runner on the candidate $SHA"
prepare_state; snapshot before
rc=0; run_runner "$BIN/runner-new.sh" "$SHA" "$RUN_REPORT/target-runner.log" || rc=$?
tail -n 12 "$RUN_REPORT/target-runner.log" | sed 's/^/    runner| /'
[ "$rc" = 0 ] || die "new runner failed (exit $rc): see $RUN_REPORT/target-runner.log"
grep -q 'existing migration coverage verified read-only before stopping writers' "$RUN_REPORT/target-runner.log" || die "verify-only pre-stop step did not run"
grep -q 'already-migrated database verified without applying backfill/calendar convergence' "$RUN_REPORT/target-runner.log" || die "verify-only branch was not taken"
grep -q 'REHEARSAL OK' "$RUN_REPORT/target-runner.log" || die "runner did not report REHEARSAL OK"
! grep -q 'backfill apply took' "$RUN_REPORT/target-runner.log" || die "backfill apply ran in the verify-only path"
log "runner: verify-only path taken, no backfill apply, REHEARSAL OK"

snapshot after
if diff -u "$SNAP/fp_before.txt" "$SNAP/fp_after.txt" > "$RUN_REPORT/fingerprint.diff"; then
  log "DATA UNCHANGED: all $(wc -l < "$SNAP/fp_before.txt") public tables identical (row count + md5 of every row) before/after the rehearsed release"
else
  cat "$RUN_REPORT/fingerprint.diff"; die "table fingerprints differ after the release (see $RUN_REPORT/fingerprint.diff)"
fi
for t in plan_weeks plan_items program_inclusions; do
  cmp -s "$SNAP/${t}_before.jsonl" "$SNAP/${t}_after.jsonl" || die "$t changed during the verify-only release"
done
log "plan_weeks / plan_items / program_inclusions identical row by row"

log "== [5] independent verify-only against the rehearsal DB with the candidate image"
git checkout --quiet --detach "$SHA"
vrc=0; (cd "$CLONE" && docker compose -p "$PROJECT" run --rm -T app python scripts/backfill_multi_program.py --verify-only) > "$RUN_REPORT/verify-only-independent.txt" 2>&1 || vrc=$?
[ "$vrc" = 0 ] || die "independent verify-only failed (exit $vrc): $(tail -n 3 "$RUN_REPORT/verify-only-independent.txt")"
python3 -I - "$RUN_REPORT/verify-only-independent.txt" <<'PY' || die "independent verify-only result is not verified"
import json, sys
rows = [l[len("RESULT-JSON "):] for l in open(sys.argv[1], encoding="utf-8") if l.startswith("RESULT-JSON ")]
assert len(rows) == 1, "expected exactly one RESULT-JSON"
d = json.loads(rows[0]); assert d["mode"] == "verify-only" and d["verified"] is True and d["errors"] == [], d
print("independent verify-only:", json.dumps(d, sort_keys=True))
PY
snapshot after-verify
cmp -s "$SNAP/fp_after.txt" "$SNAP/fp_after-verify.txt" || die "independent verify-only changed the database"
log "independent verify-only: verified, database unchanged"

log "== [6] unfinished legacy sessions with wrong rest (COPY of the dump: state at $(basename "$DUMP"), NOT live production)"
psql_db < "$SQLD/active_wrong_rest.sql" > "$RUN_REPORT/active-wrong-rest.txt"
sed -n '1,/^---- ids/p' "$RUN_REPORT/active-wrong-rest.txt" | grep -v '^---- ids' | sed 's/|/ = /; s/^/    /'
log "per-session list (ids only): $RUN_REPORT/active-wrong-rest.txt — sessions are NOT modified"

{
  echo "REHEARSAL REST01 SUMMARY ($TS)"
  echo "candidate: $SHA"
  echo "dump (read-only copy): $(basename "$DUMP") sha256 $(awk '{print $1}' "$DUMP.sha256")"
  echo "control (previous runner on d1b2375): $CONTROL_RESULT"
  echo "target (new runner): REHEARSAL OK, verify-only path, no backfill apply"
  echo "data unchanged: all public tables identical before/after; calendar tables identical row by row"
  echo "independent verify-only: verified"
} > "$RUN_REPORT/SUMMARY.txt"
cat "$RUN_REPORT/SUMMARY.txt"
log "REHEARSAL PASSED for $SHA. This is NOT permission to apply: apply stays a separate explicit step."
