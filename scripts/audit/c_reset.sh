#!/bin/bash
# Restore pullup_audit_c to the seeded S0 snapshot (profiles after backfill + injection) and restart uvicorn :8093.
set -e
cd /home/user/pullup-trainer-bot
pkill -f "uvicorn app.web.main:app --host 127.0.0.1 --port 8093" || true
sleep 1
export PGPASSWORD=pullup
psql -h localhost -U pullup -d postgres -qc "select pg_terminate_backend(pid) from pg_stat_activity where datname='pullup_audit_c'" >/dev/null
psql -h localhost -U pullup -d postgres -qc "drop database pullup_audit_c" -c "create database pullup_audit_c owner pullup"
psql -h localhost -U pullup -d pullup_audit_c -q -f ${SNAP:-/tmp/claude-0/c_seed_snapshot.sql} >/dev/null 2>&1
redis-cli -n 3 flushdb >/dev/null 2>&1 || true
BOT_TOKEN=audit-token DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_audit_c REDIS_URL=redis://localhost:6379/3 nohup .venv/bin/uvicorn app.web.main:app --host 127.0.0.1 --port 8093 > /tmp/audit-C-existing-uvicorn.log 2>&1 &
sleep 5; curl -s 127.0.0.1:8093/health
