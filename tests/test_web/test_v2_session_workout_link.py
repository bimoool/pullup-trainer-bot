"""#281 — SessionResponse.workout_id: ссылка «Открыть тренировку» из Журнала только на живую свою тренировку."""

from datetime import UTC, datetime

from app.db.models import User
from app.db.models_program import SessionStatus, TrainingSession
from app.db.repositories.users import UserRepository
from app.domain.multi_program import SessionSource
from tests.test_web._v2_client import v2_delete, v2_get, v2_post


async def _workout(session, user: User, title: str = "Моя") -> int:
    response = await v2_post(session, user.telegram_id, "/api/v2/workouts", {"title": title})
    return response.json()["id"]


async def _completed(session, user: User, workout_id: int | None) -> TrainingSession:
    snapshot = None if workout_id is None else {"workout_id": workout_id, "title": "x", "items": []}
    training = TrainingSession(
        user_id=user.id, source=SessionSource.FREEFORM, status=SessionStatus.COMPLETED,
        performed_at=datetime.now(UTC), workout_snapshot=snapshot,
    )
    session.add(training)
    await session.flush()
    return training


async def _journal(session, user: User) -> dict[int, dict]:
    response = await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")
    assert response.status_code == 200
    return {item["id"]: item for item in response.json()["sessions"]}


async def test_workout_id_is_set_for_own_live_workout_only(session, user: User):
    own = await _workout(session, user)
    linked = await _completed(session, user, own)
    without_snapshot = await _completed(session, user, None)

    sessions = await _journal(session, user)
    assert sessions[linked.id]["workout_id"] == own
    assert sessions[without_snapshot.id]["workout_id"] is None


async def test_workout_id_hidden_for_foreign_and_deleted_workouts(session, user: User):
    other = await UserRepository(session).create(telegram_id=777_281, username="other281")
    foreign_workout = await _workout(session, other)
    foreign_ref = await _completed(session, user, foreign_workout)
    deleted_workout = await _workout(session, user, "Удалю")
    deleted_ref = await _completed(session, user, deleted_workout)
    assert (await v2_delete(session, user.telegram_id, f"/api/v2/workouts/{deleted_workout}")).status_code in (200, 204)

    sessions = await _journal(session, user)
    assert sessions[foreign_ref.id]["workout_id"] is None
    assert sessions[deleted_ref.id]["workout_id"] is None
