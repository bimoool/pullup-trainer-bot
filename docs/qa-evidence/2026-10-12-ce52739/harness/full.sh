#!/usr/bin/env bash
# usage: full.sh <name> <port> <tag>
N=$1; P=$2; TAG=$3; T=/home/user/wt-$N
export DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/qa_$N BOT_TOKEN=e2e-test-token ADMIN_IDS="900010,900011,900012" PYTHONPATH=$T
cd $T && PYTHON=python scripts/e2e_seed_all.sh > /tmp/claude-0/qa/reseed_${N}_$TAG.log 2>&1
cd $T/webapp-frontend/e2e
CI=1 E2E_BASE_URL=http://127.0.0.1:$P npx playwright test --workers=1 --reporter=list > /tmp/claude-0/qa/full_${N}_$TAG.log 2>&1
echo FULL_DONE >> /tmp/claude-0/qa/full_${N}_$TAG.log
