"""Тесты Move/Remove PlanItem API (Phase D2, issue #188) — PATCH/DELETE
/plan-items/{id}, plus complex_source_type metadata на GET /plan. Тот же
паттерн, что test_v2_workouts.py уже использует (v2_get/v2_post/v2_patch
+ user-фикстура из conftest.py)."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    Program,
    ProgramInclusion,
    ProgramItem,
    SessionBlock,
    SessionSource,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
)
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from tests.test_web._v2_client import v2_get, v2_patch


async def _v2_delete(session, telegram_id: int, path: str):
    from httpx import ASGITransport, AsyncClient

    from app.web.main import app
    from tests.test_web._v2_client import _override_dependencies

    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.delete(path)
    finally:
        app.dependency_overrides.clear()


async def _create_second_user(session, telegram_id: int) -> User:
    from app.db.repositories.users import UserRepository

    users = UserRepository(session)
    return await users.create(telegram_id=telegram_id, username="second_user")


async def _create_manual_plan_item(session, user: User, *, day_of_week: int | None = 0) -> tuple[PlanItem, Exercise]:
    exercise = Exercise(name="Планка", metric_type=MetricType.TIME, category="core", source_type="system")
    session.add(exercise)
    await session.flush()
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    item = PlanItem(
        training_plan_id=plan.id, exercise_id=exercise.id, count_per_week=3, day_of_week=day_of_week,
    )
    session.add(item)
    await session.flush()
    await session.commit()
    return item, exercise


async def _create_workout_plan_item(
    session, user: User, *, source_type: str, owner_user_id: int | None, day_of_week: int | None = 0,
) -> tuple[PlanItem, Complex, ComplexItem]:
    exercise = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="pull", source_type="system")
    session.add(exercise)
    await session.flush()
    workout = Complex(name="Тестовая тренировка", source_type=source_type, owner_user_id=owner_user_id)
    session.add(workout)
    await session.flush()
    complex_item = ComplexItem(
        complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=0,
        protocol={"type": "max_effort", "prescription": {"source": "static", "attempts": 1}, "rest_seconds": 0},
    )
    session.add(complex_item)
    await session.flush()
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    item = PlanItem(
        training_plan_id=plan.id, exercise_id=exercise.id, complex_id=workout.id,
        count_per_week=1, day_of_week=day_of_week,
    )
    session.add(item)
    await session.flush()
    await session.commit()
    return item, workout, complex_item


async def _create_step_plan_item(session, user: User) -> PlanItem:
    """STEP/program-backed PlanItem — program_inclusion_id IS NOT NULL."""
    exercise = Exercise(name="Подтягивания STEP", metric_type=MetricType.REPS, category="pull", source_type="system")
    session.add(exercise)
    await session.flush()
    program = Program(name="Тест программа", goal="test", structure_type=ProgramStructureType.RECURRING, category="pull_ups_test")
    session.add(program)
    await session.flush()
    session.add(ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3))
    await session.flush()
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    inclusion = ProgramInclusion(
        training_plan_id=plan.id, program_id=program.id, snapshot={"program_name": "Тест программа"},
        progression_state={"strategy_type": "step"},
    )
    session.add(inclusion)
    await session.flush()
    item = PlanItem(
        training_plan_id=plan.id, exercise_id=exercise.id, program_inclusion_id=inclusion.id,
        count_per_week=3, day_of_week=0,
    )
    session.add(item)
    await session.flush()
    await session.commit()
    return item


# ============================================================================
# MOVE
# ============================================================================


async def test_move_manual_exercise_monday_to_wednesday(session, user: User):
    item, _ = await _create_manual_plan_item(session, user, day_of_week=0)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": 2})
    assert response.status_code == 200
    assert response.json()["day_of_week"] == 2

    result = await session.execute(select(PlanItem).where(PlanItem.id == item.id))
    assert result.scalar_one().day_of_week == 2


async def test_move_manual_exercise_wednesday_to_free_pool(session, user: User):
    item, _ = await _create_manual_plan_item(session, user, day_of_week=2)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": None})
    assert response.status_code == 200
    assert response.json()["day_of_week"] is None


async def test_move_manual_exercise_free_pool_to_sunday(session, user: User):
    item, _ = await _create_manual_plan_item(session, user, day_of_week=None)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": 6})
    assert response.status_code == 200
    assert response.json()["day_of_week"] == 6


async def test_move_user_workout_plan_item(session, user: User):
    item, _, _ = await _create_workout_plan_item(session, user, source_type="user", owner_user_id=user.id)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": 3})
    assert response.status_code == 200
    assert response.json()["day_of_week"] == 3


async def test_move_system_workout_plan_item(session, user: User):
    item, _, _ = await _create_workout_plan_item(session, user, source_type="system", owner_user_id=None)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": 4})
    assert response.status_code == 200
    assert response.json()["day_of_week"] == 4


async def test_move_other_users_plan_item_is_404(session, user: User):
    user_b = await _create_second_user(session, telegram_id=971002)
    item, _ = await _create_manual_plan_item(session, user_b, day_of_week=0)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": 1})
    assert response.status_code == 404

    result = await session.execute(select(PlanItem).where(PlanItem.id == item.id))
    assert result.scalar_one().day_of_week == 0  # не изменилось


async def test_move_step_program_backed_plan_item_is_404(session, user: User):
    item = await _create_step_plan_item(session, user)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": 5})
    assert response.status_code == 404

    result = await session.execute(select(PlanItem).where(PlanItem.id == item.id))
    assert result.scalar_one().day_of_week == 0  # не изменилось


async def test_move_invalid_day_is_422(session, user: User):
    item, _ = await _create_manual_plan_item(session, user, day_of_week=0)
    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}", payload={"day_of_week": 7})
    assert response.status_code == 422


# ============================================================================
# REMOVE
# ============================================================================


async def test_remove_manual_exercise(session, user: User):
    item, exercise = await _create_manual_plan_item(session, user)
    response = await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}")
    assert response.status_code == 204

    result = await session.execute(select(PlanItem).where(PlanItem.id == item.id))
    assert result.scalar_one_or_none() is None  # PlanItem удалён

    exercise_check = await session.execute(select(Exercise).where(Exercise.id == exercise.id))
    assert exercise_check.scalar_one_or_none() is not None  # Exercise остался


async def test_remove_user_workout_keeps_complex_and_items(session, user: User):
    item, workout, complex_item = await _create_workout_plan_item(session, user, source_type="user", owner_user_id=user.id)
    response = await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}")
    assert response.status_code == 204

    result = await session.execute(select(PlanItem).where(PlanItem.id == item.id))
    assert result.scalar_one_or_none() is None

    workout_check = await session.execute(select(Complex).where(Complex.id == workout.id))
    assert workout_check.scalar_one_or_none() is not None  # Complex остался

    item_check = await session.execute(select(ComplexItem).where(ComplexItem.id == complex_item.id))
    assert item_check.scalar_one_or_none() is not None  # ComplexItem остался


async def test_remove_system_workout_plan_item_keeps_complex(session, user: User):
    item, workout, _ = await _create_workout_plan_item(session, user, source_type="system", owner_user_id=None)
    response = await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}")
    assert response.status_code == 204

    workout_check = await session.execute(select(Complex).where(Complex.id == workout.id))
    assert workout_check.scalar_one_or_none() is not None


async def test_remove_plan_item_keeps_completed_session_history(session, user: User):
    """Раздел 10 — после удаления PlanItem существующий TrainingSession/
    workout_snapshot/result остаётся неизменным."""
    item, workout, _ = await _create_workout_plan_item(session, user, source_type="user", owner_user_id=user.id)

    snapshot = {"workout_id": workout.id, "title": "Тестовая тренировка", "items": []}
    training_session = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED,
        performed_at=datetime.now(UTC), workout_snapshot=snapshot,
    )
    session.add(training_session)
    await session.flush()
    session_block = SessionBlock(
        session_id=training_session.id, order_index=0, complex_id=workout.id,
        result={"type": "max_effort", "attempts": 1},
    )
    session.add(session_block)
    await session.commit()

    response = await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}")
    assert response.status_code == 204

    session_check = await session.execute(select(TrainingSession).where(TrainingSession.id == training_session.id))
    refreshed_session = session_check.scalar_one()
    assert refreshed_session.workout_snapshot == snapshot

    block_check = await session.execute(select(SessionBlock).where(SessionBlock.id == session_block.id))
    refreshed_block = block_check.scalar_one()
    assert refreshed_block.result == {"type": "max_effort", "attempts": 1}


async def test_remove_other_users_plan_item_is_404(session, user: User):
    user_b = await _create_second_user(session, telegram_id=971003)
    item, _ = await _create_manual_plan_item(session, user_b)
    response = await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}")
    assert response.status_code == 404

    result = await session.execute(select(PlanItem).where(PlanItem.id == item.id))
    assert result.scalar_one_or_none() is not None  # не удалился


async def test_remove_step_program_backed_plan_item_is_404(session, user: User):
    item = await _create_step_plan_item(session, user)
    response = await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items/{item.id}")
    assert response.status_code == 404

    result = await session.execute(select(PlanItem).where(PlanItem.id == item.id))
    assert result.scalar_one_or_none() is not None


# ============================================================================
# METADATA — complex_source_type
# ============================================================================


async def test_plan_response_complex_source_type_for_manual_exercise_is_null(session, user: User):
    await _create_manual_plan_item(session, user)
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    items = response.json()["plan"]["plan_items"]
    assert len(items) == 1
    assert items[0]["complex_source_type"] is None


async def test_plan_response_complex_source_type_for_user_workout(session, user: User):
    await _create_workout_plan_item(session, user, source_type="user", owner_user_id=user.id)
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    items = response.json()["plan"]["plan_items"]
    assert len(items) == 1
    assert items[0]["complex_source_type"] == "user"


async def test_plan_response_complex_source_type_for_system_workout(session, user: User):
    await _create_workout_plan_item(session, user, source_type="system", owner_user_id=None)
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    items = response.json()["plan"]["plan_items"]
    assert len(items) == 1
    assert items[0]["complex_source_type"] == "system"
