from datetime import UTC, datetime
from decimal import Decimal

from app.db.models import User
from app.db.models_program import Exercise
from app.db.repositories.training_sessions import (
    SessionBlockInput,
    SetLogInput,
    TrainingSessionRepository,
)
from app.domain.multi_program import MetricType, SessionSource


async def _make_exercise(session, name: str) -> int:
    exercise = Exercise(name=name, metric_type=MetricType.REPS, category="synthetic")
    session.add(exercise)
    await session.flush()
    return exercise.id


def _reps_block(exercise_id: int, reps: list[int], max_reps: int) -> SessionBlockInput:
    sets = [
        SetLogInput(set_number=i + 1, metric_type=MetricType.REPS, value=Decimal(r), unit="reps")
        for i, r in enumerate(reps)
    ]
    sets.append(
        SetLogInput(
            set_number=len(reps) + 1, metric_type=MetricType.REPS, value=Decimal(max_reps), unit="reps",
            is_max_set=True,
        ),
    )
    return SessionBlockInput(exercise_id=exercise_id, sets=sets)


async def test_create_session_persists_blocks_and_set_logs(session, user: User):
    exercise_a = await _make_exercise(session, "Block A")
    exercise_b = await _make_exercise(session, "Block B")
    repo = TrainingSessionRepository(session)

    created = await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        effort=Decimal("7.5"), comment="ок",
        blocks=[_reps_block(exercise_a, [10, 10, 10], 12), _reps_block(exercise_b, [3, 3, 3, 3], 4)],
    )

    detail = await repo.get_for_user(created.id, user.id)
    assert detail is not None
    assert detail.source == SessionSource.PLAN
    assert detail.effort == Decimal("7.5")
    assert detail.comment == "ок"
    assert [b.exercise_id for b in detail.blocks] == [exercise_a, exercise_b]
    assert [log.value for log in detail.blocks[0].set_logs] == [Decimal(10), Decimal(10), Decimal(10), Decimal(12)]
    assert detail.blocks[0].set_logs[-1].is_max_set is True
    assert detail.blocks[0].set_logs[0].is_max_set is False


async def test_get_for_user_returns_none_for_foreign_session(session, user: User):
    other_user = User(telegram_id=99999998, username="other")
    session.add(other_user)
    await session.flush()
    exercise = await _make_exercise(session, "Solo")
    repo = TrainingSessionRepository(session)
    created = await repo.create_session(
        user_id=other_user.id, source=SessionSource.FREEFORM, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
    )

    assert await repo.get_for_user(created.id, user.id) is None


async def test_list_for_user_orders_by_performed_at_descending(session, user: User):
    exercise = await _make_exercise(session, "Solo")
    repo = TrainingSessionRepository(session)
    await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
    )
    await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
    )

    sessions = await repo.list_for_user(user.id)

    assert [s.performed_at for s in sessions] == [datetime(2026, 1, 3, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)]


async def test_list_for_user_applies_offset_and_limit_as_python_slice(session, user: User):
    """Тот же приём, что GET /api/history (issue #50) — срез уже
    загруженного списка, см. докстринг TrainingSessionRepository.list_for_user."""
    exercise = await _make_exercise(session, "Solo")
    repo = TrainingSessionRepository(session)
    for day in range(1, 6):
        await repo.create_session(
            user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, day, tzinfo=UTC),
            effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
        )

    page = await repo.list_for_user(user.id, limit=2, offset=1)

    assert [s.performed_at.day for s in page] == [4, 3]
