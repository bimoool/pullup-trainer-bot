"""DELETE /api/v2/workouts/{id} и POST /api/v2/workouts/{id}/duplicate (issue #261)."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    SessionStatus,
    TrainingSession,
    UserFavorite,
)
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType, SessionSource
from tests.test_web._v2_client import v2_delete, v2_get, v2_post, v2_put

REPS = {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 8}, "rest_seconds": 90}


async def _workout_with_item(session, user: User, title: str = "Моя") -> tuple[int, int]:
    workout_id = (await v2_post(session, user.telegram_id, "/api/v2/workouts", {"title": title})).json()["id"]
    exercise = Exercise(name=f"Упр {title}", metric_type=MetricType.REPS, category="test")
    session.add(exercise)
    await session.flush()
    response = await v2_post(
        session, user.telegram_id, f"/api/v2/workouts/{workout_id}/items",
        {"exercise_id": exercise.id, "protocol": REPS},
    )
    assert response.status_code == 200
    return workout_id, exercise.id


async def _titles(session, user: User) -> list[str]:
    response = await v2_get(session, user.telegram_id, "/api/v2/workouts")
    return [w["title"] for w in response.json()["workouts"]]


async def test_delete_hides_workout_everywhere_but_keeps_definition(session, user: User):
    workout_id, _ = await _workout_with_item(session, user)
    await v2_put(session, user.telegram_id, f"/api/v2/favorites/workout/{workout_id}")

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")).status_code == 204

    assert await _titles(session, user) == []
    assert (await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")).status_code == 404
    assert (await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout_id}/sessions")).status_code == 404
    favorites = (await v2_get(session, user.telegram_id, "/api/v2/favorites")).json()["favorites"]
    assert favorites == []
    assert (await session.execute(select(UserFavorite))).scalars().all() == []
    # второе удаление — 404; определение и состав физически остались
    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")).status_code == 404
    complex_ = await session.get(Complex, workout_id)
    assert complex_ is not None and complex_.archived_at is not None
    items = (await session.execute(select(ComplexItem).where(ComplexItem.complex_id == workout_id))).scalars().all()
    assert len(items) == 1


async def test_delete_foreign_system_and_missing_are_404(session, user: User):
    other = await UserRepository(session).create(telegram_id=2002, username="other")
    foreign_id, _ = await _workout_with_item(session, other, "Чужая")
    system = Complex(name="Системная", source_type="system")
    session.add(system)
    await session.flush()

    for target in (foreign_id, system.id, 999999):
        assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{target}")).status_code == 404
        assert (
            await v2_post(session, user.telegram_id, f"/api/v2/workouts/{target}/duplicate", {})
        ).status_code == 404
    assert await _titles(session, other) == ["Чужая"]
    assert (await session.get(Complex, system.id)).archived_at is None


async def test_delete_keeps_completed_session_snapshot(session, user: User):
    workout_id, _ = await _workout_with_item(session, user)
    training = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED, performed_at=datetime.now(UTC),
        workout_snapshot={"workout_id": workout_id, "title": "Моя", "items": []},
    )
    session.add(training)
    await session.flush()

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")).status_code == 204

    kept = await session.get(TrainingSession, training.id)
    assert kept is not None and kept.workout_snapshot["workout_id"] == workout_id
    assert kept.status == SessionStatus.COMPLETED


async def test_delete_removes_manual_plan_items_only_of_that_workout(session, user: User):
    workout_id, exercise_id = await _workout_with_item(session, user, "Удаляемая")
    other_id, _ = await _workout_with_item(session, user, "Остаётся")
    plan = await TrainingPlanRepository(session).get_or_create_for_user(user.id)
    for complex_id in (workout_id, other_id):
        session.add(PlanItem(
            training_plan_id=plan.id, exercise_id=exercise_id, complex_id=complex_id, count_per_week=1,
        ))
    await session.flush()

    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")).status_code == 204

    remaining = (await session.execute(select(PlanItem.complex_id))).scalars().all()
    assert remaining == [other_id]
    assert await _titles(session, user) == ["Остаётся"]


async def test_duplicate_copies_items_and_protocols_for_same_owner(session, user: User):
    workout_id, exercise_id = await _workout_with_item(session, user, "Спина")

    response = await v2_post(session, user.telegram_id, f"/api/v2/workouts/{workout_id}/duplicate", {})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Спина (копия)"
    assert body["id"] != workout_id
    assert body["source_type"] == "user" and body["owner_user_id"] == user.id
    assert [(i["exercise_id"], i["order_index"], i["protocol"]) for i in body["items"]] == [(exercise_id, 0, REPS)]

    assert await _titles(session, user) == ["Спина", "Спина (копия)"]
    original_items = (await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")).json()["items"]
    assert len(original_items) == 1
    assert original_items[0]["id"] != body["items"][0]["id"]

    # копия независима: удаление оригинала её не трогает
    await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{workout_id}")
    assert await _titles(session, user) == ["Спина (копия)"]
