"""ActiveTimerRepository (issue #59, волна 1) — один активный таймер на
пользователя, замена при повторном старте, ленивый расчёт "сколько
осталось" на стороне вызывающего кода (см. app/web/routes.py::
_timer_status_response), здесь проверяется только хранение/замена."""

from datetime import UTC, datetime, timedelta

from app.db.models import ActiveTimerType, User
from app.db.repositories.active_timers import ActiveTimerRepository
from app.db.repositories.users import UserRepository


async def test_start_creates_new_timer(session, user: User):
    repo = ActiveTimerRepository(session)
    now = datetime.now(UTC)

    timer = await repo.start(
        user_id=user.id, timer_type=ActiveTimerType.REST_BETWEEN_SETS,
        started_at=now, duration_seconds=90, block_letter="A", set_number=2,
    )

    assert timer.timer_type == ActiveTimerType.REST_BETWEEN_SETS
    assert timer.duration_seconds == 90
    assert timer.block_letter == "A"
    assert timer.set_number == 2


async def test_start_replaces_existing_timer_for_same_user(session, user: User):
    repo = ActiveTimerRepository(session)
    first_start = datetime.now(UTC) - timedelta(seconds=30)
    await repo.start(
        user_id=user.id, timer_type=ActiveTimerType.REST_BETWEEN_SETS,
        started_at=first_start, duration_seconds=60, block_letter="A", set_number=1,
    )

    second_start = datetime.now(UTC)
    replaced = await repo.start(
        user_id=user.id, timer_type=ActiveTimerType.BIG_BREAK,
        started_at=second_start, duration_seconds=180, block_letter=None, set_number=None,
    )

    fetched = await repo.get_for_user(user.id)
    assert fetched is not None
    assert fetched.id == replaced.id
    assert fetched.timer_type == ActiveTimerType.BIG_BREAK
    assert fetched.duration_seconds == 180
    assert fetched.block_letter is None
    assert fetched.started_at == second_start


async def test_get_for_user_returns_none_when_no_timer(session, user: User):
    repo = ActiveTimerRepository(session)
    assert await repo.get_for_user(user.id) is None


async def test_delete_for_user_removes_timer(session, user: User):
    repo = ActiveTimerRepository(session)
    await repo.start(
        user_id=user.id, timer_type=ActiveTimerType.REST_BETWEEN_SETS,
        started_at=datetime.now(UTC), duration_seconds=60,
    )

    await repo.delete_for_user(user.id)

    assert await repo.get_for_user(user.id) is None


async def test_delete_for_user_is_idempotent_when_no_timer(session, user: User):
    repo = ActiveTimerRepository(session)
    await repo.delete_for_user(user.id)  # не должно бросить исключение


async def test_timers_are_scoped_per_user(session, user: User):
    other_user = await _make_other_user(session)
    repo = ActiveTimerRepository(session)
    await repo.start(
        user_id=user.id, timer_type=ActiveTimerType.REST_BETWEEN_SETS,
        started_at=datetime.now(UTC), duration_seconds=60,
    )

    assert await repo.get_for_user(other_user.id) is None


async def _make_other_user(session) -> User:
    return await UserRepository(session).create(telegram_id=2002, username="other")
