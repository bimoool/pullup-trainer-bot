"""GET /api/v2/workouts/{id}/sessions — история одной тренировки (Workout Detail)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import User
from app.db.models_program import Exercise, SessionBlock, SessionStatus, SetLog, TrainingSession
from app.domain.multi_program import MetricType, SessionSource
from tests.test_web._v2_client import v2_get, v2_post


async def _workout(session, user: User, title: str = "Моя") -> int:
    response = await v2_post(session, user.telegram_id, "/api/v2/workouts", {"title": title})
    return response.json()["id"]


async def _session(
    session, user: User, workout_id: int | None, *, days_ago: int, status: SessionStatus = SessionStatus.COMPLETED,
    sets: int = 3,
) -> TrainingSession:
    exercise = Exercise(name=f"Упр {days_ago}", metric_type=MetricType.REPS, category="test")
    session.add(exercise)
    await session.flush()
    snapshot = None if workout_id is None else {"workout_id": workout_id, "title": "x", "items": []}
    training = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=status,
        performed_at=datetime.now(UTC) - timedelta(days=days_ago), workout_snapshot=snapshot,
    )
    session.add(training)
    await session.flush()
    block = SessionBlock(session_id=training.id, order_index=0, exercise_id=exercise.id)
    session.add(block)
    await session.flush()
    for number in range(1, sets + 1):
        session.add(SetLog(
            session_block_id=block.id, set_number=number, is_max_set=False, metric_type=MetricType.REPS,
            value=Decimal(8), unit="reps",
        ))
    await session.flush()
    return training


async def test_empty_history(session, user: User):
    workout_id = await _workout(session, user)
    response = await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout_id}/sessions")
    assert response.status_code == 200
    assert response.json() == {"sessions": []}


async def test_lists_only_completed_sessions_of_this_workout_newest_first(session, user: User):
    workout_id = await _workout(session, user)
    other_id = await _workout(session, user, "Другая")
    older = await _session(session, user, workout_id, days_ago=5)
    newer = await _session(session, user, workout_id, days_ago=1, sets=2)
    await _session(session, user, other_id, days_ago=2)
    await _session(session, user, None, days_ago=3)
    await _session(session, user, workout_id, days_ago=4, status=SessionStatus.STARTED)

    response = await v2_get(session, user.telegram_id, f"/api/v2/workouts/{workout_id}/sessions")
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert [s["id"] for s in sessions] == [newer.id, older.id]
    assert sessions[0]["exercises_count"] == 1
    assert sessions[0]["sets_done"] == 2
    assert sessions[1]["sets_done"] == 3


async def test_foreign_workout_is_404_and_foreign_sessions_hidden(session, user: User):
    from app.db.repositories.users import UserRepository

    other = await UserRepository(session).create(telegram_id=777_001, username="other")
    foreign_workout = await _workout(session, other)
    await _session(session, other, foreign_workout, days_ago=1)
    response = await v2_get(session, user.telegram_id, f"/api/v2/workouts/{foreign_workout}/sessions")
    assert response.status_code == 404

    missing = await v2_get(session, user.telegram_id, "/api/v2/workouts/99999999/sessions")
    assert missing.status_code == 404
