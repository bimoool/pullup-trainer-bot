"""#283 — гонки недель плана на реальном Postgres: независимые соединения
(один AsyncSession гонки не даёт). Создание недели — INSERT ... ON CONFLICT DO
NOTHING + повторное чтение; материализация и copy-to-next сериализуются локом
строки плана, поэтому параллельные вызовы не дублируют PlanItem."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import User
from app.db.models_program import Exercise, PlanItem, PlanWeek
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import MetricType, WeekPhase
from app.services.plan_week import PlanWeekService
from tests.test_services.test_plan_week_service import (
    _make_plan_with_inclusion,
    _make_recurring_program,
)

MONDAY = date(2026, 9, 21)  # совпадает с created_at плана из _make_plan_with_inclusion


@asynccontextmanager
async def _own_session(dsn: str):
    engine = create_async_engine(dsn)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as db:
            yield db
    finally:
        await engine.dispose()


async def _count(dsn: str, stmt) -> int:
    async with _own_session(dsn) as db:
        return (await db.execute(stmt)).scalar_one()


async def _seed_plan(session, user: User) -> int:
    program, items = await _make_recurring_program(session, category="race283")
    plan = await _make_plan_with_inclusion(session, user, program, program_items=items)
    await session.commit()
    return plan.id


async def test_create_plan_week_conflict_returns_existing_row(session, user: User):
    """Детерминированный путь конфликта: строка недели уже есть."""
    plan_id = await _seed_plan(session, user)
    repo = TrainingPlanRepository(session)
    first = await repo.create_plan_week(training_plan_id=plan_id, week_number=3, start_date=MONDAY, phase=WeekPhase.BASE)
    again = await repo.create_plan_week(training_plan_id=plan_id, week_number=3, start_date=MONDAY, phase=WeekPhase.BASE)
    assert again.id == first.id


async def test_concurrent_ensure_current_does_not_duplicate_program_items(session, user: User, test_dsn):
    plan_id = await _seed_plan(session, user)
    # Неделя уже есть: иначе INSERT ... ON CONFLICT сам сериализует вызовы на unique-индексе
    # и гонку за PlanItem не воспроизвести — именно её закрывает лок плана.
    await TrainingPlanRepository(session).create_plan_week(
        training_plan_id=plan_id, week_number=1, start_date=MONDAY, phase=WeekPhase.BASE,
    )
    await session.commit()

    async def call() -> int:
        async with _own_session(test_dsn) as db:
            week = await PlanWeekService(db).ensure_current_plan_week(training_plan_id=plan_id, today=MONDAY)
            await asyncio.sleep(0.2)  # держим транзакцию открытой — окно гонки
            await db.commit()
            return week.id

    ids = await asyncio.gather(call(), call(), call())
    assert len(set(ids)) == 1
    # issue #304: курс (пул A+Б × 3) = 3 занятия, ровно один раз несмотря на гонку.
    assert await _count(test_dsn, select(func.count()).select_from(PlanItem).where(PlanItem.training_plan_id == plan_id)) == 3


async def test_concurrent_ensure_plannable_week_is_conflict_safe(session, user: User, test_dsn):
    plan_id = await _seed_plan(session, user)

    async def call() -> int:
        async with _own_session(test_dsn) as db:
            week = await PlanWeekService(db).ensure_plannable_week(
                training_plan_id=plan_id, week_number=3, today=MONDAY,
            )
            await db.commit()
            assert week is not None
            return week.id

    ids = await asyncio.gather(call(), call(), call())  # IntegrityError поднял бы сам gather
    assert len(set(ids)) == 1
    numbers = sorted(
        (await session.execute(select(PlanWeek.week_number).where(PlanWeek.training_plan_id == plan_id))).scalars(),
    )
    assert numbers == [1, 2, 3]


async def test_concurrent_copy_to_next_does_not_duplicate_items(session, user: User, test_dsn):
    plan_id = await _seed_plan(session, user)
    exercise = Exercise(name="Планка", metric_type=MetricType.TIME, category="core", source_type="system")
    session.add(exercise)
    await session.flush()
    repo = TrainingPlanRepository(session)
    source = await repo.create_plan_week(training_plan_id=plan_id, week_number=1, start_date=MONDAY, phase=WeekPhase.BASE)
    # Целевая неделя уже существует (иначе ON CONFLICT при создании сам сериализует вызовы).
    await repo.create_plan_week(training_plan_id=plan_id, week_number=2, start_date=MONDAY, phase=WeekPhase.BASE)
    session.add_all([
        PlanItem(training_plan_id=plan_id, exercise_id=exercise.id, count_per_week=1, day_of_week=day, plan_week_id=source.id)
        for day in (0, 2)
    ])
    await session.commit()
    source_id = source.id

    async def copy() -> tuple[int, int]:
        async with _own_session(test_dsn) as db:
            service = PlanWeekService(db)
            src = await TrainingPlanRepository(db).get_plan_week_for_user(source_id, user.id)
            target = await service.ensure_plannable_week(training_plan_id=plan_id, week_number=2, today=MONDAY)
            result = await service.copy_manual_items(source=src, target=target)
            await asyncio.sleep(0.3)  # окно гонки: без лока второй вызов успел бы прочитать пустую target
            await db.commit()
            return result

    results = await asyncio.gather(copy(), copy())
    assert sorted(results) == [(0, 2), (2, 0)]  # один скопировал, второй всё пропустил как дубли
    target_count = await _count(
        test_dsn,
        select(func.count()).select_from(PlanItem).join(PlanWeek, PlanItem.plan_week_id == PlanWeek.id)
        .where(PlanWeek.training_plan_id == plan_id, PlanWeek.week_number == 2),
    )
    # #301/#304: 2 скопированные ручные строки + 3 занятия курса из снимка (ровно один раз, без дублей при гонке).
    assert target_count == 5
