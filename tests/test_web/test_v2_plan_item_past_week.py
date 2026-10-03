"""Ревью #289 R-2: POST /plan-items не принимает прошлую неделю (#275: read-only) и
ограничивает count_per_week."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models_program import Exercise, TrainingPlan
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import MetricType, WeekPhase, plan_week_start_date
from app.web import routes_v2
from tests.test_web._v2_client import v2_post

TG = 1001
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


async def _setup(session, user, monkeypatch):
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: NOW)
    exercise = Exercise(name="Отжимания", metric_type=MetricType.REPS, category="test_synth")
    session.add(exercise)
    created = NOW - timedelta(days=21)
    session.add(TrainingPlan(user_id=user.id, created_at=created))
    await session.flush()
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    weeks = {}
    for n in (1, 4):
        weeks[n] = await plans.create_plan_week(
            training_plan_id=plan.id, week_number=n,
            start_date=plan_week_start_date(created.date(), n), phase=WeekPhase.BASE,
        )
    await session.commit()
    return exercise, weeks


async def test_create_plan_item_rejects_past_week(session, user, monkeypatch):
    exercise, weeks = await _setup(session, user, monkeypatch)
    body = {"exercise_id": exercise.id, "count_per_week": 1, "day_of_week": 1}
    past = await v2_post(session, TG, "/api/v2/plan-items", {**body, "plan_week_id": weeks[1].id})
    assert past.status_code == 422, past.text
    ok = await v2_post(session, TG, "/api/v2/plan-items", {**body, "plan_week_id": weeks[4].id})
    assert ok.status_code == 200, ok.text


@pytest.mark.parametrize("count", [0, -1, 15, 1000])
async def test_create_plan_item_bounds_count_per_week(session, user, monkeypatch, count):
    exercise, weeks = await _setup(session, user, monkeypatch)
    resp = await v2_post(
        session, TG, "/api/v2/plan-items",
        {"exercise_id": exercise.id, "count_per_week": count, "plan_week_id": weeks[4].id},
    )
    assert resp.status_code == 422, resp.text
