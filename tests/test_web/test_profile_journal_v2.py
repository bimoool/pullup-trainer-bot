"""#277 (D2) — сводка Профиля учитывает завершённые тренировки Журнала v2, а не только legacy Workout.

Display-only: считаются и legacy, и v2 TrainingSession; перенесённые backfill-ом (#163) не считаются
дважды: legacy Workout — источник правды, backfill-копии v2 исключаются отпечатком (#284)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Exercise, SessionStatus
from app.db.repositories.training_sessions import (
    SessionBlockInput,
    SetLogInput,
    TrainingSessionRepository,
)
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.multi_program import MetricType, SessionSource
from tests.test_web._v2_client import v2_delete
from tests.test_web.test_journal_dedupe import _kwargs, _legacy_user, _migrated_user
from tests.test_web.test_profile import _get_profile


async def _v2_session(
    session: AsyncSession, user, *, at: datetime, exercise_id: int, status: SessionStatus = SessionStatus.COMPLETED,
):
    repo = TrainingSessionRepository(session)
    created = await repo.create_session(
        user_id=user.id, source=SessionSource.BACKDATED, performed_at=at, effort=None, comment=None,
        blocks=[SessionBlockInput(exercise_id=exercise_id, sets=[
            SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(10), unit="reps"),
        ])],
    )
    created.status = status
    await session.flush()
    return created


async def _exercise(session: AsyncSession, user) -> Exercise:
    exercise = Exercise(
        name="Свои подтягивания", metric_type=MetricType.REPS, category="pull_ups", subcategory="x",
        source_type="user", owner_user_id=user.id,
    )
    session.add(exercise)
    await session.flush()
    return exercise


async def test_profile_counts_v2_only_user(session: AsyncSession):
    """Пользователь, у которого все тренировки — v2-сессии (legacy-истории нет)."""
    user = await UserRepository(session).create(telegram_id=983001, username="v2only")
    exercise = await _exercise(session, user)
    now = datetime.now(UTC)
    await _v2_session(session, user, at=now - timedelta(days=5), exercise_id=exercise.id)
    await _v2_session(session, user, at=now - timedelta(days=2), exercise_id=exercise.id)
    # незавершённая (живая) сессия в счёт не идёт и «последней тренировкой» не становится
    await _v2_session(session, user, at=now, exercise_id=exercise.id, status=SessionStatus.STARTED)

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["workouts_count"] == 2
    assert body["days_since_last_workout"] == 2


async def test_profile_without_any_workouts_still_empty(session: AsyncSession):
    user = await UserRepository(session).create(telegram_id=983002, username="nothing")
    exercise = await _exercise(session, user)
    await _v2_session(session, user, at=datetime.now(UTC), exercise_id=exercise.id, status=SessionStatus.STARTED)

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["workouts_count"] == 0
    assert body["days_since_last_workout"] is None


async def test_profile_does_not_double_count_migrated_workouts(session: AsyncSession):
    """3 перенесённые legacy (есть v2-копии) + 1 пост-миграционная legacy = 4, не 7."""
    user, _workout_set, _post = await _migrated_user(session, 983003)

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["workouts_count"] == 4


async def test_profile_deleted_legacy_does_not_resurrect_backfill_copy(session: AsyncSession):
    """Legacy — источник правды (#284): после удаления legacy-записи её backfill-копия не считается."""
    user, _workout_set, _post = await _migrated_user(session, 983005)
    workout = (await WorkoutRepository(session).list_for_user(user.id))[0]
    response = await v2_delete(session, user.telegram_id, f"/api/history/{workout.id}")
    assert response.status_code == 200, response.text

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["workouts_count"] == 3


async def test_profile_mixes_legacy_and_newer_v2_session(session: AsyncSession):
    """Legacy 10 дней назад + более свежая v2-сессия: считаются обе, «последняя» — v2."""
    user, workout_set = await _legacy_user(session, 983004)
    now = datetime.now(UTC)
    await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, now - timedelta(days=10), 11))
    exercise = await _exercise(session, user)
    await _v2_session(session, user, at=now - timedelta(days=1), exercise_id=exercise.id)

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["workouts_count"] == 2
    assert body["days_since_last_workout"] == 1
