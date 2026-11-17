"""An explicit calendar for reserved visual fixtures; engine clocks stay real.

These fixtures exercise UI/week editing, not wall-clock rollover admission.
Unlisted identities always use the production calendar and ordinary row writers.
"""

import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

CALENDAR_SCENARIOS = {
    990001: "plan_week_stepper",
    990002: "plan_week_stepper",
    990101: "plans_overview",
    990102: "plans_overview",
    991001: "builder_workouts",
    991002: "builder_workouts",
    991003: "builder_workouts",
    991004: "builder_workouts",
    991011: "builder_workouts",
    991012: "builder_workouts",
    991013: "builder_workouts",
    991014: "builder_workouts",
    997701: "builder_workouts",
}


def guarded_calendar_environment() -> datetime:
    """Validate before importing settings, creating an engine or importing ASGI."""
    guarded = {
        "DATABASE_URL",
        "BOT_TOKEN",
        "STAGING_BOT_TOKEN",
        "MINI_APP_URL",
        "STAGING_URL",
        "REDIS_URL",
        "GITHUB_TOKEN",
        "ROBOKASSA_MERCHANT_LOGIN",
        "ROBOKASSA_PASSWORD_1",
        "ROBOKASSA_PASSWORD_2",
        "GOOGLE_SHEETS_SPREADSHEET_ID",
        "GOOGLE_SHEETS_CREDENTIALS_PATH",
        "ADMIN_SHEET_URL",
        "E2E_PLAN_CALENDAR_AT",
    }
    if any(name.upper() in guarded and name != name.upper() for name in os.environ):
        raise RuntimeError("calendar harness refuses setting aliases")
    if os.path.lexists(Path.cwd() / ".env"):
        raise RuntimeError("calendar harness refuses dotenv")
    try:
        url = urlsplit(os.environ.get("DATABASE_URL", ""))
        port = url.port
    except ValueError:
        raise RuntimeError("calendar harness requires fixed loopback synthetic database") from None
    if (
        url.scheme != "postgresql+asyncpg"
        or url.hostname not in {"127.0.0.1", "localhost"}
        or port not in {5432, 55432}
        or url.path != "/pullup_e2e"
        or url.username != "pullup"
        or url.password != "pullup"
        or url.query
        or url.fragment
    ):
        raise RuntimeError("calendar harness requires fixed loopback synthetic database")
    if os.environ.get("BOT_TOKEN") != "e2e-test-token" or os.environ.get(
        "STAGING_BOT_TOKEN", ""
    ) not in {"", "e2e-test-token"}:
        raise RuntimeError("calendar harness requires exact synthetic tokens")
    for name in ("MINI_APP_URL", "STAGING_URL"):
        if os.environ.get(name, "") not in {"", "http://127.0.0.1:8001"}:
            raise RuntimeError("calendar harness refuses external URLs")
    if os.environ.get("REDIS_URL", "") not in {
        "",
        "redis://127.0.0.1:6379/0",
        "redis://127.0.0.1:56379/0",
    }:
        raise RuntimeError("calendar harness refuses external Redis")
    for name in (
        "GITHUB_TOKEN",
        "ROBOKASSA_MERCHANT_LOGIN",
        "ROBOKASSA_PASSWORD_1",
        "ROBOKASSA_PASSWORD_2",
        "GOOGLE_SHEETS_SPREADSHEET_ID",
        "GOOGLE_SHEETS_CREDENTIALS_PATH",
        "ADMIN_SHEET_URL",
    ):
        if os.environ.get(name, ""):
            raise RuntimeError("calendar harness refuses optional credentials")
    try:
        at = datetime.fromisoformat(os.environ["E2E_PLAN_CALENDAR_AT"])
    except (KeyError, ValueError):
        raise RuntimeError("calendar harness requires explicit UTC instant") from None
    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise RuntimeError("calendar harness requires explicit UTC instant")
    return at


def frozen_datetime(at):
    class CalendarDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz is not None else at.replace(tzinfo=None)

    return CalendarDatetime


def install_plan_calendar(at, identities):
    """Install removable, user-aware adapters only for the given test identities."""
    from sqlalchemy import event, select

    from app.db.models import User
    from app.db.models_program import TrainingPlan
    from app.web import routes_v2

    identities = frozenset(identities)
    original = routes_v2._plan_today

    def today(user):
        if user.telegram_id in identities:
            return at.astimezone(ZoneInfo(user.timezone or "Europe/Moscow")).date()
        return original(user)

    routes_v2._plan_today = today

    def owner(connection, user_id):
        return connection.execute(
            select(User.telegram_id, User.timezone).where(User.id == user_id)
        ).first()

    def anchor_plan(mapper, connection, target):
        user = owner(connection, target.user_id)
        if user and user.telegram_id in identities and target.created_at is None:
            local_date = at.astimezone(ZoneInfo(user.timezone or "Europe/Moscow")).date()
            target.created_at = datetime.combine(local_date, time(12), UTC)

    listeners = [(TrainingPlan, anchor_plan)]
    for model, callback in listeners:
        event.listen(model, "before_insert", callback)

    def restore():
        routes_v2._plan_today = original
        for model, callback in listeners:
            event.remove(model, "before_insert", callback)

    return restore
