#!/usr/bin/env bash
# usage: rep5.sh <name> <port> <reps>
N=$1; P=$2; R=$3; T=/home/user/wt-$N
export DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/qa_$N BOT_TOKEN=e2e-test-token ADMIN_IDS="900010,900011,900012" PYTHONPATH=$T
for i in $(seq 1 $R); do
  cd $T
  python scripts/e2e_seed.py builder_workouts 910001 >/dev/null 2>&1
  python scripts/e2e_seed.py golden_journey 930001 >/dev/null 2>&1
  for id in $(seq 930601 930612); do python scripts/e2e_seed.py live_engine $id >/dev/null 2>&1; done
  cd $T/webapp-frontend/e2e
  CI=1 E2E_BASE_URL=http://127.0.0.1:$P npx playwright test --project=chromium --workers=1 --retries=0 --reporter=list builder-execution golden-journey live-engine-v2 > /tmp/claude-0/qa/rep5_${N}_$i.log 2>&1
done
echo REP_DONE > /tmp/claude-0/qa/rep5_${N}_done
