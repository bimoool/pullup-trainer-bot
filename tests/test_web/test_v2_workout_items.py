"""Тесты WorkoutItem CRUD (Phase C3, issue #188) — POST/PATCH/DELETE
/workouts/{id}/items[/...], тот же паттерн, что test_v2_workouts.py уже
использует (v2_get/v2_post/v2_patch + user-фикстура из conftest.py)."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import Complex, ComplexItem, Exercise
from app.domain.multi_program import MetricType
from tests.test_web._v2_client import v2_get, v2_patch, v2_post


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


async def _create_exercise(session, *, name: str = "Отжимания") -> Exercise:
    exercise = Exercise(name=name, metric_type=MetricType.REPS, category="test")
    session.add(exercise)
    await session.flush()
    return exercise


REPS_PROTOCOL = {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 15}, "rest_seconds": 90}
TIME_PROTOCOL = {"type": "time_sets", "prescription": {"source": "static", "sets": 3, "duration_seconds": 45}, "rest_seconds": 60}
MAX_PROTOCOL = {"type": "max_effort", "prescription": {"source": "static", "attempts": 1}}
INTERVAL_PROTOCOL = {"type": "interval", "total_duration_seconds": 180, "work_seconds": 10, "rest_seconds": 20, "starts_with": "work"}
PROGRESSION_PROTOCOL = {"type": "reps_sets", "prescription": {"source": "progression"}, "rest_seconds": 90}


async def test_user_a_full_item_lifecycle(session, user: User):
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Тренировка A"})
    workout_id = workout_create.json()["id"]

    add = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise.id, "protocol": REPS_PROTOCOL},
    )
    assert add.status_code == 200
    item = add.json()
    assert item["exercise_name"] == "Отжимания"
    assert item["order_index"] == 0
    item_id = item["id"]

    detail = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")
    assert detail.status_code == 200
    assert len(detail.json()["items"]) == 1
    assert detail.json()["items"][0]["id"] == item_id

    update_protocol = await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_id}",
        payload={"protocol": TIME_PROTOCOL},
    )
    assert update_protocol.status_code == 200
    assert update_protocol.json()["protocol"]["type"] == "time_sets"

    exercise2 = await _create_exercise(session, name="Приседания")
    update_exercise = await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_id}",
        payload={"exercise_id": exercise2.id},
    )
    assert update_exercise.status_code == 200
    assert update_exercise.json()["exercise_name"] == "Приседания"

    delete = await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_id}")
    assert delete.status_code == 204

    detail_after_delete = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")
    assert detail_after_delete.json()["items"] == []


async def test_reorder_up_and_down(session, user: User):
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Порядок"})
    workout_id = workout_create.json()["id"]

    item_ids = []
    for i in range(3):
        add = await v2_post(
            session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
            payload={"exercise_id": exercise.id, "protocol": REPS_PROTOCOL},
        )
        item_ids.append(add.json()["id"])

    # append order корректный: 0, 1, 2
    detail = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")
    assert [i["id"] for i in detail.json()["items"]] == item_ids
    assert [i["order_index"] for i in detail.json()["items"]] == [0, 1, 2]

    # move второй item (index 1) вверх -> [1, 0, 2]
    move = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_ids[1]}/move",
        payload={"direction": "up"},
    )
    assert move.status_code == 200
    assert [i["id"] for i in move.json()["items"]] == [item_ids[1], item_ids[0], item_ids[2]]

    # move первый (сейчас item_ids[1]) вниз -> обратно [item_ids[0], item_ids[1], item_ids[2]]
    move_back = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_ids[1]}/move",
        payload={"direction": "down"},
    )
    assert [i["id"] for i in move_back.json()["items"]] == item_ids

    # boundary: первый item + up -> idempotent no-op, не ошибка
    boundary_up = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_ids[0]}/move",
        payload={"direction": "up"},
    )
    assert boundary_up.status_code == 200
    assert [i["id"] for i in boundary_up.json()["items"]] == item_ids  # не изменилось

    # boundary: последний item + down -> idempotent no-op
    boundary_down = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_ids[2]}/move",
        payload={"direction": "down"},
    )
    assert boundary_down.status_code == 200
    assert [i["id"] for i in boundary_down.json()["items"]] == item_ids


async def test_delete_compacts_order_index(session, user: User):
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Компактность"})
    workout_id = workout_create.json()["id"]

    item_ids = []
    for i in range(3):
        add = await v2_post(
            session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
            payload={"exercise_id": exercise.id, "protocol": REPS_PROTOCOL},
        )
        item_ids.append(add.json()["id"])

    # удаляем средний (order_index=1)
    await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_ids[1]}")

    detail = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")
    remaining = detail.json()["items"]
    assert [i["id"] for i in remaining] == [item_ids[0], item_ids[2]]
    assert [i["order_index"] for i in remaining] == [0, 1]  # без дырок


async def test_user_b_cannot_mutate_user_a_workout_items(session, user: User):
    user_b = await _create_second_user(session, telegram_id=982002)
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Приватная"})
    workout_id = workout_create.json()["id"]
    add = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise.id, "protocol": REPS_PROTOCOL},
    )
    item_id = add.json()["id"]

    add_b = await v2_post(
        session, telegram_id=user_b.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise.id, "protocol": REPS_PROTOCOL},
    )
    assert add_b.status_code == 404

    update_b = await v2_patch(
        session, telegram_id=user_b.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_id}",
        payload={"protocol": TIME_PROTOCOL},
    )
    assert update_b.status_code == 404

    delete_b = await _v2_delete(session, telegram_id=user_b.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_id}")
    assert delete_b.status_code == 404

    move_b = await v2_post(
        session, telegram_id=user_b.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_id}/move",
        payload={"direction": "up"},
    )
    assert move_b.status_code == 404


async def test_system_workout_items_are_immutable(session, user: User):
    system_workout = Complex(name="Системная тренировка", source_type="system")
    session.add(system_workout)
    await session.flush()
    exercise = await _create_exercise(session)
    session.add(ComplexItem(complex_id=system_workout.id, exercise_id=exercise.id, order_index=0, sets=0, protocol=REPS_PROTOCOL))
    await session.flush()
    await session.commit()

    add = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{system_workout.id}/items",
        payload={"exercise_id": exercise.id, "protocol": REPS_PROTOCOL},
    )
    assert add.status_code == 404


async def test_add_item_rejects_foreign_user_exercise(session, user: User):
    user_b = await _create_second_user(session, telegram_id=982003)
    exercise_b = Exercise(name="Чужое упражнение", metric_type=MetricType.REPS, category="test", source_type="user", owner_user_id=user_b.id)
    session.add(exercise_b)
    await session.flush()

    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Тест exercise visibility"})
    workout_id = workout_create.json()["id"]

    add = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise_b.id, "protocol": REPS_PROTOCOL},
    )
    assert add.status_code == 404


async def test_add_item_allows_system_and_own_exercise(session, user: User):
    system_exercise = Exercise(name="Системное", metric_type=MetricType.REPS, category="test", source_type="system")
    session.add(system_exercise)
    own_exercise = Exercise(name="Моё", metric_type=MetricType.REPS, category="test", source_type="user", owner_user_id=user.id)
    session.add(own_exercise)
    await session.flush()

    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Видимость OK"})
    workout_id = workout_create.json()["id"]

    add_system = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": system_exercise.id, "protocol": REPS_PROTOCOL},
    )
    assert add_system.status_code == 200

    add_own = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": own_exercise.id, "protocol": REPS_PROTOCOL},
    )
    assert add_own.status_code == 200


async def test_valid_protocols_accepted(session, user: User):
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Все протоколы"})
    workout_id = workout_create.json()["id"]

    for protocol in (REPS_PROTOCOL, TIME_PROTOCOL, MAX_PROTOCOL, INTERVAL_PROTOCOL):
        response = await v2_post(
            session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
            payload={"exercise_id": exercise.id, "protocol": protocol},
        )
        assert response.status_code == 200, f"protocol {protocol['type']} должен быть принят"


async def test_invalid_protocol_rejected(session, user: User):
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Невалидный протокол"})
    workout_id = workout_create.json()["id"]

    invalid = {"type": "interval", "total_duration_seconds": 10, "work_seconds": 10, "rest_seconds": 20, "starts_with": "work"}
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise.id, "protocol": invalid},
    )
    assert response.status_code == 422


async def test_progression_protocol_rejected_via_user_workout_endpoint(session, user: User):
    """Обычный Workout Builder не должен уметь протолкнуть progression
    через сырой JSON (issue #188, раздел 7)."""
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Попытка progression"})
    workout_id = workout_create.json()["id"]

    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise.id, "protocol": PROGRESSION_PROTOCOL},
    )
    assert response.status_code == 422


async def test_update_item_requires_at_least_one_field(session, user: User):
    exercise = await _create_exercise(session)
    workout_create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Пустой update"})
    workout_id = workout_create.json()["id"]
    add = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise.id, "protocol": REPS_PROTOCOL},
    )
    item_id = add.json()["id"]

    response = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}/items/{item_id}", payload={})
    assert response.status_code == 422


async def test_snapshot_immutability_after_item_mutation(session, user: User):
    """Изменение/удаление WorkoutItem после уже выполненной тренировки
    не должно менять TrainingSession.workout_snapshot/SessionBlock.result
    (issue #188, раздел 8) — не переписывает snapshot architecture, только
    проверяет, что она реально не задета."""
    from app.db.models_program import (
        PlanItem,
        SessionBlock,
        SessionSource,
        SessionStatus,
        TrainingPlan,
        TrainingSession,
    )

    exercise = await _create_exercise(session, name="Подтягивания")
    workout = Complex(name="Снимок теста", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    item = ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=0, protocol=REPS_PROTOCOL)
    session.add(item)
    await session.flush()

    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    plan_item = PlanItem(training_plan_id=plan.id, exercise_id=exercise.id, complex_id=workout.id, count_per_week=3)
    session.add(plan_item)
    await session.flush()

    snapshot = {
        "workout_id": workout.id, "title": "Снимок теста",
        "items": [{"exercise_id": exercise.id, "exercise_name": "Подтягивания", "order": 0, "protocol": REPS_PROTOCOL}],
    }
    training_session = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED,
        performed_at=datetime.now(UTC), workout_snapshot=snapshot,
    )
    session.add(training_session)
    await session.flush()
    session_block = SessionBlock(
        session_id=training_session.id, order_index=0, exercise_id=exercise.id,
        result={"type": "interval", "completed_cycles": 6},
    )
    session.add(session_block)
    await session.commit()

    original_snapshot = dict(training_session.workout_snapshot)
    original_result = dict(session_block.result)

    # Мутируем WorkoutItem — protocol и удаление.
    await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout.id}/items/{item.id}",
        payload={"protocol": INTERVAL_PROTOCOL},
    )
    await _v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout.id}/items/{item.id}")

    result = await session.execute(select(TrainingSession).where(TrainingSession.id == training_session.id))
    refreshed_session = result.scalar_one()
    assert refreshed_session.workout_snapshot == original_snapshot  # не изменился

    result2 = await session.execute(select(SessionBlock).where(SessionBlock.id == session_block.id))
    refreshed_block = result2.scalar_one()
    assert refreshed_block.result == original_result  # не изменился
