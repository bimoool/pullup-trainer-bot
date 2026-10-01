#!/usr/bin/env bash
# Real Mini App E2E for the ORCH worker job (.github/workflows/orch-worker.yml) — the same
# environment as .github/workflows/e2e.yml: Postgres DB pullup_e2e, alembic head, built
# frontend served by uvicorn :8001, scripts/e2e_seed_all.sh, Playwright chromium.
#
# Used twice in one job:
#   - by the Claude worker while it works:   bash orch-out/e2e.sh [playwright args, e.g. a spec]
#   - by the deterministic gate (fresh DB):  bash <copy from the base commit> --fresh
# Lives under .github/orch/ so a worker cannot change it (forbidden path); the gate always runs
# the copy taken from the base commit, never the worker branch.
#
# Prerequisites installed by the workflow before the agent starts: Python deps, frontend
# node_modules, webapp-frontend/e2e node_modules and the Playwright chromium browser.
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
LOG_DIR=${ORCH_E2E_LOG_DIR:-/tmp/orch-e2e}
mkdir -p "$LOG_DIR"

FRESH=0
if [ "${1:-}" = "--fresh" ]; then FRESH=1; shift; fi

PGPORT=${ORCH_PG_PORT:-5432} # override only when running this script outside Actions
export PGHOST=localhost PGUSER=pullup PGPASSWORD=pullup PGPORT
export DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:$PGPORT/pullup_e2e
export BOT_TOKEN=e2e-test-token
export ADMIN_IDS="900010,900011,900012" # v2 session seeds (see e2e.yml)
export PYTHONPATH="${PYTHONPATH:-.}"

python - "$FRESH" <<'PY'
import asyncio, os, sys
import asyncpg

async def main(fresh: bool) -> None:
    c = await asyncpg.connect(f"postgresql://pullup:pullup@localhost:{os.environ['PGPORT']}/pullup")
    try:
        if fresh:
            await c.execute("DROP DATABASE IF EXISTS pullup_e2e WITH (FORCE)")
        if not await c.fetchval("SELECT 1 FROM pg_database WHERE datname = 'pullup_e2e'"):
            await c.execute("CREATE DATABASE pullup_e2e")
    finally:
        await c.close()

asyncio.run(main(sys.argv[1] == "1"))
PY

echo "== alembic upgrade head (pullup_e2e)"
alembic upgrade head > "$LOG_DIR/alembic.log" 2>&1 || { tail -40 "$LOG_DIR/alembic.log"; exit 1; }

echo "== frontend build"
(cd webapp-frontend && npm run build) > "$LOG_DIR/build.log" 2>&1 || { tail -40 "$LOG_DIR/build.log"; exit 1; }

echo "== (re)start uvicorn :8001"
pkill -f "uvicorn app.web.main:app" 2>/dev/null || true
sleep 1
nohup uvicorn app.web.main:app --port 8001 > "$LOG_DIR/uvicorn.log" 2>&1 &
for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:8001/health >/dev/null && break
  sleep 1
done
curl -sf http://127.0.0.1:8001/health >/dev/null || {
  echo "server did not become healthy"; tail -60 "$LOG_DIR/uvicorn.log"; exit 1;
}

echo "== seed"
bash scripts/e2e_seed_all.sh > "$LOG_DIR/seed.log" 2>&1 || { tail -40 "$LOG_DIR/seed.log"; exit 1; }

echo "== playwright $*"
cd webapp-frontend/e2e
[ -d node_modules/@playwright/test ] || npm ci
E2E_BASE_URL=http://127.0.0.1:8001 npx playwright test "$@"
