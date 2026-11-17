"""Real API rollover semantics remain visible outside the finite visual fixtures."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.db.models_program import TrainingPlan, TrainingSession
from app.db.repositories.users import UserRepository
from app.services import live_engine
from app.web import routes_v2
from tests.support.plan_calendar import CALENDAR_SCENARIOS, install_plan_calendar
from tests.test_web._v2_client import v2_get


@pytest.mark.parametrize(
    "before,after,timezone",
    [
        (
            datetime(2026, 11, 15, 20, 59, 59, tzinfo=UTC),
            datetime(2026, 11, 15, 21, tzinfo=UTC),
            "Europe/Moscow",
        ),
        (
            datetime(2026, 5, 31, 20, 59, 59, tzinfo=UTC),
            datetime(2026, 5, 31, 21, tzinfo=UTC),
            "Europe/Moscow",
        ),
        (
            datetime(2028, 12, 31, 20, 59, 59, tzinfo=UTC),
            datetime(2028, 12, 31, 21, tzinfo=UTC),
            "Europe/Moscow",
        ),
        (datetime(2026, 11, 15, 23, 59, 59, tzinfo=UTC), datetime(2026, 11, 16, tzinfo=UTC), "UTC"),
    ],
)
async def test_actual_api_rolls_week_at_local_monday(session, monkeypatch, before, after, timezone):
    user = await UserRepository(session).create(telegram_id=780001)
    user.timezone = timezone
    plan = TrainingPlan(user_id=user.id, created_at=before)
    session.add(plan)
    await session.commit()
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: before)
    first = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert first.status_code == 200
    first_plan = first.json()["plan"]
    first_week = next(
        w for w in first_plan["plan_weeks"] if w["id"] == first_plan["current_week_id"]
    )
    assert first_week["week_number"] == 1
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: after)
    second = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert second.status_code == 200
    second_plan = second.json()["plan"]
    second_week = next(
        w for w in second_plan["plan_weeks"] if w["id"] == second_plan["current_week_id"]
    )
    assert second_week["week_number"] == 2


async def test_fixture_adapter_preserves_unlisted_origins_and_all_record_timestamps(session):
    at = datetime(2026, 11, 15, 20, 59, 59, tzinfo=UTC)
    engine_clock = live_engine._utcnow
    original_today = routes_v2._plan_today
    now = datetime.now(UTC)
    restore = install_plan_calendar(at, CALENDAR_SCENARIOS)
    try:
        for tg in (991001, 780002, 930606, 930607, 7_000_000_001):
            user = await UserRepository(session).create(telegram_id=tg)
            user.timezone = "Europe/Moscow"
            plan = TrainingPlan(user_id=user.id)
            session.add(plan)
            fact = TrainingSession(
                user_id=user.id,
                source="plan",
                status="completed",
                performed_at=now - timedelta(minutes=10),
                started_at=now - timedelta(minutes=10),
                completed_at=now,
                ended_at=now,
            )
            session.add(fact)
            await session.flush()
            if tg in CALENDAR_SCENARIOS:
                assert plan.created_at.date() == routes_v2._plan_today(user)
            else:
                assert abs((plan.created_at - now).total_seconds()) < 60
                assert routes_v2._plan_today(user) == original_today(user)
            assert (fact.performed_at, fact.started_at, fact.completed_at, fact.ended_at) == (
                now - timedelta(minutes=10),
                now - timedelta(minutes=10),
                now,
                now,
            )
        explicit_user = await UserRepository(session).create(telegram_id=991002)
        explicit = TrainingPlan(user_id=explicit_user.id, created_at=now)
        session.add(explicit)
        await session.flush()
        assert explicit.created_at == now
        assert live_engine._utcnow is engine_clock
    finally:
        restore()


def test_scoped_calendar_does_not_replace_global_clock_or_other_profiles(monkeypatch):
    at = datetime(2026, 11, 15, 20, 59, 59, tzinfo=UTC)
    live = datetime(2026, 11, 15, 21, tzinfo=UTC)
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: live)
    clock = routes_v2._utcnow
    restore = install_plan_calendar(at, CALENDAR_SCENARIOS)
    try:
        assert (
            routes_v2._plan_today(SimpleNamespace(telegram_id=991001, timezone="Europe/Moscow"))
            == at.date()
        )
        assert (
            routes_v2._plan_today(SimpleNamespace(telegram_id=930606, timezone="Europe/Moscow")).day
            == 16
        )
        assert routes_v2._utcnow is clock
    finally:
        restore()
