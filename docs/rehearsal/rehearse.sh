#!/bin/bash
# usage: docs/rehearsal/rehearse.sh <source_db> <tag>   (source_db = frozen COPY of the old staging DB; never modified)
# Isolated Postgres only (host/port below). NEVER point this at staging or prod. Output (json digests, logs): $REHEARSAL_OUT
set -u
SRC=$1; TAG=$2
ROOT=$(cd "$(dirname "$0")/../.." && pwd); S=$ROOT/docs/rehearsal; OUT=${REHEARSAL_OUT:-/tmp/rehearsal}
R=$OUT/reh_$TAG; mkdir -p $R
cd $ROOT
export BOT_TOKEN=x PYTHONPATH=.   # venv with ".[dev,web]" + asyncpg must be active
H="-h 127.0.0.1 -p 54329 -U pullup"; DB=reh_$TAG
psql $H -d postgres -qc "drop database if exists $DB with (force)" -c "create database $DB template $SRC"
export DATABASE_URL=postgresql+asyncpg://pullup@127.0.0.1:54329/$DB
PLAIN=postgresql://pullup@127.0.0.1:54329/$DB
snap() { python $S/dbsnap.py snap $PLAIN $R/$1.json | sed 's/.*snap [^:]*: /  /'; }
echo "== [$TAG] source rev: $(psql $H -d $SRC -Atc 'select version_num from alembic_version')"
snap before
alembic upgrade head > $R/upgrade.log 2>&1; echo "upgrade exit=$? -> $(alembic current 2>/dev/null | tail -n1)"; snap after_upgrade
# Запись сведения — только по явному списку users.id (CLI отклоняет --all --apply и --converge-history --apply без списка).
# В репетиции «подтверждены» все пользователи синтетической копии; USERS_SCOPE=1,2,3 сужает область (проверка изоляции).
PLAN_IDS=${USERS_SCOPE:-$(psql $H -d $DB -Atc "select string_agg(user_id::text, ',' order by user_id) from training_plans")}
ALL_IDS=${USERS_SCOPE:-$(psql $H -d $DB -Atc "select string_agg(id::text, ',' order by id) from users")}
python scripts/repair_plan_convergence.py --all > $R/conv_all_dry.json 2>/dev/null; echo "conv discovery (--all, read-only) exit=$?"
python scripts/repair_plan_convergence.py --user-ids $PLAN_IDS > $R/conv_dry.json 2>/dev/null; echo "conv dry exit=$?"; snap after_convdry
python scripts/repair_plan_convergence.py --user-ids $PLAN_IDS --apply > $R/conv_a1.json 2>/dev/null; echo "conv apply1 exit=$?"
python scripts/repair_plan_convergence.py --user-ids $PLAN_IDS --apply > $R/conv_a2.json 2>/dev/null; echo "conv apply2 exit=$?"; snap after_conv
python scripts/backfill_multi_program.py --converge-history > $R/hist_all_dry.out 2>&1; echo "hist discovery (all users, read-only) exit=$?"
python scripts/backfill_multi_program.py --converge-history --user-ids $ALL_IDS > $R/hist_dry.out 2>&1; echo "hist dry exit=$?"; snap after_histdry
python scripts/backfill_multi_program.py --converge-history --user-ids $ALL_IDS --apply > $R/hist_a1.out 2>&1; echo "hist apply1 exit=$?"
python scripts/backfill_multi_program.py --converge-history --user-ids $ALL_IDS --apply > $R/hist_a2.out 2>&1; echo "hist apply2 exit=$?"; snap after
echo "-- unresolved (apply1 / apply2 must match):"; sed -n '/^Не разрешено/,$p' $R/hist_a1.out | cut -c1-160; diff <(sed -n '/^Не разрешено/,$p' $R/hist_a1.out) <(sed -n '/^Не разрешено/,$p' $R/hist_a2.out) > /dev/null && echo "   stable" || echo "   UNSTABLE"
python - <<PY
import json
for n in ['conv_dry','conv_a1','conv_a2']:
    d=json.load(open('$R/'+n+'.json')); print(' ',n,d['mode'],'mutations=',d['total_mutations'],'guard_violations=',sum(1 for u in d['users_detail'] if u['guard_violations']))
PY
echo "-- dry-run wrote nothing? conv:"; python $S/dbsnap.py diff $R/after_upgrade.json $R/after_convdry.json | tail -n +2; echo "   hist:"; python $S/dbsnap.py diff $R/after_conv.json $R/after_histdry.json | tail -n +2
echo "-- hist apply2:"; sed '/^Не разрешено/,$d' $R/hist_a2.out | grep -E "создано|привязано|обновлено|замещено" | head
echo "-- FULL DIFF before -> after"; python $S/dbsnap.py diff $R/before.json $R/after.json
