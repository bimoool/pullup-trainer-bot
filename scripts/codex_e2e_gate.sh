#!/usr/bin/env bash
# A fresh GitHub-hosted runner only: synthetic DB and one server owned by this process.
set -euo pipefail
export DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_e2e
export BOT_TOKEN=e2e-test-token ADMIN_IDS=900010,900011,900012
python - <<'PY'
import asyncio
import asyncpg
async def main():
    conn = await asyncpg.connect('postgresql://pullup:pullup@localhost:5432/pullup')
    try:
        await conn.execute('CREATE DATABASE pullup_e2e')
    finally:
        await conn.close()
asyncio.run(main())
PY
alembic upgrade head
uvicorn app.web.main:app --port 8001 > /tmp/codex-uvicorn.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM
for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:8001/health >/dev/null && break
  sleep 1
done
curl -sf http://127.0.0.1:8001/health >/dev/null
bash scripts/e2e_seed_all.sh
cd webapp-frontend/e2e
export E2E_BASE_URL=http://127.0.0.1:8001
# Shared-cohort spec must run before the remaining specs change its synthetic results.
npx playwright test --project=peer-insights --reporter=list --output=test-results-peer
E2E_SKIP_PEER_PROJECT=1 npm test
