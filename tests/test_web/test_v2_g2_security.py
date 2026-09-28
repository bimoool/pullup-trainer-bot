"""REBUILD-1, R4 — G2: публичный POST /plan-items не привязывает к плану
чужое/внутреннее по id; GET /workouts — только свои Workout с items и без
N+1."""

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import Complex, ComplexItem, Exercise, PlanItem
from app.domain.multi_program import MetricType
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_mixed_workout import REPS, _exercise, _user


async def _plan_item_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(PlanItem))


async def _workout(session: AsyncSession, owner: User | None, title: str, *, source_type: str = "user") -> Complex:
    workout = Complex(name=title, source_type=source_type, owner_user_id=owner.id if owner else None)
    session.add(workout)
    await session.flush()
    exercise = await _exercise(session, f"Упр. {title}")
    session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=1, protocol=REPS))
    await session.flush()
    return workout


async def _post_plan_item(session: AsyncSession, user: User, **payload):
    return await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"count_per_week": 1, **payload},
    )


async def test_public_plan_items_deny_foreign_and_internal_objects_without_side_effects(session: AsyncSession):
    owner, attacker = await _user(session, 960001), await _user(session, 960002)
    private_workout = await _workout(session, owner, "Приватная")
    system_complex = await _workout(session, None, "Программный комплекс", source_type="system")
    foreign_exercise = Exercise(
        name="Чужое", metric_type=MetricType.REPS, category="user", source_type="user", owner_user_id=owner.id,
    )
    step_role = Exercise(
        name="Подтягивания — объём", metric_type=MetricType.REPS, category="pullups", subcategory="block_a",
    )
    session.add_all([foreign_exercise, step_role])
    await session.flush()
    await session.commit()

    attempts = [
        {"complex_id": private_workout.id},  # чужой приватный Workout
        {"complex_id": system_complex.id},  # системный/программный Complex — не публичный
        {"exercise_id": foreign_exercise.id},  # чужое пользовательское упражнение
        {"exercise_id": step_role.id},  # внутренняя STEP-роль
        {"complex_id": 999_999},
        {"exercise_id": 999_999},
    ]
    responses = [await _post_plan_item(session, attacker, **payload) for payload in attempts]

    assert [r.status_code for r in responses] == [404] * 6
    # Не перечисляет: чужое и несуществующее неразличимы по тексту.
    assert responses[0].json() == responses[4].json()
    assert responses[2].json() == responses[5].json()
    assert await _plan_item_count(session) == 0  # частичных PlanItem нет


async def test_public_plan_items_allow_own_workout_own_exercise_and_system_exercise(session: AsyncSession):
    owner = await _user(session, 960003)
    workout = await _workout(session, owner, "Своя")
    own_exercise = Exercise(
        name="Моё", metric_type=MetricType.REPS, category="user", source_type="user", owner_user_id=owner.id,
    )
    system_exercise = Exercise(name="Каталожное", metric_type=MetricType.REPS, category="pull")
    session.add_all([own_exercise, system_exercise])
    await session.flush()
    await session.commit()

    for payload in ({"complex_id": workout.id}, {"exercise_id": own_exercise.id}, {"exercise_id": system_exercise.id}):
        response = await _post_plan_item(session, owner, **payload)
        assert response.status_code == 200, response.text
    assert await _plan_item_count(session) == 3


async def test_my_workouts_are_own_user_workouts_with_items_and_no_n_plus_one(session: AsyncSession):
    owner, other = await _user(session, 960004), await _user(session, 960005)
    mine = [await _workout(session, owner, f"Моя {i}") for i in range(4)]
    await _workout(session, other, "Чужая")
    await _workout(session, None, "Системная", source_type="system")
    weird = await _workout(session, owner, "Владелец есть, но system", source_type="system")
    await session.commit()

    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _count)
    try:
        response = await v2_get(session, telegram_id=owner.telegram_id, path="/api/v2/workouts")
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert response.status_code == 200
    workouts = response.json()["workouts"]
    assert [w["id"] for w in workouts] == [w.id for w in mine]  # только source_type=user И owner=я
    assert weird.id not in [w["id"] for w in workouts]
    assert all(len(w["items"]) == 1 and w["items"][0]["exercise_name"].startswith("Упр.") for w in workouts)
    assert workouts[0]["items"][0]["protocol"]["type"] == "reps_sets"
    # Запросов не больше константы: user, workouts, items, exercises (+ служебные), а не по N.
    assert len(statements) <= 6, statements
