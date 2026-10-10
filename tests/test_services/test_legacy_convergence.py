"""#308 — dual-write писателей старой схемы в нативную копию TrainingSession (MIGRATION_V2 §4).

Каждый писатель legacy (запись, бэкдейт, свободные подтягивания, правка каскадной и некаскадной, удаление, факультатив,
админ-сброс) оставляет РОВНО ОДНУ копию с ключом (origin, legacy_id), и копия совпадает с legacy-строкой."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout, User, Workout
from app.db.models_program import SessionBlock, SetLog, TrainingSession
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.legacy_convergence import (
    ConvergenceOutcome,
    LegacyConvergenceRepository,
)
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.multi_program import SessionSource
from app.domain.session import BlockLog
from app.domain.training_session_v2 import SessionOrigin, SessionSourceV2
from app.services.admin_reset import reset_user_progress
from app.services.elective_log import ElectiveLogService
from app.services.workout_deletion import delete_cascade_workout, delete_noncascade_workout

AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
BAND = Decimal("15.0")


async def _workout_set(session: AsyncSession, user: User):
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=AT - timedelta(days=30), reps=10)
    return await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)


def _kwargs(user: User, workout_set, at: datetime, max_a: int = 11) -> dict:
    return {
        "user_id": user.id, "workout_set_id": workout_set.id, "performed_at": at,
        "block_a_reps": BlockLog(working_reps=(10, 10, 10), max_reps=max_a),
        "block_b_reps": BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        "block_a_equipment_type": EquipmentType.BAND, "block_a_equipment_value": BAND,
        "block_b_equipment_type": EquipmentType.BAND, "block_b_equipment_value": BAND,
    }


async def _copies(session: AsyncSession, user: User, origin: SessionOrigin) -> list[TrainingSession]:
    return list((await session.execute(
        select(TrainingSession).where(TrainingSession.user_id == user.id, TrainingSession.origin == origin.value)
        .order_by(TrainingSession.id),
    )).scalars().all())


async def _logs(session: AsyncSession, copy_id: int) -> list[tuple[int, int, bool, Decimal]]:
    rows = (await session.execute(
        select(SessionBlock.order_index, SetLog.set_number, SetLog.is_max_set, SetLog.value)
        .join(SetLog, SetLog.session_block_id == SessionBlock.id).where(SessionBlock.session_id == copy_id)
        .order_by(SessionBlock.order_index, SetLog.set_number),
    )).all()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


async def test_every_legacy_writer_leaves_exactly_one_matching_copy(session: AsyncSession, user: User):
    workout_set = await _workout_set(session, user)
    repo = WorkoutRepository(session)
    cascade = await repo.record_workout(**_kwargs(user, workout_set, AT, 11))
    backdated = await repo.record_backdated_workout(**{k: v for k, v in _kwargs(user, workout_set, AT + timedelta(hours=1), 12).items()})
    free = await repo.record_free_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=AT + timedelta(hours=2),
        block_a_reps=BlockLog(working_reps=(5, 5), max_reps=6), equipment_type=EquipmentType.BODYWEIGHT,
    )

    copies = await _copies(session, user, SessionOrigin.LEGACY_BACKFILL)
    assert [c.legacy_id for c in copies] == [cascade.id, backdated.id, free.id]
    assert [c.source for c in copies] == [SessionSource.PLAN, SessionSource.BACKDATED, SessionSource.FREEFORM]
    assert [c.source_v2 for c in copies] == [
        SessionSourceV2.PLANNED_LIVE.value, SessionSourceV2.MANUAL_CUSTOM.value, SessionSourceV2.MANUAL_CUSTOM.value,
    ]
    assert all(c.status == "completed" and c.duration_source == "unknown" and c.revision == 0 for c in copies)
    assert [c.performed_at for c in copies] == [AT, AT + timedelta(hours=1), AT + timedelta(hours=2)]
    # блок A: рабочие подходы + максимум; блок Б — у свободной записи отсутствует (фиктивный блок не переносится)
    assert await _logs(session, copies[0].id) == [
        (0, 1, False, 10), (0, 2, False, 10), (0, 3, False, 10), (0, 4, True, 11),
        (1, 1, False, 3), (1, 2, False, 3), (1, 3, False, 3), (1, 4, False, 3), (1, 5, True, 3),
    ]
    assert await _logs(session, copies[2].id) == [(0, 1, False, 5), (0, 2, False, 5), (0, 3, True, 6)]


async def test_edits_update_the_copy_and_unrelated_writes_do_not_bump_the_revision(session: AsyncSession, user: User):
    workout_set = await _workout_set(session, user)
    repo = WorkoutRepository(session)
    cascade = await repo.record_workout(**_kwargs(user, workout_set, AT, 11))
    backdated = await repo.record_backdated_workout(**_kwargs(user, workout_set, AT + timedelta(hours=1), 12))

    await repo.edit_workout(workout_id=cascade.id, block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=15), comment="правка")
    await repo.edit_noncascade_workout(workout_id=backdated.id, block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5))
    await repo.correct_block_equipment(workout_id=backdated.id, block_type=cascade.blocks[0].block_type, equipment_value=Decimal("20.0"))

    first, second = await _copies(session, user, SessionOrigin.LEGACY_BACKFILL)
    assert (first.comment, first.revision) == ("правка", 1)
    assert (await _logs(session, first.id))[:4] == [(0, 1, False, 10), (0, 2, False, 10), (0, 3, False, 9), (0, 4, True, 15)]
    assert second.revision == 1 and (await _logs(session, second.id))[-1] == (1, 5, True, 5)
    # повторное сведение того же состояния — 0 изменений, ревизия не растёт
    for workout_id in (cascade.id, backdated.id):
        workout = await repo.get_by_id(workout_id)
        assert await LegacyConvergenceRepository(session).sync_workout(workout) is ConvergenceOutcome.UNCHANGED
    assert (first.revision, second.revision) == (1, 1)


async def test_deleting_legacy_workouts_supersedes_their_copies(session: AsyncSession, user: User):
    workout_set = await _workout_set(session, user)
    repo = WorkoutRepository(session)
    cascade = await repo.record_workout(**_kwargs(user, workout_set, AT, 11))
    backdated = await repo.record_backdated_workout(**_kwargs(user, workout_set, AT + timedelta(hours=1), 12))

    await delete_noncascade_workout(session, backdated)
    await delete_cascade_workout(session, await repo.get_by_id(cascade.id))

    copies = await _copies(session, user, SessionOrigin.LEGACY_BACKFILL)
    assert len(copies) == 2  # строки не удалены (архивировать, не удалять)
    assert all(c.superseded_at is not None and c.superseded_reason == "legacy_deleted" for c in copies)
    assert await session.scalar(select(func.count()).select_from(Workout).where(Workout.user_id == user.id)) == 0


async def test_elective_dual_write_is_idempotent_and_the_copy_belongs_to_the_journal(session: AsyncSession, user: User):
    elective = await ElectiveLogService(session).record(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=AT, total_reps=9,
        reps_sequence=[4, 3, 2], equipment_type=EquipmentType.BAND, equipment_value=BAND,
    )
    [copy] = await _copies(session, user, SessionOrigin.LEGACY_ELECTIVE)
    assert (copy.legacy_id, copy.source, copy.source_v2) == (elective.id, SessionSource.ELECTIVE, "manual_existing_workout")

    # правка копии в Журнале и повторное сведение: правка не откатывается, дубль не появляется
    log = await session.scalar(select(SetLog).join(SessionBlock).where(SessionBlock.session_id == copy.id))
    log.value = Decimal(20)
    await session.flush()
    repo = LegacyConvergenceRepository(session)
    assert await repo.sync_elective(await session.get(ElectiveWorkout, elective.id)) is ConvergenceOutcome.UNCHANGED
    assert len(await _copies(session, user, SessionOrigin.LEGACY_ELECTIVE)) == 1
    await session.refresh(log)
    assert log.value == 20


async def test_admin_reset_supersedes_all_copies_of_the_user(session: AsyncSession, user: User):
    workout_set = await _workout_set(session, user)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, AT, 11))
    await repo.record_backdated_workout(**_kwargs(user, workout_set, AT + timedelta(hours=1), 12))
    await ElectiveLogService(session).record(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=AT, total_reps=40, reps_sequence=None,
        equipment_type=EquipmentType.BODYWEIGHT,
    )

    await reset_user_progress(session, user.id)

    workout_copies = await _copies(session, user, SessionOrigin.LEGACY_BACKFILL)
    assert len(workout_copies) == 2 and all(c.superseded_reason == "legacy_deleted" for c in workout_copies)
    [elective_copy] = await _copies(session, user, SessionOrigin.LEGACY_ELECTIVE)
    assert elective_copy.superseded_at is None  # elective_workouts сброс не затрагивает
