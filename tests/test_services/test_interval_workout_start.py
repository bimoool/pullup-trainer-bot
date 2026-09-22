"""Integration tests для interval workout start path (Phase B1, issue #215) —
проверка полного потока: ComplexItem.protocol → build_workout_snapshot →
TrainingSession.workout_snapshot → SessionBlock без targets.

Требует реальный Postgres (tests/conftest.py поднимает db автоматически)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import Complex, ComplexItem, Exercise, PlanItem, TrainingPlan
from app.domain.multi_program import MetricType
from app.domain.workout_protocol import ProtocolType
from app.services.live_session import LiveSessionService


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def interval_complex(session: AsyncSession) -> Complex:
    """Interval workout: один ComplexItem с protocol.type='interval'."""
    exercise = Exercise(
        name="Подтягивания 3min", metric_type=MetricType.REPS, category="pull",
    )
    session.add(exercise)
    await session.flush()

    complex = Complex(name="Табата подтягивания", source_type="system")
    session.add(complex)
    await session.flush()

    protocol = {
        "type": "interval",
        "total_duration_seconds": 180,
        "work_seconds": 10,
        "rest_seconds": 20,
        "starts_with": "work",
    }
    complex_item = ComplexItem(
        complex_id=complex.id, exercise_id=exercise.id, order_index=0,
        sets=0, protocol=protocol,  # interval — sets игнорируется
    )
    session.add(complex_item)
    await session.flush()

    return complex


@pytest.fixture
async def interval_plan_item(session: AsyncSession, interval_complex: Complex) -> PlanItem:
    """PlanItem, ссылающийся на interval Complex."""
    from app.db.models import User

    user = User(telegram_id=999001, telegram_username="interval_tester")
    session.add(user)
    await session.flush()

    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()

    plan_item = PlanItem(
        training_plan_id=plan.id, exercise_id=interval_complex.id, complex_id=interval_complex.id,
        count_per_week=3, day_of_week=1,
    )
    session.add(plan_item)
    await session.flush()

    return plan_item


async def test_start_interval_workout_creates_snapshot(
    session: AsyncSession, interval_plan_item: PlanItem,
):
    """Start interval workout → workout_snapshot сохранён, SessionBlock без targets."""
    service = LiveSessionService(session)

    result = await service.start_session(
        user_id=interval_plan_item.training_plan.user_id,
        client_session_id=uuid.uuid4(),
        plan_item_ids=[interval_plan_item.id],
    )

    assert result is not None
    detail = result.session

    # Проверка: workout_snapshot сохранён
    assert detail.workout_snapshot is not None
    assert "workout_id" in detail.workout_snapshot
    assert "items" in detail.workout_snapshot

    # Проверка: один SessionBlock, ноль SetTargets
    assert len(detail.blocks) == 1
    assert len(detail.blocks[0].set_targets) == 0  # interval — без targets


async def test_start_interval_duplicate_protection(
    session: AsyncSession, interval_plan_item: PlanItem,
):
    """Повторный start с тем же client_session_id → та же TrainingSession."""
    service = LiveSessionService(session)
    client_id = uuid.uuid4()

    result1 = await service.start_session(
        user_id=interval_plan_item.training_plan.user_id,
        client_session_id=client_id,
        plan_item_ids=[interval_plan_item.id],
    )

    result2 = await service.start_session(
        user_id=interval_plan_item.training_plan.user_id,
        client_session_id=client_id,  # тот же UUID
        plan_item_ids=[interval_plan_item.id],
    )

    assert result1 is not None
    assert result2 is not None
    assert result1.session.id == result2.session.id  # та же сессия


async def test_snapshot_immutability(
    session: AsyncSession, interval_plan_item: PlanItem, interval_complex: Complex,
):
    """Изменение ComplexItem.protocol после Start не влияет на активную сессию."""
    service = LiveSessionService(session)

    result = await service.start_session(
        user_id=interval_plan_item.training_plan.user_id,
        client_session_id=uuid.uuid4(),
        plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    original_snapshot = result.session.workout_snapshot

    # Изменение protocol
    from app.db.repositories.programs import ProgramRepository
    items = await ProgramRepository(session).list_complex_items(interval_complex.id)
    items[0].protocol = {
        "type": "interval",
        "total_duration_seconds": 999,  # изменено
        "work_seconds": 5,  # изменено
        "rest_seconds": 10,
        "starts_with": "work",
    }
    await session.flush()

    # Перечитать сессию
    refreshed = await service.get_active(user_id=interval_plan_item.training_plan.user_id)
    assert refreshed is not None

    # Snapshot не изменился
    assert refreshed.session.workout_snapshot == original_snapshot
    assert refreshed.session.workout_snapshot["items"][0]["protocol"]["total_duration_seconds"] == 180  # старое


# TODO: ещё нужны тесты (не блокируют коммит, но обязательны для Phase B1):
# - Expired recovery (start → fake now > deadline → GET active → COMPLETED)
# - Long absence (completed_at = protocol deadline, не момент reopen)
# - Idempotency lazy finalizer (вызван дважды → тот же результат)
# - Active во время get_ready/work/rest (корректная вычисляемая фаза)
# - Standard regression (STEP/manual path остаётся зелёным)
