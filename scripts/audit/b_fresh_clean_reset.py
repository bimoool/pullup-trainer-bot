"""Test-only helper (audit B-fresh-clean): recreate pullup_audit_b as a pure clean install (alembic head only),
flush Redis db 1. Stop the uvicorn on :8091 before, start it after."""
import os
import subprocess

DB = "pullup_audit_b"
env = {**os.environ, "BOT_TOKEN": "audit-token", "DATABASE_URL": f"postgresql+asyncpg://pullup:pullup@localhost:5432/{DB}"}
subprocess.run(["su", "postgres", "-c", f"dropdb --if-exists {DB} && createdb -O pullup {DB}"], check=True)
subprocess.run([".venv/bin/alembic", "upgrade", "head"], check=True, env=env)
subprocess.run(["redis-cli", "-n", "1", "flushdb"], check=True)
