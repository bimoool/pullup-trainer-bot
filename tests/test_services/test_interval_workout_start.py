"""Integration tests для interval workout start path (Phase B1, issue #215) —
проверка полного потока: ComplexItem.protocol → build_workout_snapshot →
TrainingSession.workout_snapshot → SessionBlock без targets.

Требует реальный Postgres (tests/conftest.py поднимает db автоматически)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import MetricType
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
async def interval_user(session: AsyncSession) -> User:
    user = User(telegram_id=999001, username="interval_tester")
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def interval_plan_item(session: AsyncSession, interval_complex: Complex, interval_user: User) -> PlanItem:
    """PlanItem, ссылающийся на interval Complex. user_id — отдельной
    interval_user фикстурой (models_program.py не заводит ORM-relationship
    PlanItem.training_plan, см. докстринг SessionDetail — обращение к
    несуществующему атрибуту было реальным багом исходной фикстуры
    воркера, ни разу не запускавшейся из-за заблокированного sandbox)."""
    plan = TrainingPlan(user_id=interval_user.id)
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
    session: AsyncSession, interval_plan_item: PlanItem, interval_user: User,
):
    """Start interval workout → workout_snapshot сохранён, SessionBlock без targets."""
    service = LiveSessionService(session)

    result = await service.start_session(
        user_id=interval_user.id,
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
    session: AsyncSession, interval_plan_item: PlanItem, interval_user: User,
):
    """Повторный start с тем же client_session_id → та же TrainingSession."""
    service = LiveSessionService(session)
    client_id = uuid.uuid4()

    result1 = await service.start_session(
        user_id=interval_user.id,
        client_session_id=client_id,
        plan_item_ids=[interval_plan_item.id],
    )

    result2 = await service.start_session(
        user_id=interval_user.id,
        client_session_id=client_id,  # тот же UUID
        plan_item_ids=[interval_plan_item.id],
    )

    assert result1 is not None
    assert result2 is not None
    assert result1.session.id == result2.session.id  # та же сессия


async def test_snapshot_immutability(
    session: AsyncSession, interval_plan_item: PlanItem, interval_complex: Complex, interval_user: User,
):
    """Изменение ComplexItem.protocol после Start не влияет на активную сессию."""
    service = LiveSessionService(session)

    result = await service.start_session(
        user_id=interval_user.id,
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
    refreshed = await service.get_active(user_id=interval_user.id)
    assert refreshed is not None

    # Snapshot не изменился
    assert refreshed.session.workout_snapshot == original_snapshot
    assert refreshed.session.workout_snapshot["items"][0]["protocol"]["total_duration_seconds"] == 180  # старое


async def _set_performed_at(session: AsyncSession, training_session_id: int, performed_at: datetime) -> None:
    """Тестовый хелпер — напрямую двигает TrainingSession.performed_at в
    прошлое, чтобы смоделировать "время прошло" без добавления explicit
    `now`-параметра в публичный API сервиса (issue #215, раздел 18 —
    'test clock': не плодить monkeypatch datetime.now() по всему коду,
    performed_at уже единственный persisted timing anchor по контракту).
    Тот же приём, что уже используется в проекте для тестовых legacy-дат
    (scripts/e2e_seed.py, record_workout с performed_at=now-timedelta)."""
    from sqlalchemy import update

    await session.execute(
        update(TrainingSession).where(TrainingSession.id == training_session_id).values(performed_at=performed_at),
    )
    await session.flush()


async def test_active_during_get_ready(session: AsyncSession, interval_plan_item: PlanItem, interval_user: User):
    """Сразу после Start (до конца 5-секундного GET_READY) — phase=get_ready."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None

    refreshed = await service.get_active(user_id=interval_user.id)
    assert refreshed is not None
    assert refreshed.session.status == SessionStatus.STARTED


async def test_active_during_work(session: AsyncSession, interval_plan_item: PlanItem, interval_user: User):
    """elapsed=8 сек (внутри 5с GET_READY + первые 3с work=10) — сессия ещё STARTED."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    past = datetime.now(UTC) - timedelta(seconds=8)
    await _set_performed_at(session, result.session.id, past)

    refreshed = await service.get_active(user_id=interval_user.id)
    assert refreshed is not None  # 8с < total_duration(180) — всё ещё активна
    assert refreshed.session.status == SessionStatus.STARTED


async def test_active_during_rest(session: AsyncSession, interval_plan_item: PlanItem, interval_user: User):
    """elapsed=20 сек (5с GET_READY + 10с work + начало 20с rest) — всё ещё STARTED,
    сессия не завершена (180с общей длительности далеко не исчерпаны)."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    past = datetime.now(UTC) - timedelta(seconds=20)
    await _set_performed_at(session, result.session.id, past)

    refreshed = await service.get_active(user_id=interval_user.id)
    assert refreshed is not None
    assert refreshed.session.status == SessionStatus.STARTED


async def test_recovery_at_45_seconds_same_session(session: AsyncSession, interval_plan_item: PlanItem, interval_user: User):
    """start → fake now +45с → GET active → та же TrainingSession, не новая."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    original_id = result.session.id
    past = datetime.now(UTC) - timedelta(seconds=45)
    await _set_performed_at(session, original_id, past)

    refreshed = await service.get_active(user_id=interval_user.id)
    assert refreshed is not None
    assert refreshed.session.id == original_id  # та же сессия, не пересоздана
    assert refreshed.session.status == SessionStatus.STARTED  # 45с < 180с total


async def test_expired_recovery_finalizes_session(session: AsyncSession, interval_plan_item: PlanItem, interval_user: User):
    """start → fake now > deadline (180с+5с get_ready) → GET active → сессия
    финализирована: status=COMPLETED, result сохранён с полным контрактом."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    session_id = result.session.id
    # performed_at достаточно далеко в прошлом, чтобы execution_started_at
    # (+5с) + total_duration_seconds(180с) уже прошёл к моменту вызова.
    past = datetime.now(UTC) - timedelta(seconds=200)
    await _set_performed_at(session, session_id, past)

    # /sessions/live/active НЕ должен отдать её как активную (issue #215,
    # раздел 5) — она только что финализирована лениво.
    refreshed = await service.get_active(user_id=interval_user.id)
    assert refreshed is None

    # Но сама сессия реально существует и COMPLETED — читаем напрямую.
    final_detail = await TrainingSessionRepository(session).get_for_user(
        session_id, interval_user.id,
    )
    assert final_detail is not None
    assert final_detail.status == SessionStatus.COMPLETED
    assert len(final_detail.blocks) == 1
    result_json = final_detail.blocks[0].result
    assert result_json is not None
    assert result_json["type"] == "interval"
    assert result_json["planned_duration_seconds"] == 180
    assert result_json["completed_cycles"] == 6  # 180/10/20 -> 6, контрактный кейс


async def test_long_absence_completed_at_is_protocol_deadline_not_reopen_time(
    session: AsyncSession, interval_plan_item: PlanItem, interval_user: User,
):
    """start → fake now +10 минут → completed_at = плановый дедлайн (не
    момент reopen), actual_duration_seconds = planned (180), не 600+."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    session_id = result.session.id
    performed_at = datetime.now(UTC) - timedelta(minutes=10)
    await _set_performed_at(session, session_id, performed_at)
    expected_deadline = performed_at + timedelta(seconds=5 + 180)  # GET_READY_SECONDS + total

    await service.get_active(user_id=interval_user.id)

    final_detail = await TrainingSessionRepository(session).get_for_user(
        session_id, interval_user.id,
    )
    result_json = final_detail.blocks[0].result
    completed_at = datetime.fromisoformat(result_json["completed_at"])
    assert abs((completed_at - expected_deadline).total_seconds()) < 1
    assert result_json["actual_duration_seconds"] == 180  # НЕ 600+


async def test_lazy_finalizer_idempotent_when_called_twice(session: AsyncSession, interval_plan_item: PlanItem, interval_user: User):
    """Central finalizer вызван дважды подряд → идентичный persisted result,
    без дублей side effects. Result полностью детерминирован входными
    (performed_at, protocol) — второй вызов производит байт-в-байт тот же
    JSON, не зависит от порядка/количества вызовов."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    session_id = result.session.id
    user_id = interval_user.id
    past = datetime.now(UTC) - timedelta(seconds=200)
    await _set_performed_at(session, session_id, past)

    await service.finalize_expired_interval_if_needed(session_id, user_id)
    first = await TrainingSessionRepository(session).get_for_user(session_id, user_id)
    first_result = first.blocks[0].result
    first_status = first.status

    # Второй вызов — имитация конкурентного recovery-запроса.
    await service.finalize_expired_interval_if_needed(session_id, user_id)
    second = await TrainingSessionRepository(session).get_for_user(session_id, user_id)

    assert second.status == first_status == SessionStatus.COMPLETED
    assert second.blocks[0].result == first_result  # идентичный JSON, не дубль
    assert len(second.blocks) == 1  # ни одного нового SessionBlock не создано


async def test_journal_only_recovery_without_active_lookup(session: AsyncSession, interval_plan_item: PlanItem, interval_user: User):
    """start → НЕ вызывать get_active вообще → продвинуть время за deadline →
    вызвать session-listing путь (тот же helper, что list_sessions route
    вызывает) → сессия материализуется как completed."""
    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=interval_user.id,
        client_session_id=uuid.uuid4(), plan_item_ids=[interval_plan_item.id],
    )
    assert result is not None
    session_id = result.session.id
    user_id = interval_user.id
    past = datetime.now(UTC) - timedelta(seconds=200)
    await _set_performed_at(session, session_id, past)

    # Имитация list_sessions route: сканирует STARTED-сессии пользователя и
    # финализирует истёкшие — НЕ через /active вообще.
    started = await TrainingSessionRepository(session).list_for_user(user_id, status=SessionStatus.STARTED)
    for detail in started:
        await service.finalize_expired_interval_if_needed(detail.id, user_id)

    completed_only = await TrainingSessionRepository(session).list_for_user(user_id, status=SessionStatus.COMPLETED)
    assert any(d.id == session_id for d in completed_only)
    finalized = next(d for d in completed_only if d.id == session_id)
    assert finalized.blocks[0].result is not None


async def test_standard_step_session_unaffected_by_interval_finalizer(session: AsyncSession):
    """Regression — standard STEP-путь (без workout_snapshot) не задет
    lazy-финализацией вообще: finalize_expired_interval_if_needed должен
    быть no-op для неё (workout_snapshot is None guard, issue #215).

    Переиспользует уже существующий, проверенный _setup_step_session (тот
    же хелпер, что tests/test_web/test_v2_live_session.py использует для
    всех STEP-тестов проекта) — не реализует настройку STEP с нуля."""
    from tests.test_web.test_v2_live_session import _setup_step_session

    user = User(telegram_id=999002, username="step_regression")
    session.add(user)
    await session.flush()

    _inclusion, _roles, plan_item_ids = await _setup_step_session(session, user)

    service = LiveSessionService(session)
    result = await service.start_session(
        user_id=user.id, client_session_id=uuid.uuid4(),
        plan_item_ids=[plan_item_ids["block_a"], plan_item_ids["block_b"]],
    )
    assert result is not None
    assert result.session.workout_snapshot is None  # standard путь — не interval

    # Финализатор — no-op для неё, статус не должен смениться.
    await service.finalize_expired_interval_if_needed(result.session.id, user.id)
    unchanged = await TrainingSessionRepository(session).get_for_user(result.session.id, user.id)
    assert unchanged.status == SessionStatus.STARTED  # не тронута interval-логикой
    assert len(unchanged.blocks) == 2  # оба блока (Блок A + Блок Б) целы
