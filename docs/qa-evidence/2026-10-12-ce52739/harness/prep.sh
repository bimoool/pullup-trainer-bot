#!/usr/bin/env bash
# usage: prep.sh <tree> <name> <port>
set -eo pipefail
T=$1; N=$2; P=$3
export PGPASSWORD=pullup
psql -h localhost -U pullup -d pullup -qc "DROP DATABASE IF EXISTS qa_$N" -c "CREATE DATABASE qa_$N"
export DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/qa_$N BOT_TOKEN=e2e-test-token ADMIN_IDS="900010,900011,900012" PYTHONPATH=$T
cd $T
python -m alembic upgrade head 2>&1 | tail -2
(cd webapp-frontend && npm ci --silent 2>&1 | tail -2 && npm run build 2>&1 | tail -3)
(cd webapp-frontend/e2e && npm ci --silent 2>&1 | tail -2)
nohup python -m uvicorn app.web.main:app --port $P > /tmp/claude-0/qa/uvicorn_$N.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://127.0.0.1:$P/health && break; sleep 1; done
PYTHON=python scripts/e2e_seed_all.sh 2>&1 | tail -3
echo PREP_DONE $N
