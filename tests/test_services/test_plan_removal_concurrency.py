"""#304 B1/B3 — гонки снятия занятий на реальном Postgres (независимые соединения; один AsyncSession
гонки не даёт). Модель локов та же, что у #304: advisory-лок стартов пользователя (lock_user_starts)
сериализует кредит занятия со снятием, лок строки плана (lock_plan) — снятие со сходимостью.

Проверяется: удаление vs старт не теряет кредит и не засчитывает снятое; остановка плана vs сходимость
не оставляет открытых строк; параллельная сходимость не воскрешает снятое занятие."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    CustomPlan,
    Exercise,
    PlanItem,
    PlanWeek,
    TrainingPlan,
    TrainingSession,
)
from app.domain.multi_program import MetricType
from app.services.live_session import LiveSessionService
from app.services.plan_convergence import PlanConvergenceService
from app.services.plan_removal import CreditedPlanItemError, PlanRemovalService

MON = date(2026, 10, 5)
HOLD = 0.3  # держим транзакцию открытой — окно гонки


@asynccontextmanager
async def _own_session(dsn: str):
    engine = create_async_engine(dsn)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as db:
            yield db
    finally:
        await engine.dispose()


async def _seed(session, user: User, *, weeks: list[int], until_week: int = 1) -> tuple[int, int]:
    user.timezone = "UTC"
    plan = TrainingPlan(user_id=user.id, created_at=datetime(2026, 10, 5, 8, tzinfo=UTC))
    session.add(plan)
    exercise = Exercise(name="Отжимания race", metric_type=MetricType.REPS, category="Общая")
    session.add(exercise)
    await session.flush()
    workout = Complex(name="Своя race", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=0, sets=3, target_value=10))
    custom = CustomPlan(
        user_id=user.id, training_plan_id=plan.id, display_name="race", start_week_number=1,
        workouts=[workout.id], weeks=weeks, repeat="once", preferred_weekdays=None, is_active=True,
    )
    session.add(custom)
    await session.flush()
    await PlanConvergenceService(session).converge_user_plan(
        training_plan_id=plan.id, today=MON, create_until_week=until_week,
    )
    await session.commit()
    return plan.id, custom.id


async def _rows(dsn: str, custom_id: int) -> list[tuple]:
    async with _own_session(dsn) as db:
        return [tuple(row) for row in (await db.execute(
            select(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.status, PlanItem.id)
            .join(PlanWeek, PlanWeek.id == PlanItem.origin_plan_week_id)
            .where(PlanItem.custom_plan_id == custom_id)
            .order_by(PlanWeek.week_number, PlanItem.occurrence_index, PlanItem.id),
        )).all()]


async def _credits(dsn: str, user_id: int) -> list[int | None]:
    async with _own_session(dsn) as db:
        return list((await db.execute(
            select(TrainingSession.plan_item_id).where(TrainingSession.user_id == user_id),
        )).scalars().all())


async def test_delete_waits_for_concurrent_crediting_start_and_refuses(session, user: User, test_dsn):
    _, custom_id = await _seed(session, user, weeks=[2])
    occurrence = (await _rows(test_dsn, custom_id))[0][3]
    started = asyncio.Event()

    async def start() -> None:
        async with _own_session(test_dsn) as db:
            await LiveSessionService(db).start_session(
                user_id=user.id, client_session_id=uuid.uuid4(), plan_item_ids=[occurrence],
            )
            started.set()
            await asyncio.sleep(HOLD)
            await db.commit()

    async def remove() -> None:
        await started.wait()
        async with _own_session(test_dsn) as db:
            with pytest.raises(CreditedPlanItemError):
                await PlanRemovalService(db).remove_plan_item(user_id=user.id, plan_item_id=occurrence)
            await db.rollback()

    await asyncio.gather(start(), remove())
    assert await _credits(test_dsn, user.id) == [occurrence]
    assert (await _rows(test_dsn, custom_id))[0][2] == "open"


async def test_start_after_concurrent_removal_sees_removed_occurrence(session, user: User, test_dsn):
    _, custom_id = await _seed(session, user, weeks=[2])
    occurrence = (await _rows(test_dsn, custom_id))[0][3]
    removed = asyncio.Event()

    async def remove() -> None:
        async with _own_session(test_dsn) as db:
            await PlanRemovalService(db).remove_plan_item(user_id=user.id, plan_item_id=occurrence)
            removed.set()
            await asyncio.sleep(HOLD)
            await db.commit()

    async def start() -> None:
        await removed.wait()
        async with _own_session(test_dsn) as db:
            with pytest.raises(ValueError):
                await LiveSessionService(db).start_session(
                    user_id=user.id, client_session_id=uuid.uuid4(), plan_item_ids=[occurrence],
                )
            await db.rollback()

    await asyncio.gather(remove(), start())
    assert await _credits(test_dsn, user.id) == []
    assert (await _rows(test_dsn, custom_id))[0][2] == "removed"


async def _drop_week_rows(session, custom_id: int, week_number: int) -> None:
    """Неделя есть, её занятий ещё нет — сходимости есть что материализовать (окно гонки)."""
    week_ids = select(PlanWeek.id).where(PlanWeek.week_number == week_number)
    await session.execute(delete(PlanItem).where(
        PlanItem.custom_plan_id == custom_id, PlanItem.origin_plan_week_id.in_(week_ids),
    ))
    await session.commit()


@pytest.mark.parametrize("first", ["deactivate", "converge"])
async def test_deactivate_vs_converge_leaves_no_open_rows(session, user: User, test_dsn, first):
    plan_id, custom_id = await _seed(session, user, weeks=[1, 1, 1], until_week=3)
    await _drop_week_rows(session, custom_id, 2)
    holding = asyncio.Event()

    async def deactivate() -> None:
        if first != "deactivate":
            await holding.wait()
        async with _own_session(test_dsn) as db:
            await PlanRemovalService(db).deactivate_custom_plan(user_id=user.id, custom_plan_id=custom_id, today=MON)
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

    await asyncio.gather(deactivate(), converge())
    rows = await _rows(test_dsn, custom_id)
    assert rows and all(status == "removed" for _, _, status, _ in rows), rows
    async with _own_session(test_dsn) as db:
        await PlanConvergenceService(db).converge_user_plan(training_plan_id=plan_id, today=MON)
        await db.commit()
    assert await _rows(test_dsn, custom_id) == rows


@pytest.mark.parametrize("first", ["remove", "converge"])
async def test_remove_vs_converge_never_regenerates(session, user: User, test_dsn, first):
    plan_id, custom_id = await _seed(session, user, weeks=[2])
    occurrence = (await _rows(test_dsn, custom_id))[1][3]
    holding = asyncio.Event()

    async def remove() -> None:
        if first != "remove":
            await holding.wait()
        async with _own_session(test_dsn) as db:
            await PlanRemovalService(db).remove_plan_item(user_id=user.id, plan_item_id=occurrence)
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

    await asyncio.gather(remove(), converge())

    async def converge_once() -> None:
        async with _own_session(test_dsn) as db:
            await PlanConvergenceService(db).converge_user_plan(training_plan_id=plan_id, today=MON)
            await asyncio.sleep(0.1)
            await db.commit()

    await asyncio.gather(converge_once(), converge_once(), converge_once())
    rows = await _rows(test_dsn, custom_id)
    assert [(index, status) for _, index, status, _ in rows] == [(1, "open"), (2, "removed")]
    assert rows[1][3] == occurrence
