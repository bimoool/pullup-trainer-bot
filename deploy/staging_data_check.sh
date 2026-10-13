#!/usr/bin/env bash
# Проверки данных staging-выката (docs/STAGING_RC_RUNBOOK.md §6). Вызывается deploy-staging-guarded-run.sh; ничего не пишет в БД.
#
#   staging_data_check.sh before            <workdir> <gen_hash_queries.sql>   # снимок ДО миграции (писатели остановлены)
#   staging_data_check.sh after-migration   <workdir> <allowed-diff-file>      # ожидаемые преобразования 7 миграций
#   staging_data_check.sh same-as-migration <workdir>                          # dry-run convergence ничего не записал
#   staging_data_check.sh hold-check                                           # риск дублей факультативов (HOLD §6.2)
#   staging_data_check.sh after-convergence <workdir>                          # инварианты после --apply
#
# Окружение: STAGING_PSQL — команда, читающая SQL со stdin и печатающая невыравненные строки (psql -At), например
#   docker exec -i <db-container> sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At'
# Выход 0 — проверка пройдена; иначе ненулевой, причина в stderr. Значения персональных данных не печатаются (id, имена таблиц, хэши).
set -euo pipefail

: "${STAGING_PSQL:?STAGING_PSQL is required}"
cmd="${1:?subcommand}"
shift || true

q()  { bash -c "$STAGING_PSQL" <<<"$1"; }
qf() { bash -c "$STAGING_PSQL" < "$1"; }
fail() { echo "DATA-CHECK FAILED: $*" >&2; exit 1; }

# Таблицы, данные которых при convergence меняться МОГУТ (остальные ДО-таблицы обязаны остаться идентичными).
CONVERGENCE_MAY_CHANGE="plan_items plan_weeks program_inclusions session_blocks set_logs training_sessions"
# Таблицы, где convergence только ДОБАВЛЯЕТ строки: у ранее существовавших строк ДО-колонки не меняются.
APPEND_ONLY="training_sessions session_blocks set_logs"

hash_join() { # <before> <after> -> строки "tbl|n_before|h_before|n_after|h_after" для таблиц, присутствующих в обоих
  join -t'|' -j1 <(sort "$1") <(sort "$2")
}

case "$cmd" in
before)
  w="${1:?workdir}"; gen="${2:?gen_hash_queries.sql}"
  mkdir -p "$w"
  qf "$gen" > "$w/hash_queries.sql"
  [ -s "$w/hash_queries.sql" ] || fail "generated hash_queries.sql is empty"
  qf "$w/hash_queries.sql" > "$w/hq_before.txt"
  [ "$(wc -l < "$w/hq_before.txt")" -eq "$(wc -l < "$w/hash_queries.sql")" ] || fail "hash query count mismatch (before)"
  q "select id||'|'||coalesce(jsonb_typeof(progression_state->'block_b'),'none')||'|'||coalesce((progression_state->'block_b'->'work_sets')::text,'ABSENT') from program_inclusions order by id" > "$w/work_sets_before.txt"
  q "select coalesce(md5(string_agg(id::text||'|'||(progression_state #- '{block_b,work_sets}')::text, ',' order by id)),'') from program_inclusions" > "$w/state_wo_ws.before"
  q "select coalesce(md5(string_agg(row(id,training_plan_id,program_id,snapshot,started_at,expires_at,is_active,created_at,initial_progression_state)::text, '|' order by id)),'') from program_inclusions" > "$w/inclusion_other.before"
  for t in $APPEND_ONLY; do q "select coalesce(max(id),0) from $t" > "$w/max_id.$t"; done
  echo "before: $(wc -l < "$w/hq_before.txt") tables hashed, $(wc -l < "$w/work_sets_before.txt") inclusions recorded"
  ;;

after-migration)
  w="${1:?workdir}"; allow="${2:?allowed-diff file}"
  qf "$w/hash_queries.sql" > "$w/hq_after.txt"
  [ "$(wc -l < "$w/hq_after.txt")" -eq "$(wc -l < "$w/hq_before.txt")" ] || fail "number of hashed tables changed (a pre-existing table disappeared?)"
  hash_join "$w/hq_before.txt" "$w/hq_after.txt" > "$w/hq_joined.txt"
  [ "$(wc -l < "$w/hq_joined.txt")" -eq "$(wc -l < "$w/hq_before.txt")" ] || fail "table set differs between before and after"
  count_changed=$(awk -F'|' '$2!=$4{print $1" ("$2"->"$4")"}' "$w/hq_joined.txt")
  [ -z "$count_changed" ] || fail "row counts of pre-existing tables changed by the migrations: $count_changed"
  changed=$(awk -F'|' '$3!=$5{print $1}' "$w/hq_joined.txt" | sort)
  allowed=$(grep -vE '^\s*(#|$)' "$allow" | sort)
  unexpected=$(comm -23 <(printf '%s\n' "$changed" | sed '/^$/d') <(printf '%s\n' "$allowed" | sed '/^$/d'))
  [ -z "$unexpected" ] || fail "pre-existing data changed in tables outside the allowed list ($allow): $(echo $unexpected)"
  echo "after-migration: changed tables = [$(echo $changed)] (allowed: [$(echo $allowed)])"
  # e3b9c5d7a2f1: block_b.work_sets absent/null -> 4, всё остальное не меняется
  left=$(q "select count(*) from program_inclusions where jsonb_typeof(progression_state->'block_b')='object' and coalesce(jsonb_typeof(progression_state->'block_b'->'work_sets'),'null')='null'")
  [ "$left" = "0" ] || fail "$left inclusion(s) still have block_b without a numeric work_sets"
  [ "$(q "select coalesce(md5(string_agg(id::text||'|'||(progression_state #- '{block_b,work_sets}')::text, ',' order by id)),'') from program_inclusions")" = "$(cat "$w/state_wo_ws.before")" ] \
    || fail "progression_state changed outside block_b.work_sets"
  [ "$(q "select coalesce(md5(string_agg(row(id,training_plan_id,program_id,snapshot,started_at,expires_at,is_active,created_at,initial_progression_state)::text, '|' order by id)),'') from program_inclusions")" = "$(cat "$w/inclusion_other.before")" ] \
    || fail "program_inclusions columns other than progression_state changed"
  q "select id||'|'||coalesce(jsonb_typeof(progression_state->'block_b'),'none')||'|'||coalesce((progression_state->'block_b'->'work_sets')::text,'ABSENT') from program_inclusions order by id" > "$w/work_sets_after.txt"
  awk -F'|' 'NR==FNR{bt[$1]=$2; bw[$1]=$3; next}
    { id=$1; if(!(id in bt)){print "new inclusion row "id; bad=1; next}
      if($2!=bt[id]){print "id "id": block_b type "bt[id]" -> "$2; bad=1}
      e=(bt[id]=="object" && (bw[id]=="ABSENT"||bw[id]=="null")) ? "4" : bw[id];
      if($3!=e){print "id "id": work_sets before="bw[id]" after="$3" expected="e; bad=1} }
    END{exit bad}' "$w/work_sets_before.txt" "$w/work_sets_after.txt" >&2 || fail "work_sets rule (absent/null -> 4, existing values kept) violated"
  bad_origin=$(q "select distinct origin from training_sessions where origin is not null and origin not in ('native','legacy_backfill','legacy_elective')")
  [ -z "$bad_origin" ] || fail "unexpected training_sessions.origin values: $bad_origin"
  echo "after-migration: OK (work_sets rule holds; no other pre-existing data changed)"
  ;;

same-as-migration)
  w="${1:?workdir}"
  qf "$w/hash_queries.sql" > "$w/hq_dry.txt"
  diff -q <(sort "$w/hq_after.txt") <(sort "$w/hq_dry.txt") >/dev/null || fail "database changed during dry-run convergence"
  echo "same-as-migration: OK (dry-run wrote nothing)"
  ;;

hold-check)
  n=$(q "select count(*) from elective_workouts e join training_plans tp on tp.user_id = e.user_id where e.created_at >= tp.created_at and exists (select 1 from training_sessions ts where ts.user_id = e.user_id and ts.origin = 'legacy_elective' and ts.legacy_id is null)")
  [ "$n" = "0" ] || fail "HOLD: $n elective(s) not older than their plan have an unkeyed legacy_elective copy (duplicate/resurrection risk)"
  echo "hold-check: OK (0 risky electives)"
  ;;

after-convergence)
  w="${1:?workdir}"
  qf "$w/hash_queries.sql" > "$w/hq_conv.txt"
  hash_join "$w/hq_before.txt" "$w/hq_conv.txt" > "$w/hq_joined_conv.txt"
  [ "$(wc -l < "$w/hq_joined_conv.txt")" -eq "$(wc -l < "$w/hq_before.txt")" ] || fail "table set differs after convergence"
  changed=$(awk -F'|' '$2!=$4 || $3!=$5{print $1}' "$w/hq_joined_conv.txt" | sort | sed '/^$/d')
  unexpected=$(comm -23 <(printf '%s\n' "$changed") <(printf '%s\n' $CONVERGENCE_MAY_CHANGE | sort))
  [ -z "$unexpected" ] || fail "convergence changed tables it must not touch: $(echo $unexpected)"
  for t in $APPEND_ONLY; do
    max=$(cat "$w/max_id.$t")
    line=$(grep -E "^select '$t' as tbl," "$w/hash_queries.sql") || fail "no hash query for $t"
    restricted=$(printf '%s' "$line" | sed -E "s/ from $t;\$/ from $t where id <= $max;/")
    [ "$restricted" != "$line" ] || fail "cannot restrict hash query for $t"
    got=$(q "$restricted")
    want=$(grep -E "^$t\|" "$w/hq_before.txt")
    [ "$got" = "$want" ] || fail "pre-existing $t rows changed by convergence (restricted hash differs): got=$got want=$want"
  done
  dups=$(q "select origin||':'||legacy_id||' x'||count(*) from training_sessions where legacy_id is not null group by origin, legacy_id having count(*) > 1")
  [ -z "$dups" ] || fail "duplicate (origin, legacy_id) copies: $dups"
  echo "after-convergence: OK (changed tables = [$(echo $changed)]; pre-existing rows of $APPEND_ONLY unchanged; no duplicate copies)"
  ;;

*) echo "unknown subcommand: $cmd" >&2; exit 2 ;;
esac
