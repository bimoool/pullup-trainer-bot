"""Checkpoint 3B (issue #197): POST /api/v2/plan-items с plan_week_id —
создание manual PlanItem непосредственно внутри конкретной PlanWeek,
ownership-проверка через get_plan_week_for_user."""

from datetime import date

from sqlalchemy import func, select

from app.db.models import User
from app.db.models_program import Complex, ComplexItem, Exercise, PlanItem
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import MetricType, WeekPhase
from tests.test_web._v2_client import v2_get, v2_post


async def _make_exercise(session) -> Exercise:
    exercise = Exercise(name="Отжимания", metric_type=MetricType.REPS, category="test_synth")
    session.add(exercise)
    await session.flush()
    return exercise


async def test_create_plan_item_with_valid_plan_week_id_succeeds(session, user: User):
    """1. manual PlanItem успешно создаётся с exercise_id + valid plan_week_id + day_of_week"""
    exercise = await _make_exercise(session)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    week = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=1, start_date=date(2026, 9, 21), phase=WeekPhase.BASE,
    )

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={
            "exercise_id": exercise.id, "count_per_week": 3, "day_of_week": 1, "plan_week_id": week.id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan_week_id"] == week.id
    assert body["day_of_week"] == 1
    assert body["program_inclusion_id"] is None
    assert body["exercise_id"] == exercise.id


async def test_create_plan_item_with_plan_week_id_persists_correctly(session, user: User):
    """2. response содержит правильный plan_week_id, day_of_week, program_inclusion_id == NULL"""
    exercise = await _make_exercise(session)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    week = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=1, start_date=date(2026, 9, 21), phase=WeekPhase.BASE,
    )

    create_response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={
            "exercise_id": exercise.id, "count_per_week": 2, "day_of_week": 3, "plan_week_id": week.id,
        },
    )

    assert create_response.status_code == 200
    created_body = create_response.json()

    # Проверка через GET /api/v2/plan
    plan_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    assert plan_response.status_code == 200
    plan_data = plan_response.json()["plan"]
    assert plan_data is not None

    items = plan_data["plan_items"]
    # issue #304 (AD-4): «2 раза в неделю» = два занятия; первое — созданная строка.
    assert [(i["occurrence_index"], i["count_per_week"]) for i in items] == [(1, 1), (2, 1)]
    item = items[0]
    assert item["id"] == created_body["id"]
    assert item["plan_week_id"] == week.id
    assert item["day_of_week"] == 3
    assert item["program_inclusion_id"] is None


async def test_create_plan_item_with_foreign_plan_week_id_is_404(session, user: User):
    """3. чужая PlanWeek → 404, запись не создаётся"""
    exercise = await _make_exercise(session)

    # Создаём второго пользователя с его собственным планом и неделей
    other_user = User(telegram_id=60500, username="other_user")
    session.add(other_user)
    await session.flush()

    plans = TrainingPlanRepository(session)
    other_plan = await plans.get_or_create_for_user(other_user.id)
    other_week = await plans.create_plan_week(
        training_plan_id=other_plan.id, week_number=1, start_date=date(2026, 9, 21), phase=WeekPhase.BASE,
    )

    # Пытаемся создать PlanItem для первого пользователя с week_id второго
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={
            "exercise_id": exercise.id, "count_per_week": 2, "plan_week_id": other_week.id,
        },
    )

    assert response.status_code == 404

    # Проверяем, что запись не создалась
    own_plan = await plans.get_for_user(user.id)
    items = await plans.list_plan_items(own_plan.id)
    assert len(items) == 0


async def test_create_plan_item_with_invalid_day_of_week_is_rejected(session, user: User):
    """4. невалидный day_of_week → отклоняется"""
    exercise = await _make_exercise(session)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    week = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=1, start_date=date(2026, 9, 21), phase=WeekPhase.BASE,
    )

    # day_of_week должен быть 0-6 или NULL
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={
            "exercise_id": exercise.id, "count_per_week": 2, "day_of_week": 7, "plan_week_id": week.id,
        },
    )

    # Pydantic или DB constraint должен отклонить
    assert response.status_code in (400, 422, 500)


async def _make_workout(session, user: User) -> Complex:
    exercise = await _make_exercise(session)
    workout = Complex(name="Моя тренировка", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=3))
    await session.flush()
    return workout


async def _orphan_manual_count(session) -> int:
    return (await session.execute(
        select(func.count()).select_from(PlanItem).where(
            PlanItem.plan_week_id.is_(None), PlanItem.program_inclusion_id.is_(None),
        ),
    )).scalar_one()


async def test_first_add_without_plan_week_id_lands_in_current_week(session, user: User):
    """#297 / FD-02 — у пользователя ещё НЕТ плана, plan_week_id не передан (первое «Добавить в план»):
    строка привязывается к текущей неделе и видна в GET /plan внутри current_week_id; сирот нет."""
    exercise = await _make_exercise(session)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "count_per_week": 3, "day_of_week": 2, "week_phase": "base"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan_week_id"] is not None  # не сирота
    assert body["day_of_week"] == 2
    assert body["week_phase"] == "base"
    assert body["program_inclusion_id"] is None

    plan_data = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")).json()["plan"]
    assert plan_data["current_week_id"] == body["plan_week_id"]
    assert [week["id"] for week in plan_data["plan_weeks"]] == [body["plan_week_id"]]
    rows = [item for item in plan_data["plan_items"] if item["plan_week_id"] == plan_data["current_week_id"]]
    # issue #304 (AD-4): «3 раза в неделю» = три занятия текущей недели, первое — созданная строка.
    assert rows[0]["id"] == body["id"] and len(rows) == 3
    assert await _orphan_manual_count(session) == 0  # инвариант: ручной строки без недели не бывает


async def test_first_add_of_workout_without_plan_week_id_lands_in_current_week(session, user: User):
    """#297 — то же для Workout (complex_id), свободный пул (day_of_week=null)."""
    workout = await _make_workout(session, user)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"complex_id": workout.id, "count_per_week": 1, "day_of_week": None},
    )

    assert response.status_code == 200
    body = response.json()
    plan_data = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")).json()["plan"]
    assert body["plan_week_id"] == plan_data["current_week_id"]
    assert [(item["id"], item["complex_id"], item["day_of_week"]) for item in plan_data["plan_items"]] == [
        (body["id"], workout.id, None),
    ]
    assert await _orphan_manual_count(session) == 0


async def test_add_without_plan_week_id_to_existing_plan_uses_current_week(session, user: User):
    """#297 — план и неделя уже есть, plan_week_id не передан: строка — в ТЕКУЩЕЙ неделе, новую неделю не плодим."""
    exercise = await _make_exercise(session)
    first = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "count_per_week": 1, "day_of_week": 0},
    )
    second = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "count_per_week": 1, "day_of_week": 4},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["plan_week_id"] is not None
    assert first.json()["plan_week_id"] == second.json()["plan_week_id"]
    plan_data = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")).json()["plan"]
    assert len(plan_data["plan_weeks"]) == 1
    assert len(plan_data["plan_items"]) == 2


async def test_manual_item_appears_in_get_plan_within_plan_week(session, user: User):
    """6. manual item после GET /plan — присутствует в нужной PlanWeek, program_inclusion_id=NULL"""
    exercise = await _make_exercise(session)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    week = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=1, start_date=date(2026, 9, 21), phase=WeekPhase.BASE,
    )

    create_response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={
            "exercise_id": exercise.id, "count_per_week": 4, "day_of_week": 5, "plan_week_id": week.id,
        },
    )
    assert create_response.status_code == 200
    created_item_id = create_response.json()["id"]

    # GET /api/v2/plan должен вернуть созданный item
    plan_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    assert plan_response.status_code == 200
    plan_data = plan_response.json()["plan"]

    assert plan_data is not None
    items = plan_data["plan_items"]
    weeks = plan_data["plan_weeks"]

    assert len(weeks) == 1
    assert weeks[0]["id"] == week.id

    assert len(items) == 4  # issue #304 (AD-4): «4 раза в неделю» = 4 занятия
    item = items[0]
    assert item["id"] == created_item_id
    assert item["plan_week_id"] == week.id
    assert item["program_inclusion_id"] is None
    assert item["day_of_week"] == 5


async def test_legacy_orphan_manual_item_becomes_visible_in_get_plan(session, user: User):
    """#297 — уже существующая «сирота» (ручной PlanItem без недели, создан старым POST) после GET /plan
    лежит в current_week_id: видна, управляема; ничего не удалено, день сохранён."""
    exercise = await _make_exercise(session)
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    orphan = await plans.create_plan_item(
        training_plan_id=plan.id, exercise_id=exercise.id, complex_id=None, count_per_week=1,
        day_of_week=2, week_phase=None, program_inclusion_id=None, plan_week_id=None,
    )
    await session.commit()

    plan_data = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")).json()["plan"]

    assert [(item["id"], item["plan_week_id"], item["day_of_week"]) for item in plan_data["plan_items"]] == [
        (orphan.id, plan_data["current_week_id"], 2),
    ]
    assert await _orphan_manual_count(session) == 0
