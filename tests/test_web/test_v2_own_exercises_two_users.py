"""Аудит staging 6475bc0, приоритет 2 — собственные упражнения через API под двумя обычными пользователями.

Создание и повторное использование своего упражнения (две тренировки и план — одна строка Exercise, без дублей),
изоляция: чужое упражнение не видно в библиотеке, не прикрепляется к тренировке/плану, не попадает в общий каталог
(«Готовые тренировки»). Чужое — 404, не 403 (конвенция проекта: существование чужого не раскрывается).
Переименования/архивации упражнений в API нет — план в docs/own-exercises.md (нужна миграция)."""

from sqlalchemy import func, select

from app.db.models import User
from app.db.models_program import Exercise
from app.db.repositories.users import UserRepository
from tests.test_web._v2_client import v2_get, v2_post

PROTOCOL = {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 10}, "rest_seconds": 90}


async def _second_user(session, telegram_id: int) -> User:
    return await UserRepository(session).create(telegram_id=telegram_id, username="user_b")


async def _workout(session, telegram_id: int, title: str) -> int:
    response = await v2_post(session, telegram_id=telegram_id, path="/api/v2/workouts", payload={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _add_item(session, telegram_id: int, workout_id: int, exercise_id: int):
    return await v2_post(
        session, telegram_id=telegram_id, path=f"/api/v2/workouts/{workout_id}/items",
        payload={"exercise_id": exercise_id, "protocol": PROTOCOL},
    )


async def test_own_exercise_is_created_once_and_reused_in_workouts_and_plan(session, user: User):
    created = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Узкий хват"})
    assert created.status_code == 200, created.text
    exercise_id = created.json()["id"]

    for title in ("Тяга А", "Тяга Б"):
        added = await _add_item(session, user.telegram_id, await _workout(session, user.telegram_id, title), exercise_id)
        assert added.status_code == 200, added.text
    planned = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise_id, "count_per_week": 1},
    )
    assert planned.status_code == 200, planned.text

    library = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")).json()["exercises"]
    assert [e["id"] for e in library if e["name"] == "Узкий хват"] == [exercise_id]  # одно упражнение, не копии
    owned = (await session.execute(
        select(func.count()).select_from(Exercise).where(Exercise.owner_user_id == user.id),
    )).scalar_one()
    assert owned == 1


async def test_other_user_cannot_see_or_use_own_exercise(session, user: User):
    user_b = await _second_user(session, telegram_id=980_611)
    exercise_id = (await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Секретный хват"},
    )).json()["id"]
    workout_a = await _workout(session, user.telegram_id, "Тренировка А")
    assert (await _add_item(session, user.telegram_id, workout_a, exercise_id)).status_code == 200

    library_b = (await v2_get(session, telegram_id=user_b.telegram_id, path="/api/v2/exercises")).json()["exercises"]
    assert exercise_id not in {e["id"] for e in library_b}
    assert "Секретный хват" not in {e["name"] for e in library_b}

    workout_b = await _workout(session, user_b.telegram_id, "Тренировка Б")
    attach = await _add_item(session, user_b.telegram_id, workout_b, exercise_id)
    assert attach.status_code == 404
    plan = await v2_post(
        session, telegram_id=user_b.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise_id, "count_per_week": 1},
    )
    assert plan.status_code == 404
    # Тренировка А с этим упражнением — тоже чужая: не открывается, не прикрепляется к плану B.
    assert (await v2_get(session, telegram_id=user_b.telegram_id, path=f"/api/v2/workouts/{workout_a}")).status_code == 404
    plan_workout = await v2_post(
        session, telegram_id=user_b.telegram_id, path="/api/v2/plan-items", payload={"complex_id": workout_a, "count_per_week": 1},
    )
    assert plan_workout.status_code == 404
    # Ничего не создалось у B и не изменилось у A.
    assert (await session.get(Exercise, exercise_id)).owner_user_id == user.id


async def test_own_exercise_and_workout_never_reach_the_shared_catalogue(session, user: User):
    user_b = await _second_user(session, telegram_id=980_612)
    exercise_id = (await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Моё каталожное?"},
    )).json()["id"]
    workout_a = await _workout(session, user.telegram_id, "Моя тренировка")
    assert (await _add_item(session, user.telegram_id, workout_a, exercise_id)).status_code == 200

    for viewer in (user.telegram_id, user_b.telegram_id):
        catalogue = (await v2_get(session, telegram_id=viewer, path="/api/v2/workouts/catalog")).json()["workouts"]
        assert workout_a not in {w["id"] for w in catalogue}
    own_list_b = (await v2_get(session, telegram_id=user_b.telegram_id, path="/api/v2/workouts")).json()["workouts"]
    assert workout_a not in {w["id"] for w in own_list_b}
    exercise = await session.get(Exercise, exercise_id)
    assert (exercise.source_type, exercise.visibility) == ("user", "user")
