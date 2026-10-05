"""#284 — CSV-экспорт не дублирует перенесённую backfill-ом историю: v2-копию отбрасывает тот же отпечаток,
что и Журнал (TrainingSessionRepository._backfilled_fingerprint); перенесённую тренировку отдаёт legacy-строка.
Копии создаются НАСТОЯЩИМИ функциями backfill (см. test_journal_dedupe.py)."""

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.services.history_export import build_rows
from tests.test_web.test_journal_dedupe import (
    _EXERCISE_BLOCK_A_NAME,
    BASE,
    _create_training_session_for_elective,
    _get_or_create_exercise,
    _live_flow_session,
    _migrated_user,
)


async def _rows(session: AsyncSession, user) -> list[list[str]]:
    return await build_rows(session, user_id=user.id, timezone="UTC")


def _date(offset_hours: int) -> str:
    return (BASE + timedelta(hours=offset_hours)).strftime("%Y-%m-%d %H:%M")


async def test_migrated_workouts_appear_exactly_once_in_csv(session: AsyncSession):
    user, _workout_set, _post = await _migrated_user(session, 983001)
    rows = await _rows(session, user)

    assert not [r for r in rows if r[0] == "v2"]  # все три перенесённые записи — backfill-копии
    legacy = [r for r in rows if r[0] == "legacy"]
    # каждая из четырёх тренировок (3 перенесённых + пост-миграционная) — только legacy-строками, по одному разу
    for hours in (0, 1, 2, 3):
        assert len([r for r in legacy if r[1] == _date(hours) and r[4] == "a"]) == 3
        assert len([r for r in legacy if r[1] == _date(hours) and r[4] == "b"]) == (0 if hours == 2 else 4)  # 2 — свободная
    assert len(rows) == 7 + 7 + 3 + 7
    # пост-миграционная запись (без v2-копии) на месте
    assert any(r[1] == _date(3) for r in legacy)


async def test_elective_and_live_session_at_identical_timestamp_stay_in_csv(session: AsyncSession):
    user, _workout_set, _post = await _migrated_user(session, 983002)
    block_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    live = await _live_flow_session(session, user, exercise_id=block_a.id, workout_snapshot=None, activity_type=None)
    live.client_session_id = uuid.uuid4()  # живой старт — не backfill
    elective = ElectiveWorkout(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=BASE + timedelta(hours=5),
        reps_sequence=[4, 3, 2], total_reps=9, equipment_type=EquipmentType.BAND, equipment_value=Decimal("15.0"),
    )
    session.add(elective)
    await session.flush()
    elective_exercise = await _get_or_create_exercise(
        session, name="Факультатив: 3 минуты", subcategory="elective_three_minutes",
    )
    await _create_training_session_for_elective(session, elective, exercise_id=elective_exercise.id)
    await session.flush()

    rows = await _rows(session, user)
    v2 = [r for r in rows if r[0] == "v2"]
    assert len([r for r in v2 if r[1] == _date(0)]) == 1  # живая сессия в тот же момент, что legacy-копия
    assert len([r for r in v2 if r[1] == _date(5)]) == 1  # электив (#279) — одна строка
    assert len(v2) == 2
    # legacy-строки по-прежнему по одной на подход
    assert len([r for r in rows if r[0] == "legacy" and r[1] == _date(0) and r[4] == "a"]) == 3
