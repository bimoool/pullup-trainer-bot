"""/api/v2/favorites — Избранное: тренировки и программы (issue #272)."""

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import Complex, Program, ProgramStructureType, UserFavorite
from app.db.repositories.users import UserRepository
from tests.test_web._v2_client import v2_delete, v2_get, v2_post, v2_put


async def _workout(session, user: User, title: str = "Моя") -> int:
    response = await v2_post(session, user.telegram_id, "/api/v2/workouts", {"title": title})
    return response.json()["id"]


async def _program(session, name: str = "Курс") -> int:
    program = Program(name=name, goal="сила", structure_type=ProgramStructureType.RECURRING, config={})
    session.add(program)
    await session.flush()
    return program.id


async def _list(session, user: User) -> list[dict]:
    response = await v2_get(session, user.telegram_id, "/api/v2/favorites")
    assert response.status_code == 200
    return response.json()["favorites"]


async def test_empty_by_default(session, user: User):
    assert await _list(session, user) == []


async def test_put_is_idempotent_and_lists_workout_and_program(session, user: User):
    workout_id = await _workout(session, user, "Спина")
    program_id = await _program(session, "Подтягивания")
    for _ in range(2):
        assert (await v2_put(session, user.telegram_id, f"/api/v2/favorites/workout/{workout_id}")).status_code == 204
    assert (await v2_put(session, user.telegram_id, f"/api/v2/favorites/program/{program_id}")).status_code == 204

    favorites = await _list(session, user)
    assert [(f["target_type"], f["target_id"], f["title"]) for f in favorites] == [
        ("program", program_id, "Подтягивания"), ("workout", workout_id, "Спина"),
    ]
    rows = (await session.execute(select(UserFavorite))).scalars().all()
    assert len(rows) == 2


async def test_delete_is_idempotent(session, user: User):
    workout_id = await _workout(session, user)
    await v2_put(session, user.telegram_id, f"/api/v2/favorites/workout/{workout_id}")
    for _ in range(2):
        response = await v2_delete(session, user.telegram_id, f"/api/v2/favorites/workout/{workout_id}")
        assert response.status_code == 204
    assert await _list(session, user) == []


async def test_other_users_workout_and_missing_targets_are_404(session, user: User):
    other = await UserRepository(session).create(telegram_id=2002, username="other")
    foreign_id = await _workout(session, other)
    assert (await v2_put(session, user.telegram_id, f"/api/v2/favorites/workout/{foreign_id}")).status_code == 404
    assert (await v2_put(session, user.telegram_id, "/api/v2/favorites/workout/999999")).status_code == 404
    assert (await v2_put(session, user.telegram_id, "/api/v2/favorites/program/999999")).status_code == 404
    assert (await v2_put(session, user.telegram_id, "/api/v2/favorites/exercise/1")).status_code == 404
    assert (await v2_delete(session, user.telegram_id, "/api/v2/favorites/exercise/1")).status_code == 404
    assert (await session.execute(select(UserFavorite))).scalars().all() == []


async def test_system_workout_is_not_favoritable(session, user: User):
    system = Complex(name="Системная", source_type="system")
    session.add(system)
    await session.flush()
    assert (await v2_put(session, user.telegram_id, f"/api/v2/favorites/workout/{system.id}")).status_code == 404


async def test_favorites_are_per_user(session, user: User):
    other = await UserRepository(session).create(telegram_id=2002, username="other")
    program_id = await _program(session)
    await v2_put(session, user.telegram_id, f"/api/v2/favorites/program/{program_id}")
    assert await _list(session, other) == []


async def test_deleted_target_drops_out_of_list(session, user: User):
    workout_id = await _workout(session, user)
    await v2_put(session, user.telegram_id, f"/api/v2/favorites/workout/{workout_id}")
    workout = await session.get(Complex, workout_id)
    await session.delete(workout)
    await session.flush()
    assert await _list(session, user) == []
