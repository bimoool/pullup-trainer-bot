"""#304 блокер F — гонки удаления (архивирования) тренировки своего плана на реальном Postgres
(независимые соединения). Модель локов — та же, что принята в #304: удаление тренировки берёт лок
стартов пользователя (lock_user_starts), затем строку плана (lock_plan) и архивирует в той же
транзакции; сходимость — только lock_plan; старт — только lock_user_starts.

Проверяется в обоих порядках: удаление vs сходимость не воскрешает открытое занятие удалённой
тренировки и не плодит дубли; удаление vs старт — либо кредит сохранён (старт первым), либо старт
архивной тренировки отклонён (удаление первым); повторная сходимость ничего не меняет."""

import asyncio
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    CustomPlan,
    Exercise,
    PlanItem,
    PlanWeek,
    TrainingPlan,
)
from app.db.repositories.programs import ProgramRepository
from app.domain.multi_program import MetricType
from app.services.live_session import STALE_PLAN_ITEM_MESSAGE, LiveSessionService
from app.services.plan_convergence import PlanConvergenceService
from app.services.plan_removal import PlanRemovalService
from tests.test_services.test_plan_removal_concurrency import (
    HOLD,
    _credits,
    _drop_week_rows,
    _own_session,
)

MON = date(2026, 10, 5)


async def _seed(session, user: User, *, names: list[str], weeks: list[int], until_week: int) -> tuple[int, int, list[int]]:
    user.timezone = "UTC"
    plan = TrainingPlan(user_id=user.id, created_at=datetime(2026, 10, 5, 8, tzinfo=UTC))
    session.add(plan)
    await session.flush()
    workout_ids = []
    for name in names:
        exercise = Exercise(name=f"race {name}", metric_type=MetricType.REPS, category="Общая")
        session.add(exercise)
        await session.flush()
        workout = Complex(name=name, source_type="user", owner_user_id=user.id)
        session.add(workout)
        await session.flush()
        session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=3, target_value=10))
        workout_ids.append(workout.id)
    custom = CustomPlan(
        user_id=user.id, training_plan_id=plan.id, display_name="race F", start_week_number=1,
        workouts=workout_ids, weeks=weeks, repeat="cycle", preferred_weekdays=None, is_active=True,
    )
    session.add(custom)
    await session.flush()
    await PlanConvergenceService(session).converge_user_plan(
        training_plan_id=plan.id, today=MON, create_until_week=until_week,
    )
    await session.commit()
    return plan.id, custom.id, workout_ids


async def _rows(dsn: str, custom_id: int) -> list[tuple]:
    async with _own_session(dsn) as db:
        return [tuple(row) for row in (await db.execute(
            select(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.workout_definition_id, PlanItem.status, PlanItem.id)
            .join(PlanWeek, PlanWeek.id == PlanItem.origin_plan_week_id)
            .where(PlanItem.custom_plan_id == custom_id)
            .order_by(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.id),
        )).all()]


async def _is_active(dsn: str, custom_id: int) -> bool:
    async with _own_session(dsn) as db:
        return (await db.execute(select(CustomPlan.is_active).where(CustomPlan.id == custom_id))).scalar_one()


async def _delete_workout(db, user_id: int, workout_id: int) -> None:
    """Тот же порядок, что DELETE /api/v2/workouts/{id}: снятие строк под локами, затем архив."""
    await PlanRemovalService(db).remove_workout_items(user_id=user_id, complex_id=workout_id, today=MON)
    workout = await ProgramRepository(db).get_editable_workout_for_user(workout_id, user_id)
    await ProgramRepository(db).archive_workout(workout)


async def _converge(dsn: str, plan_id: int) -> None:
    async with _own_session(dsn) as db:
        await PlanConvergenceService(db).converge_user_plan(training_plan_id=plan_id, today=MON)
        await db.commit()


@pytest.mark.parametrize("names", [["W1", "W2"], ["W1"]], ids=["two-workouts", "single-workout"])
@pytest.mark.parametrize("first", ["delete", "converge"])
async def test_delete_workout_vs_converge_no_resurrection_no_duplicates(session, user: User, test_dsn, first, names):
    plan_id, custom_id, workout_ids = await _seed(session, user, names=names, weeks=[2, 2, 2], until_week=3)
    w1 = workout_ids[0]
    await _drop_week_rows(session, custom_id, 2)  # сходимости есть что материализовать — окно гонки
    holding = asyncio.Event()

    async def delete() -> None:
        if first != "delete":
            await holding.wait()
        async with _own_session(test_dsn) as db:
            await _delete_workout(db, user.id, w1)
            holding.set()
            await asyncio.sleep(HOLD)
            await db.commit()

    async def converge() -> None:
        if first != "converge":
            await holding.wait()
        async with _own_session(test_dsn) as db:
            await PlanConvergenceService(db).converge_user_plan(training_plan_id=plan_id, today=MON)
            holding.set()
            await asyncio.sleep(HOLD)
            await db.commit()

    await asyncio.gather(delete(), converge())
    rows = await _rows(test_dsn, custom_id)
    assert not [row for row in rows if row[2] == w1 and row[3] != "removed"], rows  # W1 не воскресла
    assert len({(week, index) for week, index, *_ in rows}) == len(rows)  # без дублей идентичности
    assert await _is_active(test_dsn, custom_id) is (len(names) > 1)

    await asyncio.gather(_converge(test_dsn, plan_id), _converge(test_dsn, plan_id))
    await _converge(test_dsn, plan_id)
    settled = await _rows(test_dsn, custom_id)
    await _converge(test_dsn, plan_id)
    assert await _rows(test_dsn, custom_id) == settled  # повторная сходимость — 0 изменений
    assert not [row for row in settled if row[2] == w1 and row[3] != "removed"]
    assert len({(week, index) for week, index, *_ in settled}) == len(settled)


async def test_start_first_then_delete_workout_keeps_credit(session, user: User, test_dsn):
    _, custom_id, (w1, _) = await _seed(session, user, names=["W1", "W2"], weeks=[2], until_week=1)
    occurrence = next(row[4] for row in await _rows(test_dsn, custom_id) if row[2] == w1)
    started = asyncio.Event()

    async def start() -> None:
        async with _own_session(test_dsn) as db:
            await LiveSessionService(db).start_session(
                user_id=user.id, client_session_id=uuid.uuid4(), plan_item_ids=[occurrence],
            )
            started.set()
            await asyncio.sleep(HOLD)
            await db.commit()

    async def delete() -> None:
        await started.wait()
        async with _own_session(test_dsn) as db:
            await _delete_workout(db, user.id, w1)
            await db.commit()

    await asyncio.gather(start(), delete())
    assert await _credits(test_dsn, user.id) == [occurrence]
    row = next(row for row in await _rows(test_dsn, custom_id) if row[4] == occurrence)
    assert row[3] == "open"  # засчитанная строка — история, не снята


async def test_delete_workout_first_then_start_is_rejected(session, user: User, test_dsn):
    _, custom_id, (w1, _) = await _seed(session, user, names=["W1", "W2"], weeks=[2], until_week=1)
    occurrence = next(row[4] for row in await _rows(test_dsn, custom_id) if row[2] == w1)
    deleted = asyncio.Event()

    async def delete() -> None:
        async with _own_session(test_dsn) as db:
            await _delete_workout(db, user.id, w1)
            deleted.set()
            await asyncio.sleep(HOLD)
            await db.commit()

    async def start() -> None:
        await deleted.wait()
        async with _own_session(test_dsn) as db:
            with pytest.raises(ValueError, match=STALE_PLAN_ITEM_MESSAGE):
                await LiveSessionService(db).start_session(
                    user_id=user.id, client_session_id=uuid.uuid4(), plan_item_ids=[occurrence],
                )
            await db.rollback()

    await asyncio.gather(delete(), start())
    assert await _credits(test_dsn, user.id) == []
    assert next(row for row in await _rows(test_dsn, custom_id) if row[4] == occurrence)[3] == "removed"
