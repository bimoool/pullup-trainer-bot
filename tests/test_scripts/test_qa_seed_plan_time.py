"""QA seed calendars and their read-only summaries follow the real plan API."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.db.models_program import PlanWeek, TrainingPlan
from app.web import routes_v2
from scripts.qa import provision_staging_identities as provision
from tests.test_scripts.test_e2e_seed_plan_time import CLOCKS
from tests.test_web._v2_client import v2_get


def _freeze(monkeypatch, now):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(provision, "datetime", FrozenDatetime)
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)


@pytest.mark.parametrize("timezone", ["Europe/Moscow", "UTC"])
@pytest.mark.parametrize(("clock_name", "now"), CLOCKS, ids=[name for name, _ in CLOCKS])
async def test_qa_snapshot_current_week_matches_api(
    session, user, monkeypatch, timezone, clock_name, now
):
    _freeze(monkeypatch, now)
    user.timezone = timezone
    plan = TrainingPlan(user_id=user.id, created_at=now)
    session.add(plan)
    await session.commit()
    summary = await provision.snapshot(session, user.telegram_id)
    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert response.status_code == 200, response.text
    body = response.json()["plan"]
    current = next(week for week in body["plan_weeks"] if week["id"] == body["current_week_id"])
    assert summary["plan"]["current_week_number"] == current["week_number"], clock_name


@pytest.mark.parametrize("timezone", ["Europe/Moscow", "UTC"])
@pytest.mark.parametrize(("clock_name", "start"), CLOCKS, ids=[name for name, _ in CLOCKS])
async def test_qa_visited_weeks_use_local_dates_without_moving_origins(
    session,
    user,
    timezone,
    clock_name,
    start,
):
    user.timezone = timezone
    # server_default=now() is the transaction timestamp, preceding this call.
    inserted_at = await session.scalar(text("SELECT transaction_timestamp()"))
    _, inclusion, plan = await provision._include_course_in_past(
        session,
        user,
        start=start,
        visited_weeks=2,
    )
    await session.commit()
    assert plan.created_at == start
    assert inclusion.created_at == start
    assert inclusion.started_at == inserted_at
    local_start = start.astimezone(ZoneInfo(timezone)).date()
    monday = local_start - timedelta(days=local_start.weekday())
    weeks = (
        (
            await session.execute(
                select(PlanWeek)
                .where(PlanWeek.training_plan_id == plan.id)
                .order_by(PlanWeek.start_date),
            )
        )
        .scalars()
        .all()
    )
    assert [week.start_date for week in weeks] == [monday, monday + timedelta(weeks=1)], clock_name
