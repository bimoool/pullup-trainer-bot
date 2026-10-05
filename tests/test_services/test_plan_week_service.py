"""Checkpoint 1 (issue #188): PlanWeekService.ensure_current_plan_week —
единственный канонический путь материализации Program -> PlanWeek/PlanItem.
Пять обязательных сценариев из preflight (раздел 9): новый пользователь,
идемпотентность, бэкфилл/старые данные, rollover, ownership."""

import asyncio
from datetime import UTC, date, datetime

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import User
from app.db.models_program import (
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramInclusion,
    ProgramItem,
    TrainingPlan,
)
from app.db.repositories.programs import program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.services.plan_week import PlanWeekService


async def _make_recurring_program(session, *, category: str = "synthetic") -> tuple[Program, list[ProgramItem]]:
    """Зеркалит реальный сид «Подтягивания» (2 ProgramItem, week_phase=base,
    day_of_week=NULL — свободный пул, см. scripts/backfill_multi_program.py
    ::_get_or_create_program_item)."""
    program = Program(
        name="Синтетическая recurring", goal="test", structure_type=ProgramStructureType.RECURRING,
        category=category, config={},
    )
    session.add(program)
    await session.flush()

    block_a = Exercise(name="Блок A", metric_type=MetricType.REPS, category=category, subcategory="block_a")
    block_b = Exercise(name="Блок Б", metric_type=MetricType.REPS, category=category, subcategory="block_b")
    session.add_all([block_a, block_b])
    await session.flush()

    items = [
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_a.id,
            count_per_week=3, day_of_week=None,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_b.id,
            count_per_week=3, day_of_week=None,
        ),
    ]
    session.add_all(items)
    await session.flush()
    return program, items


_DEFAULT_PLAN_CREATED_AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)  # понедельник, полдень — время суток не участвует в расчёте (домен), но нужно для NOT NULL


async def _make_plan_with_inclusion(
    session, user: User, program: Program, *, created_at=None, program_items: list[ProgramItem] | None = None,
) -> TrainingPlan:
    """Checkpoint 1.1 (issue #188): snapshot строится через ту же
    program_items_snapshot, что и настоящий путь подключения — тестам,
    которые доходят до rollover-клонирования, недостаточно snapshot={},
    оно больше не читает live ProgramItem. program_items=None оставляет
    snapshot без "program_items" — используется только там, где тест
    специально проверяет фолбэк/легаси-случай."""
    plan = TrainingPlan(user_id=user.id, created_at=created_at or _DEFAULT_PLAN_CREATED_AT)
    session.add(plan)
    await session.flush()
    snapshot: dict = {"structure_type": program.structure_type.value}
    if program_items is not None:
        snapshot["program_items"] = program_items_snapshot(program_items)
    inclusion = ProgramInclusion(
        training_plan_id=plan.id, program_id=program.id, snapshot=snapshot, progression_state={}, is_active=True,
    )
    session.add(inclusion)
    await session.flush()
    return plan


async def _plan_items(session, plan_id: int) -> list[PlanItem]:
    return await TrainingPlanRepository(session).list_plan_items(plan_id)


# --- New user --------------------------------------------------------------------------


async def test_new_inclusion_materializes_into_current_week(session, user: User):
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, created_at=None, program_items=program_items)

    week = await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan.id, today=date(2026, 9, 21),  # понедельник
    )

    assert week.week_number == 1
    assert week.start_date == date(2026, 9, 21)
    items = await _plan_items(session, plan.id)
    assert len(items) == 2
    assert all(item.plan_week_id == week.id for item in items)


# --- Idempotency -------------------------------------------------------------------------


async def test_two_calls_same_day_create_no_duplicates(session, user: User):
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)

    week1 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 21))
    week2 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 22))

    assert week1.id == week2.id
    items = await _plan_items(session, plan.id)
    assert len(items) == 2  # не 4


# --- Existing/backfill: PlanItem без week получает FK, данные не меняются ---------------


async def test_unweeked_existing_plan_items_get_attached_not_duplicated(session, user: User):
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program)
    inclusion = (await TrainingPlanRepository(session).list_inclusions(plan.id))[0]

    # Имитация состояния "мигрирован до checkpoint 1" — PlanItem уже есть,
    # plan_week_id ещё NULL, как у реальных бэкфилленных аккаунтов сегодня.
    pre_existing = await TrainingPlanRepository(session).bulk_create_plan_items_from_program_items(
        training_plan_id=plan.id, program_inclusion_id=inclusion.id, program_items=program_items,
    )
    pre_existing_ids = {item.id for item in pre_existing}

    week = await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan.id, today=date(2026, 9, 21),
    )

    items = await _plan_items(session, plan.id)
    assert len(items) == 2  # не создались новые поверх старых
    assert {item.id for item in items} == pre_existing_ids  # те же самые строки
    assert all(item.plan_week_id == week.id for item in items)


# --- Rollover ------------------------------------------------------------------------


async def test_rollover_creates_new_items_in_new_week_keeps_old_week_intact(session, user: User):
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)

    week1 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 21))
    week1_items = await _plan_items(session, plan.id)
    week1_item_ids = {item.id for item in week1_items}
    assert len(week1_items) == 2

    week2 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 28))

    assert week2.id != week1.id
    assert week2.week_number == 2

    all_items = await _plan_items(session, plan.id)
    assert len(all_items) == 4  # 2 старых + 2 новых, не апдейт старых

    week1_items_after = [item for item in all_items if item.plan_week_id == week1.id]
    week2_items_new = [item for item in all_items if item.plan_week_id == week2.id]
    assert {item.id for item in week1_items_after} == week1_item_ids  # неделя 1 не тронута
    assert len(week2_items_new) == 2

    # повторный вызов в той же (второй) неделе — снова без дублей
    await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 29))
    all_items_again = await _plan_items(session, plan.id)
    assert len(all_items_again) == 4


# --- Snapshot immutability (Кирилл, checkpoint 1.1 — контрактный баг) -------------------
#
# ProgramInclusion.snapshot зафиксирован на момент подключения; program_id
# после этого — только provenance, не источник контента. Rollover обязан
# читать snapshot, не live ProgramItem — иначе пользователь, подключивший
# курс месяц назад, получит другую программу на следующей неделе просто
# потому, что кто-то отредактировал каталог.


async def test_rollover_uses_snapshot_not_live_program(session, user: User):
    program, program_items = await _make_recurring_program(session, category="immut")
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)

    await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan.id, today=date(2026, 9, 21),
    )
    week1_items = await _plan_items(session, plan.id)
    assert len(week1_items) == 2

    # Мутация LIVE Program ПОСЛЕ подключения — третий ProgramItem, которого
    # в snapshot этого пользователя нет и быть не должно.
    block_c = Exercise(name="Блок В", metric_type=MetricType.REPS, category="immut", subcategory="block_c")
    session.add(block_c)
    await session.flush()
    session.add(
        ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_c.id, count_per_week=2),
    )
    await session.flush()

    week2 = await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan.id, today=date(2026, 9, 28),
    )
    week2_items = [item for item in await _plan_items(session, plan.id) if item.plan_week_id == week2.id]

    assert len(week2_items) == 2  # НЕ 3 — новый ProgramItem программы не просочился
    assert block_c.id not in {item.exercise_id for item in week2_items}


async def test_new_inclusion_after_program_mutation_gets_new_structure(session, user: User):
    """Обратная сторона того же контракта: НОВОЕ подключение, сделанное
    ПОСЛЕ правки каталога, обязано снять снимок с уже изменённой Program —
    snapshot фиксируется в момент подключения, не раньше."""
    program, program_items = await _make_recurring_program(session, category="immut2")

    block_c = Exercise(name="Блок В", metric_type=MetricType.REPS, category="immut2", subcategory="block_c")
    session.add(block_c)
    await session.flush()
    item_c = ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_c.id, count_per_week=2)
    session.add(item_c)
    await session.flush()

    plan = await _make_plan_with_inclusion(
        session, user, program, program_items=[*program_items, item_c],  # снимок берёт АКТУАЛЬНОЕ состояние
    )

    await PlanWeekService(session).ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 21))
    items = await _plan_items(session, plan.id)
    assert {item.exercise_id for item in items} == {program_items[0].exercise_id, program_items[1].exercise_id, block_c.id}
    assert len(items) == 3


# --- Ownership -----------------------------------------------------------------------


async def test_unknown_training_plan_id_raises(session):
    try:
        await PlanWeekService(session).ensure_current_plan_week(training_plan_id=999_999, today=date(2026, 9, 21))
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown training_plan_id")


# --- Concurrency (Кирилл, checkpoint 1.1, п.7) -------------------------------------------
#
# uq_plan_weeks_plan_week_number существует с волны 1 (не новый constraint
# — найден в модели, не в тексте миграции по "unique=", моя же ошибка при
# первой проверке). Воспроизведено реальной гонкой (3 независимых
# соединения, не один AsyncSession — иначе гонки физически нет): без
# ON CONFLICT проигравший вызов падал необработанной IntegrityError.


async def test_concurrent_ensure_calls_do_not_raise_and_agree_on_one_week(test_dsn):
    """Единственный тест в этом файле не использующий фикстуру session —
    ей одна транзакция на тест, гонки внутри одной транзакции не бывает."""
    setup_engine = create_async_engine(test_dsn)
    factory = async_sessionmaker(setup_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as setup_session:
        setup_user = await UserRepository(setup_session).create(telegram_id=1003, username="racer")
        program, program_items = await _make_recurring_program(setup_session, category="race")
        plan = await _make_plan_with_inclusion(setup_session, setup_user, program, program_items=program_items)
        await setup_session.commit()
        plan_id = plan.id
    await setup_engine.dispose()

    async def call() -> int:
        engine = create_async_engine(test_dsn)
        try:
            async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as call_session:
                week = await PlanWeekService(call_session).ensure_current_plan_week(
                    training_plan_id=plan_id, today=date(2026, 9, 21),
                )
                await call_session.commit()
                return week.id
        finally:
            await engine.dispose()

    week_ids = await asyncio.gather(call(), call(), call())  # ни одного исключения — сам gather бы его поднял

    assert len(set(week_ids)) == 1  # все три вызова сошлись на одной и той же неделе

    check_engine = create_async_engine(test_dsn)
    async with async_sessionmaker(check_engine, class_=AsyncSession, expire_on_commit=False)() as check_session:
        rows = await TrainingPlanRepository(check_session).list_inclusions(plan_id)
        assert rows  # sanity — план не потерялся
        weeks = (
            await check_session.execute(sa_select(PlanWeek).where(PlanWeek.training_plan_id == plan_id))
        ).scalars().all()
        assert len(weeks) == 1  # ни одного дубля на уровне БД
    await check_engine.dispose()


# --- Regression: FIXED/SINGLE_LESSON программы не материализуются понедельно ------------


async def test_non_recurring_program_is_not_materialized(session, user: User):
    program = Program(
        name="Разовое занятие", goal="test", structure_type=ProgramStructureType.SINGLE_LESSON,
        category="synthetic_single", config={},
    )
    session.add(program)
    await session.flush()
    plan = await _make_plan_with_inclusion(session, user, program)

    week = await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan.id, today=date(2026, 9, 21),
    )

    assert week is not None  # неделя всё равно создаётся (плановая ось не зависит от программы)
    items = await _plan_items(session, plan.id)
    assert items == []  # но материализации нет — программе это не подходит


# --- Ownership / no cross-contamination (Кирилл, отдельная проверка) --------------------
#
# list_unweeked_plan_items фильтрует строго по program_inclusion_id — риск
# был бы, если бы фильтр случайно захватывал что-то более широкое (другой
# план, другую инклюзию, ручные строки). Проверяем это фактом, не
# рассуждением: два независимых плана с той же самой программой + ручной
# PlanItem без инклюзии рядом — ensure_current_plan_week на ОДНОМ плане не
# должен тронуть ничего постороннего.


async def test_unweeked_attach_does_not_touch_other_plans_inclusion(session, user: User):
    """Два разных пользователя, два разных TrainingPlan, оба подключили ТУ
    ЖЕ программу (program_id общий — как оно и будет с единственной
    'Подтягивания' в каталоге). ensure_current_plan_week для плана A не
    должен привязать/создать PlanWeek и не должен трогать unweeked-строки
    плана B."""
    program, program_items = await _make_recurring_program(session)

    plan_a = await _make_plan_with_inclusion(session, user, program)

    other_user = await UserRepository(session).create(telegram_id=1002, username="other")
    plan_b = await _make_plan_with_inclusion(session, other_user, program)

    inclusion_a = (await TrainingPlanRepository(session).list_inclusions(plan_a.id))[0]
    inclusion_b = (await TrainingPlanRepository(session).list_inclusions(plan_b.id))[0]

    # Оба плана в состоянии "только что создана инклюзия" — unweeked строки
    # есть у обоих, независимо друг от друга.
    await TrainingPlanRepository(session).bulk_create_plan_items_from_program_items(
        training_plan_id=plan_a.id, program_inclusion_id=inclusion_a.id, program_items=program_items,
    )
    items_b = await TrainingPlanRepository(session).bulk_create_plan_items_from_program_items(
        training_plan_id=plan_b.id, program_inclusion_id=inclusion_b.id, program_items=program_items,
    )
    items_b_ids_before = {item.id for item in items_b}

    week_a = await PlanWeekService(session).ensure_current_plan_week(
        training_plan_id=plan_a.id, today=date(2026, 9, 21),
    )

    # План A материализован.
    items_a_after = await _plan_items(session, plan_a.id)
    assert all(item.plan_week_id == week_a.id for item in items_a_after)

    # План B — НИ ОДНА строка не тронута, plan_week_id всё ещё NULL, и для
    # него не создалась никакая PlanWeek побочно.
    items_b_after = await _plan_items(session, plan_b.id)
    assert {item.id for item in items_b_after} == items_b_ids_before
    assert all(item.plan_week_id is None for item in items_b_after)
    assert await TrainingPlanRepository(session).get_plan_week(training_plan_id=plan_b.id, week_number=1) is None


async def test_orphan_manual_plan_item_is_attached_to_current_week(session, user: User):
    """#297 — «сирота» (ручной PlanItem без недели, остаток старого POST /plan-items без plan_week_id)
    привязывается к текущей неделе при ensure_current_plan_week; день/count не меняются, программные
    строки привязываются как раньше, повторный вызов ничего не дублирует."""
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program)
    inclusion = (await TrainingPlanRepository(session).list_inclusions(plan.id))[0]

    await TrainingPlanRepository(session).bulk_create_plan_items_from_program_items(
        training_plan_id=plan.id, program_inclusion_id=inclusion.id, program_items=program_items,
    )
    manual_item = await TrainingPlanRepository(session).create_plan_item(
        training_plan_id=plan.id, exercise_id=program_items[0].exercise_id, complex_id=None,
        count_per_week=1, day_of_week=3, week_phase=None, program_inclusion_id=None,
    )
    assert manual_item.plan_week_id is None  # состояние «сироты»

    service = PlanWeekService(session)
    week = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 21))
    week_again = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 21))

    items = await _plan_items(session, plan.id)
    recurring_items = [item for item in items if item.program_inclusion_id == inclusion.id]
    manual_after = next(item for item in items if item.id == manual_item.id)

    assert week_again.id == week.id
    assert all(item.plan_week_id == week.id for item in recurring_items)
    assert manual_after.plan_week_id == week.id  # сирота привязана, не удалена
    assert (manual_after.day_of_week, manual_after.count_per_week) == (3, 1)
    assert manual_after.program_inclusion_id is None
    assert len(items) == len(recurring_items) + 1  # дублей нет


async def test_orphan_attach_is_scoped_to_its_own_plan(session, user: User):
    """#297 — сироты чужого плана этим вызовом не трогаются."""
    program, program_items = await _make_recurring_program(session)
    plan_a = await _make_plan_with_inclusion(session, user, program)
    other = await UserRepository(session).create(telegram_id=1002, username="other")
    plan_b = await _make_plan_with_inclusion(session, other, program)
    repo = TrainingPlanRepository(session)
    orphan_b = await repo.create_plan_item(
        training_plan_id=plan_b.id, exercise_id=program_items[0].exercise_id, complex_id=None,
        count_per_week=1, day_of_week=None, week_phase=None, program_inclusion_id=None,
    )

    await PlanWeekService(session).ensure_current_plan_week(training_plan_id=plan_a.id, today=date(2026, 9, 21))

    assert (await session.get(PlanItem, orphan_b.id)).plan_week_id is None


# --- #301: недели наперёд продолжающейся программы ---------------------------------------


async def _items_of_week(session, week_id: int) -> list[PlanItem]:
    return list((await session.execute(
        sa_select(PlanItem).where(PlanItem.plan_week_id == week_id).order_by(PlanItem.id),
    )).scalars())


async def test_plannable_future_weeks_get_course_rows_idempotently(session, user: User):
    """#301: › на неделю 2/3 создаёт неделю уже с курсом (из снимка), повтор без дублей."""
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)
    today = date(2026, 9, 21)
    week1 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)

    week3 = await service.ensure_plannable_week(training_plan_id=plan.id, week_number=3, today=today)
    assert week3 is not None and week3.week_number == 3
    week2 = await TrainingPlanRepository(session).get_plan_week(training_plan_id=plan.id, week_number=2)

    assert len(await _items_of_week(session, week1.id)) == 2
    for week in (week2, week3):
        rows = await _items_of_week(session, week.id)
        assert len(rows) == 2 and {r.count_per_week for r in rows} == {3}
        assert all(r.program_inclusion_id is not None for r in rows)

    await service.ensure_plannable_week(training_plan_id=plan.id, week_number=3, today=today)
    await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)
    assert len(await _plan_items(session, plan.id)) == 6


async def test_existing_empty_future_week_is_filled_on_current_week_ensure(session, user: User):
    """#301: уже существующая пустая будущая неделя (создана до фикса) наполняется при GET /plan."""
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    today = date(2026, 9, 21)
    service = PlanWeekService(session)
    await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)
    future = await TrainingPlanRepository(session).create_plan_week(
        training_plan_id=plan.id, week_number=2, start_date=date(2026, 9, 28), phase=WeekPhase.BASE,
    )
    assert await _items_of_week(session, future.id) == []

    await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)

    assert len(await _items_of_week(session, future.id)) == 2
    await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)
    assert len(await _items_of_week(session, future.id)) == 2


async def test_rollover_after_prematerialisation_creates_no_duplicates(session, user: User):
    """#301: неделя 2 уже наполнена наперёд; когда она становится текущей — строк не удваивается."""
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)
    await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 21))
    week2 = await service.ensure_plannable_week(training_plan_id=plan.id, week_number=2, today=date(2026, 9, 21))
    before = {r.id for r in await _items_of_week(session, week2.id)}
    assert len(before) == 2

    current = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 29))

    assert current.id == week2.id
    assert {r.id for r in await _items_of_week(session, week2.id)} == before
    # неделя 3 (ещё не создана) не появилась сама; всего 2 + 2
    assert len(await _plan_items(session, plan.id)) == 4


async def test_future_weeks_use_snapshot_and_manual_only_plan_stays_empty(session, user: User):
    """#301: источник — снимок, не live Program; план без курса — будущая неделя пустая."""
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)
    today = date(2026, 9, 21)
    await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)
    session.add(ProgramItem(
        program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=program_items[0].exercise_id,
        count_per_week=9, day_of_week=1,
    ))
    await session.flush()
    week2 = await service.ensure_plannable_week(training_plan_id=plan.id, week_number=2, today=today)
    assert sorted(r.count_per_week for r in await _items_of_week(session, week2.id)) == [3, 3]

    manual_user = await UserRepository(session).create(telegram_id=424242, username="manual")
    manual_plan = TrainingPlan(user_id=manual_user.id, created_at=_DEFAULT_PLAN_CREATED_AT)
    session.add(manual_plan)
    await session.flush()
    await service.ensure_current_plan_week(training_plan_id=manual_plan.id, today=today)
    manual_week2 = await service.ensure_plannable_week(training_plan_id=manual_plan.id, week_number=2, today=today)
    assert await _items_of_week(session, manual_week2.id) == []


async def test_inactive_inclusion_is_not_materialised_into_future_weeks(session, user: User):
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)
    today = date(2026, 9, 21)
    await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)
    inclusion = (await TrainingPlanRepository(session).list_inclusions(plan.id))[0]
    inclusion.is_active = False
    await session.flush()

    week2 = await service.ensure_plannable_week(training_plan_id=plan.id, week_number=2, today=today)

    assert await _items_of_week(session, week2.id) == []


async def test_release_future_weeks_drops_unperformed_future_rows_only(session, user: User):
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)
    today = date(2026, 9, 21)
    week1 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=today)
    week3 = await service.ensure_plannable_week(training_plan_id=plan.id, week_number=3, today=today)
    inclusion = (await TrainingPlanRepository(session).list_inclusions(plan.id))[0]

    removed = await service.release_future_weeks_of_inclusion(inclusion=inclusion, today=today)

    assert removed == 4  # недели 2 и 3 по 2 строки
    assert len(await _items_of_week(session, week1.id)) == 2  # текущая не тронута
    assert await _items_of_week(session, week3.id) == []


async def test_past_gap_weeks_are_created_empty(session, user: User):
    """#301: неделя, ни разу не бывшая текущей, не пропадает из списка (степпер не перепрыгивает)."""
    program, program_items = await _make_recurring_program(session)
    plan = await _make_plan_with_inclusion(session, user, program, program_items=program_items)
    service = PlanWeekService(session)
    week1 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 9, 21))

    week3 = await service.ensure_current_plan_week(training_plan_id=plan.id, today=date(2026, 10, 5))

    numbers = [w.week_number for w in await TrainingPlanRepository(session).list_plan_weeks(plan.id)]
    assert numbers == [1, 2, 3]
    gap = await TrainingPlanRepository(session).get_plan_week(training_plan_id=plan.id, week_number=2)
    assert await _items_of_week(session, gap.id) == []  # прошлое — без строк
    assert len(await _items_of_week(session, week1.id)) == 2
    assert len(await _items_of_week(session, week3.id)) == 2
