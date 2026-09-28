"""REBUILD-1, R3 — GET /api/v2/analytics/training: отдельный конвейер, не
зависящий от пагинации Журнала; (exercise, protocol)-агрегация; часовой
пояс пользователя; изоляция пользователей."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Exercise,
    SessionBlock,
    SessionStatus,
    SetLog,
    TrainingSession,
)
from app.domain.multi_program import MetricType, SessionSource
from tests.test_web._v2_client import v2_get
from tests.test_web.test_v2_mixed_workout import _exercise, _user

REPS_ITEM = {"type": "reps_sets", "sets": [{"target_reps": 8}], "rest_seconds": 0}
MAX_ITEM = {"type": "max_effort", "attempts": [{"is_max": True}], "rest_seconds": 0}
INTERVAL_ITEM = {
    "type": "interval", "total_duration_seconds": 60, "work_seconds": 10, "rest_seconds": 20, "starts_with": "work",
}


def _snapshot(items: list[tuple[Exercise, dict]]) -> dict:
    return {
        "workout_id": 1, "title": "Т",
        "items": [
            {"exercise_id": ex.id, "exercise_name": ex.name, "order": i, "protocol": protocol}
            for i, (ex, protocol) in enumerate(items)
        ],
    }


async def _add_session(
    session: AsyncSession, user: User, at: datetime, blocks: list[tuple[Exercise, dict, list[str], dict | None]],
) -> None:
    training = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED, performed_at=at,
        workout_snapshot=_snapshot([(ex, protocol) for ex, protocol, _, _ in blocks]),
    )
    session.add(training)
    await session.flush()
    for index, (exercise, _protocol, values, result) in enumerate(blocks):
        block = SessionBlock(session_id=training.id, order_index=index, exercise_id=exercise.id, result=result)
        session.add(block)
        await session.flush()
        for number, value in enumerate(values, start=1):
            session.add(SetLog(
                session_block_id=block.id, set_number=number, metric_type=MetricType.REPS,
                value=Decimal(value), unit="reps",
            ))


async def _analytics(session: AsyncSession, user: User) -> dict:
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/analytics/training")
    assert response.status_code == 200, response.text
    return response.json()


async def test_more_than_200_sessions_do_not_depend_on_journal_pagination(session: AsyncSession):
    user = await _user(session, 950001)
    pull = await _exercise(session, "Подтягивания")
    now = datetime.now(UTC)
    for i in range(210):
        await _add_session(session, user, now - timedelta(minutes=i + 1), [(pull, REPS_ITEM, ["5", "4"], None)])
    await session.commit()

    data = await _analytics(session, user)
    [exercise] = data["exercises"]
    [panel] = exercise["panels"]

    assert panel["protocol_type"] == "reps_sets"
    assert panel["total_reps"] == str(9 * 210) and panel["set_count"] == 420  # все 210 сессий, не 50/200 Журнала
    assert panel["points_total"] == 210 and len(panel["points"]) == 200
    assert data["activity"]["sessions_last_30_days"] == 210
    assert data["timezone"] == "Europe/Moscow"  # у пользователя пояса нет — проектный дефолт


async def test_mixed_session_counts_once_and_same_exercise_stays_separated(session: AsyncSession):
    user = await _user(session, 950002)
    pull, burpee = await _exercise(session, "Подтягивания"), await _exercise(session, "Бёрпи")
    now = datetime.now(UTC)
    interval_result = {"type": "interval", "actual_duration_seconds": 60, "completed_cycles": 2}
    await _add_session(session, user, now - timedelta(hours=3), [
        (pull, REPS_ITEM, ["8", "8"], None), (burpee, INTERVAL_ITEM, [], interval_result),
        (pull, MAX_ITEM, ["21"], None),
    ])
    await _add_session(session, user, now - timedelta(hours=1), [(pull, MAX_ITEM, ["23"], None)])
    await session.commit()

    data = await _analytics(session, user)
    assert data["activity"]["sessions_last_30_days"] == 2  # смешанная — одна
    by_name = {e["exercise_name"]: {p["protocol_type"]: p for p in e["panels"]} for e in data["exercises"]}

    assert set(by_name["Подтягивания"]) == {"reps_sets", "max_effort"}
    assert by_name["Подтягивания"]["reps_sets"]["total_reps"] == "16"
    assert by_name["Подтягивания"]["max_effort"]["best"] == "23"
    assert [p["is_new_pb"] for p in by_name["Подтягивания"]["max_effort"]["points"]] == [False, True]
    assert by_name["Бёрпи"]["interval"]["cycles"] == 2 and by_name["Бёрпи"]["interval"]["total_reps"] is None


async def test_timezone_of_user_drives_bucketing_and_invalid_falls_back(session: AsyncSession):
    user = await _user(session, 950003)
    user.timezone = "Pacific/Kiritimati"
    pull = await _exercise(session, "Подтягивания")
    now = datetime.now(UTC)
    await _add_session(session, user, now - timedelta(hours=1), [(pull, REPS_ITEM, ["5"], None)])
    await session.commit()
    assert (await _analytics(session, user))["timezone"] == "Pacific/Kiritimati"

    user.timezone = "Not/AZone"
    await session.commit()
    assert (await _analytics(session, user))["timezone"] == "Europe/Moscow"  # невалидный пояс — дефолт, не 500


async def test_other_users_and_active_sessions_are_excluded(session: AsyncSession):
    owner, stranger = await _user(session, 950004), await _user(session, 950005)
    pull = await _exercise(session, "Подтягивания")
    now = datetime.now(UTC)
    await _add_session(session, stranger, now - timedelta(hours=1), [(pull, REPS_ITEM, ["50"], None)])
    await _add_session(session, owner, now - timedelta(hours=2), [(pull, REPS_ITEM, ["5"], None)])
    running = TrainingSession(
        user_id=owner.id, source=SessionSource.PLAN, status=SessionStatus.STARTED, performed_at=now,
        workout_snapshot=_snapshot([(pull, REPS_ITEM)]),
    )
    session.add(running)
    await session.commit()

    data = await _analytics(session, owner)
    assert data["activity"]["sessions_last_30_days"] == 1
    assert data["exercises"][0]["panels"][0]["total_reps"] == "5"
