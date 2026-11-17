"""Guarded local ASGI entrypoint for the finite visual calendar fixtures."""

from tests.support.plan_calendar import (
    CALENDAR_SCENARIOS,
    guarded_calendar_environment,
    install_plan_calendar,
)

calendar_at = guarded_calendar_environment()
install_plan_calendar(calendar_at, CALENDAR_SCENARIOS)

from app.web.main import app  # noqa: F401
