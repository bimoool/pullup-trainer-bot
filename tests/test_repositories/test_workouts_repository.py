from datetime import UTC, datetime

from app.db.models import Branch, Equipment, User, WorkoutStatus
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import BLOCK_A, BLOCK_B
from app.domain.session import BlockLog

BAND = 22.0
WEIGHT = 10.0


async def _make_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC),
        branch_result=Branch.BAND, equipment_type=Equipment.BAND, reps=18,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    return workout_set.id


def _day(n: int) -> datetime:
    return datetime(2026, 1, n, tzinfo=UTC)


async def test_record_workout_first_ever_starts_from_domain_base_targets(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=16),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    block_a = next(b for b in workout.blocks if b.block_type.value == "a")
    block_b = next(b for b in workout.blocks if b.block_type.value == "b")
    assert workout.sequence_number == 1
    assert workout.status == WorkoutStatus.COMPLETED
    assert block_a.target_before == BLOCK_A.base_target
    assert block_a.target_after == 16  # delta=1, step=min(3, ceil(0.5))=1
    assert block_b.target_before == BLOCK_B.base_target
    assert block_b.target_after == 4


async def test_record_workout_second_continues_from_first_target_after(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=16),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    second = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(4),
        block_a_reps=BlockLog(working_reps=(16, 16, 16), max_reps=16),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=4),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    block_a = next(b for b in second.blocks if b.block_type.value == "a")
    assert second.sequence_number == 2
    assert block_a.target_before == 16  # = target_after первой тренировки


async def test_record_workout_reaching_change_at_switches_equipment(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(18, 18, 18), max_reps=21),
        block_b_reps=BlockLog(working_reps=(6, 6, 6, 6), max_reps=9),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    # это не первая тренировка в домене (target_before там не 18/6), поэтому
    # реальный сценарий смены снаряда собираем через два вызова record_workout
    second = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(4),
        block_a_reps=BlockLog(working_reps=(18, 18, 18), max_reps=21),
        block_b_reps=BlockLog(working_reps=(6, 6, 6, 6), max_reps=9),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    block_a_1 = next(b for b in workout.blocks if b.block_type.value == "a")
    block_a_2 = next(b for b in second.blocks if b.block_type.value == "a")
    # первая: target_before=15(base), delta=21-15=6, step=min(3, ceil(3))=3 -> 18, ещё не порог
    assert block_a_1.target_after == 18
    assert not block_a_1.equipment_changed
    # вторая: target_before=18, delta=21-18=3, step=min(3, ceil(1.5))=2 -> 20 >= change_at(20)
    assert block_a_2.equipment_changed is True
    assert block_a_2.target_after == BLOCK_A.base_target


async def test_backdated_insertion_renumbers_and_cascades(session, user: User):
    """Ключевой тест: тренировка вносится задним числом МЕЖДУ двумя уже
    сохранёнными. sequence_number существующих должен сдвинуться, а
    target_before/target_after всех тренировок после точки вставки —
    пересчитаться через domain.recalculate_cascade, а не остаться от
    старого порядка."""
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    first = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=18),  # -> target_after 16 (delta3,cap? ceil(1.5)=2->17) пересчитаем ниже по факту
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    third = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(10),
        block_a_reps=BlockLog(working_reps=(17, 17, 17), max_reps=16),  # delta<0
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    first_block_a = next(b for b in first.blocks if b.block_type.value == "a")
    assert first.sequence_number == 1
    assert third.sequence_number == 2  # пока только две тренировки

    # third была посчитана от target_before = first.target_after (17), с volume
    # первой = 15+15+15+18=63, prev_volume не важен для delta>0 у first.
    # Значения снимаем в переменные СРАЗУ — third.blocks те же ORM-объекты,
    # что вернёт repo.get_by_id(third.id) позже (identity map SQLAlchemy),
    # и каскад их замутирует на месте; ссылку сравнивать нельзя, только value.
    third_block_a_before_insert = next(b for b in third.blocks if b.block_type.value == "a")
    target_before_pre_cascade = third_block_a_before_insert.target_before
    assert target_before_pre_cascade == first_block_a.target_after

    # теперь вставляем задним числом между first (day 1) и third (day 10);
    # max_reps=19 при target_before=17 даёт delta=2 -> target_after=18,
    # так что у third target_before реально сдвинется (17 -> 18), а не
    # случайно совпадёт со старым значением
    second = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(5),
        block_a_reps=BlockLog(working_reps=(17, 17, 17), max_reps=19),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=4),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    updated_third = await repo.get_by_id(third.id)
    second_block_a = next(b for b in second.blocks if b.block_type.value == "a")
    updated_third_block_a = next(b for b in updated_third.blocks if b.block_type.value == "a")

    # перенумерация: second встала между first и third
    assert second.sequence_number == 2
    assert updated_third.sequence_number == 3

    # second унаследовала target_before от first (единственной тренировки до неё)
    assert second_block_a.target_before == first_block_a.target_after
    assert second_block_a.target_after == 18  # delta=2, ceil(1.0)=1 -> 17+1

    # third была ПЕРЕСЧИТАНА от нового target_before = second.target_after,
    # а не осталась со старым значением (это и есть проверка каскада)
    assert updated_third_block_a.target_before == second_block_a.target_after
    assert updated_third_block_a.target_before != target_before_pre_cascade

    # реальные повторения third не изменились от каскада
    assert updated_third_block_a.working_reps == [17, 17, 17]


async def test_edit_workout_reps_cascades_forward(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    first = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),  # delta=0
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    second = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(4),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    # снимаем значение сразу — second.blocks те же ORM-объекты, что вернёт
    # get_by_id(second.id) позже, каскад замутирует их на месте
    second_block_a_before = next(b for b in second.blocks if b.block_type.value == "a")
    target_before_pre_edit = second_block_a_before.target_before
    assert target_before_pre_edit == 15

    # редактируем первую тренировку — вместо 15 15 15 / 15 теперь большой
    # максимум, target_after первой вырастет и должен утащить за собой вторую
    edited_first = await repo.edit_workout(
        workout_id=first.id,
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=20),
    )
    edited_first_block_a = next(b for b in edited_first.blocks if b.block_type.value == "a")
    assert edited_first_block_a.target_after == 18  # delta=5, ceil(2.5)=3, cap 3 -> 18

    updated_second = await repo.get_by_id(second.id)
    updated_second_block_a = next(b for b in updated_second.blocks if b.block_type.value == "a")
    assert updated_second_block_a.target_before == 18
    assert updated_second_block_a.target_before != target_before_pre_edit


async def test_complete_workout_increments_set_counter(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    workout_set = await WorkoutSetRepository(session).get_by_id(workout_set_id)
    assert workout_set.workouts_completed == 1


async def test_start_then_complete_workout(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    started = await repo.start_workout(user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1))
    assert started.status == WorkoutStatus.STARTED
    assert started.sequence_number is None
    assert started.blocks == []

    completed = await repo.complete_workout(
        workout_id=started.id,
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=16),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    assert completed.status == WorkoutStatus.COMPLETED
    assert completed.sequence_number == 1


async def test_list_for_user_excludes_started_workouts(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.start_workout(user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1))
    completed = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(2),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    workouts = await repo.list_for_user(user.id)
    assert [w.id for w in workouts] == [completed.id]
