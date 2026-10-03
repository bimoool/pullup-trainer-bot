import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.db.models import User
from app.db.models_program import Exercise, PlanItem, SessionPhase, SessionStatus, TrainingPlan
from app.db.repositories.training_sessions import (
    BatchSetLogInput,
    SessionBlockInput,
    SetLogInput,
    SetTargetInput,
    TrainingSessionRepository,
)
from app.domain.multi_program import MetricType, SessionSource


async def _make_exercise(session, name: str) -> int:
    exercise = Exercise(name=name, metric_type=MetricType.REPS, category="synthetic")
    session.add(exercise)
    await session.flush()
    return exercise.id


async def _make_plan_item(session, user: User, exercise_id: int) -> int:
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    item = PlanItem(training_plan_id=plan.id, exercise_id=exercise_id, count_per_week=3)
    session.add(item)
    await session.flush()
    return item.id


def _reps_block(exercise_id: int, reps: list[int], max_reps: int) -> SessionBlockInput:
    sets = [
        SetLogInput(set_number=i + 1, metric_type=MetricType.REPS, value=Decimal(r), unit="reps")
        for i, r in enumerate(reps)
    ]
    sets.append(
        SetLogInput(
            set_number=len(reps) + 1, metric_type=MetricType.REPS, value=Decimal(max_reps), unit="reps",
            is_max_set=True,
        ),
    )
    return SessionBlockInput(exercise_id=exercise_id, sets=sets)


async def test_create_session_persists_blocks_and_set_logs(session, user: User):
    exercise_a = await _make_exercise(session, "Block A")
    exercise_b = await _make_exercise(session, "Block B")
    repo = TrainingSessionRepository(session)

    created = await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        effort=Decimal("7.5"), comment="ок",
        blocks=[_reps_block(exercise_a, [10, 10, 10], 12), _reps_block(exercise_b, [3, 3, 3, 3], 4)],
    )

    detail = await repo.get_for_user(created.id, user.id)
    assert detail is not None
    assert detail.source == SessionSource.PLAN
    assert detail.effort == Decimal("7.5")
    assert detail.comment == "ок"
    assert [b.exercise_id for b in detail.blocks] == [exercise_a, exercise_b]
    assert [log.value for log in detail.blocks[0].set_logs] == [Decimal(10), Decimal(10), Decimal(10), Decimal(12)]
    assert detail.blocks[0].set_logs[-1].is_max_set is True
    assert detail.blocks[0].set_logs[0].is_max_set is False


async def test_get_for_user_returns_none_for_foreign_session(session, user: User):
    other_user = User(telegram_id=99999998, username="other")
    session.add(other_user)
    await session.flush()
    exercise = await _make_exercise(session, "Solo")
    repo = TrainingSessionRepository(session)
    created = await repo.create_session(
        user_id=other_user.id, source=SessionSource.FREEFORM, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
    )

    assert await repo.get_for_user(created.id, user.id) is None


async def test_list_for_user_orders_by_performed_at_descending(session, user: User):
    exercise = await _make_exercise(session, "Solo")
    repo = TrainingSessionRepository(session)
    await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
    )
    await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
    )

    sessions = await repo.list_for_user(user.id)

    assert [s.performed_at for s in sessions] == [datetime(2026, 1, 3, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)]


async def test_list_for_user_applies_offset_and_limit_as_python_slice(session, user: User):
    """Тот же приём, что GET /api/history (issue #50) — срез уже
    загруженного списка, см. докстринг TrainingSessionRepository.list_for_user."""
    exercise = await _make_exercise(session, "Solo")
    repo = TrainingSessionRepository(session)
    for day in range(1, 6):
        await repo.create_session(
            user_id=user.id, source=SessionSource.PLAN, performed_at=datetime(2026, 1, day, tzinfo=UTC),
            effort=None, comment=None, blocks=[_reps_block(exercise, [5], 6)],
        )

    page = await repo.list_for_user(user.id, limit=2, offset=1)

    assert [s.performed_at.day for s in page] == [4, 3]


# --- Живая сессия (issue #165, продолжение волны 3) --------------------------------------


async def test_create_live_session_persists_blocks_targets_and_plan_items(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    client_session_id = uuid.uuid4()

    created = await repo.create_live_session(
        user_id=user.id, client_session_id=client_session_id, source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[
            SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps"),
            SetTargetInput(set_number=2, metric_type=MetricType.REPS, value=Decimal(15), unit="reps"),
        ]],
        phase_ends_at=datetime(2026, 1, 5, 0, 0, 5, tzinfo=UTC),
    )

    detail = await repo.get_for_user(created.id, user.id)
    assert detail is not None
    assert detail.client_session_id == client_session_id
    assert detail.phase_name == SessionPhase.GET_READY
    assert detail.phase_ends_at == datetime(2026, 1, 5, 0, 0, 5, tzinfo=UTC)
    assert detail.current_block_index == 0
    assert detail.current_set_number == 1
    assert detail.phase_index == 0
    assert len(detail.blocks) == 1
    assert [t.value for t in detail.blocks[0].set_targets] == [Decimal(15), Decimal(15)]
    assert detail.blocks[0].set_logs == []


async def test_get_by_client_session_id_is_idempotent_lookup(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    client_session_id = uuid.uuid4()
    created = await repo.create_live_session(
        user_id=user.id, client_session_id=client_session_id, source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps")]],
        phase_ends_at=None,
    )

    found = await repo.get_by_client_session_id(user.id, client_session_id)
    assert found is not None
    assert found.id == created.id
    assert await repo.get_by_client_session_id(user.id, uuid.uuid4()) is None


async def test_get_active_for_user_returns_only_started_sessions(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    assert await repo.get_active_for_user(user.id) is None

    live = await repo.create_live_session(
        user_id=user.id, client_session_id=uuid.uuid4(), source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps")]],
        phase_ends_at=None,
    )

    active = await repo.get_active_for_user(user.id)
    assert active is not None
    assert active.id == live.id

    await repo.mark_completed(live.id)
    assert await repo.get_active_for_user(user.id) is None


async def test_advance_phase_updates_state(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    live = await repo.create_live_session(
        user_id=user.id, client_session_id=uuid.uuid4(), source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps")]],
        phase_ends_at=datetime(2026, 1, 5, 0, 0, 5, tzinfo=UTC),
    )

    await repo.advance_phase(
        live.id, phase_name=SessionPhase.GO, phase_ends_at=None,
        current_block_index=0, current_set_number=1, phase_index=1,
    )

    detail = await repo.get_for_user(live.id, user.id)
    assert detail.phase_name == SessionPhase.GO
    assert detail.phase_ends_at is None
    assert detail.phase_index == 1


async def test_upsert_set_logs_batch_inserts_with_sequential_set_number(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    live = await repo.create_live_session(
        user_id=user.id, client_session_id=uuid.uuid4(), source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[
            SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps"),
            SetTargetInput(set_number=2, metric_type=MetricType.REPS, value=Decimal(15), unit="reps"),
            SetTargetInput(set_number=3, metric_type=MetricType.REPS, value=Decimal(15), unit="reps"),
        ]],
        phase_ends_at=None,
    )

    await repo.upsert_set_logs_batch(live.id, [
        BatchSetLogInput(set_index=0, exercise_id=exercise, value=Decimal(14)),
        BatchSetLogInput(set_index=1, exercise_id=exercise, value=Decimal(15)),
        BatchSetLogInput(set_index=2, exercise_id=exercise, value=Decimal(16)),
    ])

    detail = await repo.get_for_user(live.id, user.id)
    logs = detail.blocks[0].set_logs
    assert [log.set_number for log in logs] == [1, 2, 3]
    assert [log.value for log in logs] == [Decimal(14), Decimal(15), Decimal(16)]
    assert all(log.unit == "reps" for log in logs)


async def test_upsert_set_logs_batch_resend_same_batch_is_noop(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    live = await repo.create_live_session(
        user_id=user.id, client_session_id=uuid.uuid4(), source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps")]],
        phase_ends_at=None,
    )
    entries = [BatchSetLogInput(set_index=0, exercise_id=exercise, value=Decimal(14))]

    await repo.upsert_set_logs_batch(live.id, entries)
    await repo.upsert_set_logs_batch(live.id, entries)  # тот же батч повторно

    detail = await repo.get_for_user(live.id, user.id)
    logs = detail.blocks[0].set_logs
    assert len(logs) == 1  # не задублировалось
    assert logs[0].value == Decimal(14)


async def test_upsert_set_logs_batch_resend_with_different_value_overwrites(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    live = await repo.create_live_session(
        user_id=user.id, client_session_id=uuid.uuid4(), source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps")]],
        phase_ends_at=None,
    )

    await repo.upsert_set_logs_batch(live.id, [BatchSetLogInput(set_index=0, exercise_id=exercise, value=Decimal(14))])
    await repo.upsert_set_logs_batch(
        live.id, [BatchSetLogInput(set_index=0, exercise_id=exercise, value=Decimal(17), note="исправлено")],
    )

    detail = await repo.get_for_user(live.id, user.id)
    logs = detail.blocks[0].set_logs
    assert len(logs) == 1  # правка того же set_index - не вторая строка
    assert logs[0].value == Decimal(17)
    assert logs[0].note == "исправлено"


async def test_upsert_set_logs_batch_raises_for_exercise_not_in_session(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    other_exercise = await _make_exercise(session, "Другое упражнение")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    live = await repo.create_live_session(
        user_id=user.id, client_session_id=uuid.uuid4(), source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps")]],
        phase_ends_at=None,
    )

    with pytest.raises(ValueError, match=str(other_exercise)):
        await repo.upsert_set_logs_batch(
            live.id, [BatchSetLogInput(set_index=0, exercise_id=other_exercise, value=Decimal(14))],
        )


async def test_mark_completed_sets_status_and_clears_phase(session, user: User):
    exercise = await _make_exercise(session, "Live block")
    plan_item_id = await _make_plan_item(session, user, exercise)
    repo = TrainingSessionRepository(session)
    live = await repo.create_live_session(
        user_id=user.id, client_session_id=uuid.uuid4(), source=SessionSource.PLAN,
        performed_at=datetime(2026, 1, 5, tzinfo=UTC), plan_item_ids=[plan_item_id],
        blocks=[SessionBlockInput(exercise_id=exercise, sets=[])],
        targets_by_block=[[SetTargetInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(15), unit="reps")]],
        phase_ends_at=datetime(2026, 1, 5, 0, 0, 5, tzinfo=UTC),
    )

    await repo.mark_completed(live.id)

    detail = await repo.get_for_user(live.id, user.id)
    assert detail.status == SessionStatus.COMPLETED
    assert detail.phase_name == SessionPhase.DONE
    assert detail.phase_ends_at is None
