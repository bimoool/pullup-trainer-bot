"""Only the test harness can select a calendar; reject before application imports."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALID = {
    "DATABASE_URL": "postgresql+asyncpg://pullup:pullup@127.0.0.1:55432/pullup_e2e",
    "BOT_TOKEN": "e2e-test-token",
    "E2E_PLAN_CALENDAR_AT": "2026-11-15T20:59:59+00:00",
}


@pytest.mark.parametrize(
    "changes",
    [
        {"DATABASE_URL": "postgresql+asyncpg://pullup:pullup@remote.example/pullup_e2e"},
        {"DATABASE_URL": VALID["DATABASE_URL"] + "?host=remote.example"},
        {"DATABASE_URL": VALID["DATABASE_URL"].replace("pullup_e2e", "pullup")},
        {"DATABASE_URL": VALID["DATABASE_URL"].replace("55432", "PRIVATE-MARKER")},
        {"BOT_TOKEN": "not-the-fixed-test-token"},
        {"database_url": "must-not-import-app"},
        {"bot_token": "must-not-import-app"},
        {"Github_Token": "must-not-import-app"},
        {"robokassa_password_1": "must-not-import-app"},
        {"Redis_Url": "must-not-import-app"},
        {"REDIS_URL": "redis://external.example/0"},
        {"STAGING_BOT_TOKEN": "not-a-test-token"},
        {"MINI_APP_URL": "https://external.example"},
        {"GITHUB_TOKEN": "must-not-import-app"},
        {"E2E_PLAN_CALENDAR_AT": "2026-11-15T20:59:59"},
        {"E2E_PLAN_CALENDAR_AT": "PRIVATE-MARKER"},
        {"DOTENV": "1"},
    ],
)
def test_calendar_guard_rejects_before_settings_or_engines(tmp_path, changes):
    if changes.get("DOTENV"):
        (tmp_path / ".env").write_text("BOT_TOKEN=must-not-load\n")
    code = f"""import sys
sys.path.insert(0, {str(ROOT)!r})
try:
    import tests.support.e2e_calendar_app
except (RuntimeError, ValueError):
    import traceback
    traceback.print_exc()
    assert 'app.config' not in sys.modules and 'app.db.base' not in sys.modules
else:
    raise AssertionError('unsafe harness environment accepted')
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        env={"PATH": os.environ["PATH"], **VALID, **changes},
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PRIVATE-MARKER" not in proc.stdout + proc.stderr


def test_harness_is_excluded_from_images_and_workflow_binds_loopback():
    docker = (ROOT / "Dockerfile").read_text()
    assert "COPY tests" not in docker and "COPY . " not in docker
    workflow = (ROOT / ".github/workflows/e2e.yml").read_text()
    assert "uvicorn tests.support.e2e_calendar_app:app --host 127.0.0.1 --port 8001" in workflow
    assert "E2E_PLAN_CALENDAR_AT=$E2E_PLAN_CALENDAR_AT" in workflow
    assert "from tests." not in (ROOT / "scripts/e2e_seed.py").read_text()
