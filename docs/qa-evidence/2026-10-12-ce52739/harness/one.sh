#!/usr/bin/env bash
N=$1; P=$2; T=/home/user/wt-$N
export DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/qa_$N BOT_TOKEN=e2e-test-token ADMIN_IDS="900010,900011,900012" PYTHONPATH=$T
cd $T && python scripts/e2e_seed.py plan_week_start_session 900016 >/dev/null 2>&1
cd $T/webapp-frontend/e2e && CI=1 E2E_BASE_URL=http://127.0.0.1:$P npx playwright test --project=chromium --workers=1 --retries=0 --reporter=list plans-start-session 2>&1 | tail -n 6 | cut -c1-200
