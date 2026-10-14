#!/bin/bash
# Весь прогон «отредактированная копия факультатива»: старый код строит и правит, новый код мигрирует/сводит, сравнение.
# usage: docs/rehearsal/edited_copy_run.sh <OLD_CHECKOUT (develop/current | 4298f8b)> [edit|delete-all]   (изолированный Postgres 54329; venv активен)
# edit (по умолчанию) — §8: правка E1/E2, удаление E4; delete-all — старое API удаляет ВСЕ копии факультативов.
set -u
OLD=$1; MODE=${2:-edit}; ROOT=$(cd "$(dirname "$0")/../.." && pwd); R=$ROOT/docs/rehearsal; OUT=${REHEARSAL_OUT:-/tmp/rehearsal}; mkdir -p $OUT
H="-h 127.0.0.1 -p 54329 -U pullup"; DSN=postgresql://pullup@127.0.0.1:54329
stop_port() { local pid; pid=$(ps -eo pid,args | grep "uvicorn app.web.main:app --port $1" | grep -v grep | awk '{print $1}' | head -n1); [ -n "$pid" ] && kill $pid; sleep 2; }
api() { # api <checkout> <db> <port> <token>
  (cd $1; PYTHONPATH=$1 BOT_TOKEN=$4 ADMIN_IDS=900010 DATABASE_URL=postgresql+asyncpg://pullup@127.0.0.1:54329/$2 nohup uvicorn app.web.main:app --port $3 > $OUT/api_$3.log 2>&1 &)
  for i in $(seq 1 40); do curl -sf http://127.0.0.1:$3/health >/dev/null && return; sleep 1; done; echo "api $3 did not start"; }
echo "### 1. fixture (OLD code, its own Alembic head)"
psql $H -d postgres -qc "drop database if exists fx_edit with (force)" -c "create database fx_edit" 2>&1 | grep -v NOTICE
(cd $OLD; export PYTHONPATH=$OLD BOT_TOKEN=x ADMIN_IDS=900010 DATABASE_URL=postgresql+asyncpg://pullup@127.0.0.1:54329/fx_edit; alembic upgrade head >/dev/null 2>&1; python $R/edited_copy_fixture.py | grep fixture) || { echo 'FIXTURE FAILED'; exit 1; }
echo "### 2. OLD API: baseline, then user edits (PATCH value, PATCH date, DELETE copy)"
api $OLD fx_edit 8021 fx-token
python $R/edited_copy_api.py http://127.0.0.1:8021 fx-token summary $OUT/fx_0_before_edit.json >/dev/null
python $R/edited_copy_api.py http://127.0.0.1:8021 fx-token $MODE $DSN/fx_edit
psql $H -d fx_edit -At -c "select 'plans after old API: ' || count(*) from training_plans tp join users u on u.id=tp.user_id where u.telegram_id in (770001,770002)"
python $R/edited_copy_api.py http://127.0.0.1:8021 fx-token summary $OUT/fx_1_old_after_edit.json >/dev/null
stop_port 8021
echo "### 3. NEW code: upgrade + convergence (rehearse.sh)"
REHEARSAL_OUT=$OUT bash $R/rehearse.sh fx_edit fx 2>&1 | grep -E "upgrade exit|conv_|hist .* exit|^   hist|dry-run wrote"
echo "--- history convergence reports"; for f in hist_dry hist_a1 hist_a2; do echo "[$f]"; grep -E "привязано|создано|без изменений|без пары|воскрешены|ambiguous" $OUT/reh_fx/$f.out; done
echo "### 4. NEW API on converged DB"
api $ROOT reh_fx 8022 fx-token
python $R/edited_copy_api.py http://127.0.0.1:8022 fx-token summary $OUT/fx_2_new_after_convergence.json >/dev/null
stop_port 8022
echo "### 5. totals: OLD API after edit  vs  NEW API after convergence"
python $R/edited_copy_api.py diff $OUT/fx_1_old_after_edit.json $OUT/fx_2_new_after_convergence.json
echo "### 6. origin / legacy_id of elective copies after convergence"
psql $H -d reh_fx -At -c "select u.telegram_id, ts.id, ts.origin, coalesce(ts.legacy_id::text,'NULL') legacy_id, ts.performed_at::date, (ts.superseded_at is not null) superseded from training_sessions ts join users u on u.id=ts.user_id where ts.source='elective' order by 1, ts.id"
