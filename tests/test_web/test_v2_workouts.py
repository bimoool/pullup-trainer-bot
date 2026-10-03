"""Тесты Workout core API (Phase C2, issue #188) — POST/GET/PATCH /workouts.
Тот же паттерн, что tests/test_web/test_v2_exercises.py уже использует для
аналогичного C1-фичи (v2_get/v2_post/v2_patch + user-фикстура из conftest.py)."""

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import Complex
from tests.test_web._v2_client import v2_get, v2_patch, v2_post


async def _create_second_user(session, telegram_id: int) -> User:
    from app.db.repositories.users import UserRepository

    users = UserRepository(session)
    return await users.create(telegram_id=telegram_id, username="second_user")


async def test_user_a_creates_workout_sees_it_opens_detail_updates_title(session, user: User):
    create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "3 минуты подтягиваний"})
    assert create.status_code == 200
    data = create.json()
    assert data["title"] == "3 минуты подтягиваний"
    assert data["source_type"] == "user"
    assert data["owner_user_id"] == user.id
    workout_id = data["id"]

    listing = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/workouts")
    assert listing.status_code == 200
    titles = [w["title"] for w in listing.json()["workouts"]]
    assert "3 минуты подтягиваний" in titles

    detail = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "3 минуты подтягиваний"

    patch = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}", payload={"title": "Обновлённое название"})
    assert patch.status_code == 200
    assert patch.json()["title"] == "Обновлённое название"

    result = await session.execute(select(Complex).where(Complex.id == workout_id))
    assert result.scalar_one().name == "Обновлённое название"


async def test_user_b_does_not_see_user_a_workout_in_list(session, user: User):
    user_b = await _create_second_user(session, telegram_id=981002)
    await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Workout A"})

    listing = await v2_get(session, telegram_id=user_b.telegram_id, path="/api/v2/workouts")
    titles = [w["title"] for w in listing.json()["workouts"]]
    assert "Workout A" not in titles
    assert titles == []


async def test_user_b_detail_of_user_a_workout_is_404(session, user: User):
    user_b = await _create_second_user(session, telegram_id=981003)
    create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Приватная тренировка A"})
    workout_id = create.json()["id"]

    detail = await v2_get(session, telegram_id=user_b.telegram_id, path=f"/api/v2/workouts/{workout_id}")
    assert detail.status_code == 404


async def test_user_b_patch_of_user_a_workout_is_404(session, user: User):
    user_b = await _create_second_user(session, telegram_id=981004)
    create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Приватная тренировка A2"})
    workout_id = create.json()["id"]

    patch = await v2_patch(session, telegram_id=user_b.telegram_id, path=f"/api/v2/workouts/{workout_id}", payload={"title": "Взлом"})
    assert patch.status_code == 404

    # Название реально не изменилось.
    result = await session.execute(select(Complex).where(Complex.id == workout_id))
    assert result.scalar_one().name == "Приватная тренировка A2"


async def test_system_workout_detail_accessible_to_any_user(session, user: User):
    system_workout = Complex(name="Системная тренировка", source_type="system")
    session.add(system_workout)
    await session.flush()

    detail = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{system_workout.id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Системная тренировка"
    assert detail.json()["source_type"] == "system"


async def test_system_workout_patch_is_404_for_any_user(session, user: User):
    system_workout = Complex(name="Системная тренировка 2", source_type="system")
    session.add(system_workout)
    await session.flush()

    patch = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{system_workout.id}", payload={"title": "Попытка правки"})
    assert patch.status_code == 404

    result = await session.execute(select(Complex).where(Complex.id == system_workout.id))
    assert result.scalar_one().name == "Системная тренировка 2"  # не изменилось


async def test_create_workout_sets_correct_ownership(session, user: User):
    create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Тест ownership"})
    workout_id = create.json()["id"]

    result = await session.execute(select(Complex).where(Complex.id == workout_id))
    workout = result.scalar_one()
    assert workout.source_type == "user"
    assert workout.owner_user_id == user.id


async def test_create_workout_rejects_empty_title(session, user: User):
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "   "})
    assert response.status_code == 422


async def test_update_workout_rejects_empty_title(session, user: User):
    create = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Валидная тренировка"})
    workout_id = create.json()["id"]

    patch = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout_id}", payload={"title": "   "})
    assert patch.status_code == 422


async def test_duplicate_workout_titles_allowed(session, user: User):
    user_b = await _create_second_user(session, telegram_id=981005)

    r1 = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Моя тренировка"})
    r2 = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/workouts", payload={"title": "Моя тренировка"})
    r3 = await v2_post(session, telegram_id=user_b.telegram_id, path="/api/v2/workouts", payload={"title": "Моя тренировка"})

    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert r1.json()["id"] != r2.json()["id"] != r3.json()["id"]


# ============================================================================
# Phase C5b (issue #188) — regression: POST /plan-items с complex_id, найден
# живым UI-прогоном. PlanItemCreateRequest._exactly_one_target требует ровно
# одно из exercise_id/complex_id, но PlanItem.exercise_id NOT NULL на уровне
# БД — раньше это никогда не билось живым HTTP-путём (все Complex-based
# PlanItem до этого чанка создавались прямой ORM-вставкой в тестах/сидах, с
# exercise_id, подставленным вручную). Реальный /api/v2/plan-items запрос с
# только complex_id (без exercise_id) давал 500 IntegrityError
# NotNullViolationError.
# ============================================================================


async def test_add_plan_item_with_complex_id_only_resolves_exercise_id(session, user: User):
    """Core regression — POST /plan-items {complex_id, без exercise_id}
    больше не падает 500, backend резолвит exercise_id из первого
    ComplexItem выбранного Workout."""
    from datetime import UTC, datetime

    from app.db.models_program import Complex, ComplexItem, Exercise, PlanWeek, TrainingPlan
    from app.domain.multi_program import MetricType

    exercise = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="pull", source_type="system")
    session.add(exercise)
    await session.flush()
    workout = Complex(name="3 минуты подтягиваний", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    session.add(ComplexItem(
        complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=0,
        protocol={"type": "interval", "total_duration_seconds": 180, "work_seconds": 10, "rest_seconds": 20, "starts_with": "work"},
    ))
    await session.flush()
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    week = PlanWeek(training_plan_id=plan.id, week_number=1, start_date=datetime.now(UTC).date(), phase="base")
    session.add(week)
    await session.flush()
    await session.commit()

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"complex_id": workout.id, "plan_week_id": week.id, "day_of_week": 2, "count_per_week": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["complex_id"] == workout.id
    assert data["exercise_id"] == exercise.id  # резолвлен, не null


async def test_add_plan_item_with_both_exercise_id_and_complex_id_rejected(session, user: User):
    """Существующий валидатор (exactly_one_target) не менялся — оба поля
    вместе по-прежнему 422, не 200."""
    from app.db.models_program import Complex, Exercise
    from app.domain.multi_program import MetricType

    exercise = Exercise(name="Тест", metric_type=MetricType.REPS, category="pull", source_type="system")
    session.add(exercise)
    workout = Complex(name="Тест Workout", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "complex_id": workout.id, "count_per_week": 1},
    )
    assert response.status_code == 422


async def test_add_plan_item_with_complex_without_items_returns_422_not_500(session, user: User):
    """Complex без единого ComplexItem — resolver не может подобрать
    exercise_id, честный 422 с человекочитаемым текстом, не 500."""
    from app.db.models_program import Complex

    empty_workout = Complex(name="Пустая тренировка", source_type="user", owner_user_id=user.id)
    session.add(empty_workout)
    await session.flush()
    await session.commit()

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"complex_id": empty_workout.id, "count_per_week": 1},
    )
    assert response.status_code == 422
    assert "упражнени" in response.json()["detail"].lower()


async def test_standard_exercise_id_only_plan_item_still_works(session, user: User):
    """Regression — существующий '+ Добавить упражнение' путь (только
    exercise_id, complex_id всегда None) не задет фиксом резолвера."""
    from app.db.models_program import Exercise
    from app.domain.multi_program import MetricType

    exercise = Exercise(name="Планка", metric_type=MetricType.REPS, category="core", source_type="system")
    session.add(exercise)
    await session.flush()
    await session.commit()

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "count_per_week": 1},
    )
    assert response.status_code == 200
    assert response.json()["exercise_id"] == exercise.id
    assert response.json()["complex_id"] is None
