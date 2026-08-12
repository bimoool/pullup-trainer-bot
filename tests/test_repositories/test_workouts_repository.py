from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.db.models import BlockType, User, WorkoutStatus
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType, ExerciseType
from app.domain.session import BlockLog

BAND_VALUE = Decimal("30.0")


async def _make_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=8,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    return workout_set.id


def _day(n: int) -> datetime:
    return datetime(2026, 1, n, tzinfo=UTC)


def _block(workout, block_type: str):
    return next(b for b in workout.blocks if b.block_type.value == block_type)


async def test_record_workout_first_ever_starts_from_domain_base_targets(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    block_a, block_b = _block(workout, "a"), _block(workout, "b")
    assert workout.sequence_number == 1
    assert workout.status == WorkoutStatus.COMPLETED
    assert block_a.target_before == VOLUME_BLOCK.base_target
    # Часть 10, пакет #2: формула роста считает шаг от avg_working (11), не
    # от target (10) — avg=11, growth=12-11=1, step=min(3,ceil(0.5))=1 -> 12
    assert block_a.target_after == 12
    assert block_b.target_before == STRENGTH_BLOCK.base_target
    # avg=4, growth=5-4=1, step=min(2,ceil(0.5))=1 -> 5
    assert block_b.target_after == 5
    assert block_a.equipment_type == EquipmentType.BAND
    assert block_a.equipment_value == BAND_VALUE


async def test_record_workout_second_continues_from_first_target_after(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    second = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(4),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    block_a = _block(second, "a")
    assert second.sequence_number == 2
    assert block_a.target_before == 12  # = target_after первой тренировки (см. тест выше)


async def test_equipment_change_threshold_and_failed_transition_reverts_to_prior_gear(session, user: User):
    """Ключевой сценарий: все рабочие подходы объёмного блока достигают
    порога (20) -> снаряд меняется. Следующая тренировка на новом снаряде
    проваливается (max < min_viable=10) -> цель откатывается на
    target_before неудачной попытки (10 -> исходный base_target первой
    тренировки), снаряд возвращается к прежнему, а не к неудачному —
    _resolve_next_state должен заглянуть на шаг раньше за equipment."""
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    first = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=21),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    first_block_a = _block(first, "a")
    assert first_block_a.target_before == VOLUME_BLOCK.base_target  # 10, первая тренировка
    assert first_block_a.equipment_changed is True
    assert first_block_a.target_after == VOLUME_BLOCK.base_target  # порог достигнут -> сброс на base_target

    second = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(4),
        block_a_reps=BlockLog(working_reps=(5, 5, 5), max_reps=8),  # max < min_viable_reps(10) -> провал
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    second_block_a = _block(second, "a")
    assert second_block_a.transition_failed is True
    assert second_block_a.equipment_changed is False
    assert second_block_a.target_after == first_block_a.target_before  # откат на target_before неудачной попытки
    assert second_block_a.equipment_type == EquipmentType.BODYWEIGHT  # факт того, что реально пробовали

    third = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(7),
        block_a_reps=BlockLog(working_reps=(12, 12, 12), max_reps=13),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    third_block_a = _block(third, "a")
    # снаряд для третьей тренировки должен быть предложен со ШАГА ДО
    # неудачной попытки (тот же BAND, что и в первой тренировке), а не
    # BODYWEIGHT, на котором провалились
    assert third_block_a.target_before == second_block_a.target_after


async def test_bodyweight_ceiling_caps_volume_target_and_does_not_switch_equipment(session, user: User):
    # Часть 10, пакет #2: под новой формулой роста target больше не растёт
    # кумулятивно на max_step каждый раз при одинаковых working_reps (шаг
    # считается от avg_working, а не накапливается поверх предыдущего
    # target) — фиксированные working_reps=15 сходятся к 15+max_step=18 и
    # там и остаются, к потолку не подбираются. Чтобы реально дотянуться до
    # потолка, working_reps сами должны быть достаточно высоки — единственный
    # вызов с working_reps=26 уже за потолком (25) демонстрирует cap.
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(26, 26, 26), max_reps=27),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    block_a = _block(workout, "a")
    assert block_a.target_after == VOLUME_BLOCK.bodyweight_ceiling
    assert block_a.equipment_changed is False


async def test_backdated_workout_excluded_from_cascade_but_drives_target_derivation(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    first = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    first_block_a = _block(first, "a")
    # Часть 10, пакет #2: avg=11, growth=12-11=1, step=1 -> 12 (не 11 — см.
    # test_record_workout_first_ever_starts_from_domain_base_targets)
    assert first_block_a.target_after == 12

    backdated = await repo.record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(2),
        block_a_reps=BlockLog(working_reps=(14, 14, 14), max_reps=15),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    backdated_block_a = _block(backdated, "a")
    assert backdated.sequence_number is None
    assert backdated.participates_in_cascade is False
    assert backdated_block_a.target_before == first_block_a.target_after  # 12
    # avg=14, growth=15-14=1, step=min(3,ceil(0.5))=1 -> 15
    assert backdated_block_a.target_after == 15

    third = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(3),
        block_a_reps=BlockLog(working_reps=(12, 12, 12), max_reps=13),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    third_block_a = _block(third, "a")
    # цель для третьей тренировки выведена из ПОСЛЕДНЕЙ ПО ДАТЕ записи любого
    # происхождения — то есть из внесённой задним числом, а не из первой
    assert third_block_a.target_before == backdated_block_a.target_after  # 15
    # но нумерация цепочки каскада backdated не учитывает — вторая позиция
    assert third.sequence_number == 2

    edited_first = await repo.edit_workout(
        workout_id=first.id,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=14),
    )
    edited_first_block_a = _block(edited_first, "a")
    # avg=11, growth=14-11=3, step=min(3,ceil(1.5))=2 -> 13
    assert edited_first_block_a.target_after == 13

    updated_backdated = await repo.get_by_id(backdated.id)
    updated_backdated_block_a = _block(updated_backdated, "a")
    # каскад НЕ трогает внесённую задним числом тренировку — её собственные
    # target_before/after остаются снимком на момент записи, не переигрываются
    assert updated_backdated_block_a.target_before == 12
    assert updated_backdated_block_a.target_after == 15

    updated_third = await repo.get_by_id(third.id)
    updated_third_block_a = _block(updated_third, "a")
    # каскад пересчитал третью от НОВОГО target_after первой (13), полностью
    # игнорируя внесённую задним числом — она не часть цепочки каскада
    assert updated_third_block_a.target_before == 13
    assert updated_third_block_a.target_before != updated_backdated_block_a.target_after


async def test_edit_workout_raises_for_backdated_workout(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    backdated = await repo.record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    with pytest.raises(ValueError, match="cascade"):
        await repo.edit_workout(workout_id=backdated.id, block_a_reps=BlockLog(working_reps=(12, 12, 12), max_reps=13))


async def test_complete_workout_increments_set_counter(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
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
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    assert completed.status == WorkoutStatus.COMPLETED
    assert completed.sequence_number == 1


async def test_resolve_next_targets_reports_needs_new_equipment(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    empty_a, empty_b = await repo.resolve_next_targets(user.id)
    assert empty_a.needs_new_equipment is True
    assert empty_b.needs_new_equipment is True

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=21),  # достигает порога -> equipment_changed
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    next_a, next_b = await repo.resolve_next_targets(user.id)
    assert next_a.needs_new_equipment is True  # объёмный блок сменил снаряд
    assert next_b.needs_new_equipment is False  # силовой — нет, ниже порога
    assert next_b.equipment_type == EquipmentType.BAND
    assert next_b.equipment_value == BAND_VALUE


async def test_list_for_user_includes_backdated_and_excludes_started(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.start_workout(user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1))
    completed = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(2),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    backdated = await repo.record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    workouts = await repo.list_for_user(user.id)
    assert [w.id for w in workouts] == [completed.id, backdated.id]


async def test_abandoned_set_workouts_stay_with_old_set_after_cycle_restart(session, user: User):
    """"Завершить цикл и начать заново" (Профиль) не архивирует и не
    перемещает старые тренировки — они уже физически отделены от нового
    цикла через workout_set_id, см. app/bot/handlers/workout.py::
    handle_end_cycle_confirm. list_for_user (История/Прогресс/Отчёты)
    продолжает видеть обе тренировки — это единая непрерывная история."""
    old_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    old_workout = await repo.record_workout(
        user_id=user.id, workout_set_id=old_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    workout_sets = WorkoutSetRepository(session)
    await workout_sets.mark_abandoned(old_set_id, abandoned_at=_day(2))
    new_baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=_day(2), reps=10,
    )
    new_set = await workout_sets.create(user_id=user.id, started_from_baseline_id=new_baseline.id)

    new_workout = await repo.record_workout(
        user_id=user.id, workout_set_id=new_set.id, performed_at=_day(3),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=10),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    # старая тренировка осталась в старом (заброшенном) сете
    old_set_workouts = await repo.list_for_set(old_set_id)
    assert [w.id for w in old_set_workouts] == [old_workout.id]
    new_set_workouts = await repo.list_for_set(new_set.id)
    assert [w.id for w in new_set_workouts] == [new_workout.id]

    # но обе видны в общей истории пользователя — ничего не спрятано
    all_workouts = await repo.list_for_user(user.id)
    assert [w.id for w in all_workouts] == [old_workout.id, new_workout.id]


async def test_record_workout_persists_equipment_item_id_on_blocks(session, user: User):
    """Часть 8: для BAND снаряд теперь ссылка на личный список
    (equipment_items), а не equipment_value — repository должен сохранить
    этот id на Block, не потеряв его по пути."""
    workout_set_id = await _make_set(session, user)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="зелёная")
    repo = WorkoutRepository(session)

    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=BAND_VALUE,
        block_a_equipment_item_id=item.id,
    )

    block_a, block_b = _block(workout, "a"), _block(workout, "b")
    assert block_a.equipment_item_id == item.id
    assert block_b.equipment_item_id is None


async def test_resolve_next_targets_carries_equipment_item_id_forward(session, user: User):
    """resolve_next_targets (использует _resolve_next_state) — то, что
    хендлер показывает как "текущий снаряд" перед следующей тренировкой,
    должно включать equipment_item_id, а не только type/value."""
    workout_set_id = await _make_set(session, user)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="широкая фиолетовая")
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=None,
        block_a_equipment_item_id=item.id, block_b_equipment_item_id=item.id,
    )

    target_a_state, _ = await repo.resolve_next_targets(user.id)

    assert target_a_state.equipment_item_id == item.id
    assert target_a_state.needs_new_equipment is False


async def test_list_records_for_set_populates_workout_set_id_and_exercise_type(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    records = await repo.list_records_for_set(workout_set_id)

    assert len(records) == 1
    assert records[0].workout_set_id == workout_set_id
    assert records[0].exercise_type == ExerciseType.PULL_UPS


async def test_resolve_next_targets_bypass_transition_wait_forces_new_prompt(session, user: User):
    """Часть 9 (админ-тестирование): по умолчанию (bypass_transition_wait=
    False) поведение не меняется — после провала перехода needs_new_equipment
    остаётся False. Домен (_apply_transition_outcome/check_transition_outcome)
    не трогаем — только этот флаг в репозитории."""
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    _block(workout, "a").transition_failed = True
    await session.flush()

    normal_a, _ = await repo.resolve_next_targets(user.id)
    assert normal_a.needs_new_equipment is False

    admin_a, _ = await repo.resolve_next_targets(user.id, bypass_transition_wait=True)
    assert admin_a.needs_new_equipment is True


async def test_resolve_next_targets_bypass_does_not_affect_blocks_without_failed_transition(
    session, user: User,
):
    """bypass_transition_wait=True не должен трогать блоки, где перехода
    вообще не было — только те, где transition_failed=True."""
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    admin_a, admin_b = await repo.resolve_next_targets(user.id, bypass_transition_wait=True)
    assert admin_a.needs_new_equipment is False
    assert admin_b.needs_new_equipment is False


async def test_resolve_next_targets_bypass_with_two_workout_history(session, user: User):
    """Реалистичный случай (len(history) >= 2, где обычно срабатывает
    "тихий откат на equipment_source из history[-2]") — админ вместо этого
    сразу получает needs_new_equipment=True для проваленного блока."""
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    second = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(2),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.WEIGHT, block_a_equipment_value=Decimal("40.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    _block(second, "a").transition_failed = True
    await session.flush()

    normal_a, _ = await repo.resolve_next_targets(user.id)
    assert normal_a.needs_new_equipment is False
    assert normal_a.equipment_type == EquipmentType.BAND  # снаряд ДО провала, а не WEIGHT

    admin_a, _ = await repo.resolve_next_targets(user.id, bypass_transition_wait=True)
    assert admin_a.needs_new_equipment is True


async def test_correct_block_equipment_updates_value_without_touching_target(session, user: User):
    """Часть 10: правка веса/резины "в этом же отчёте" — только
    исправление ошибки ввода, target_before/after не пересчитывается."""
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)
    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("20.0"),
    )
    block_b_before = _block(workout, "b")
    target_before, target_after = block_b_before.target_before, block_b_before.target_after

    updated = await repo.correct_block_equipment(
        workout_id=workout.id, block_type=BlockType.B, equipment_value=Decimal("22.5"),
    )

    updated_block_b = _block(updated, "b")
    assert updated_block_b.equipment_value == Decimal("22.5")
    assert updated_block_b.target_before == target_before
    assert updated_block_b.target_after == target_after


async def test_correct_block_equipment_updates_item_id(session, user: User):
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="широкая")
    other_item = await EquipmentItemRepository(session).create(user_id=user.id, name="узкая")
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)
    workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=None,
        block_a_equipment_item_id=item.id,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    updated = await repo.correct_block_equipment(
        workout_id=workout.id, block_type=BlockType.A, equipment_item_id=other_item.id,
    )

    assert _block(updated, "a").equipment_item_id == other_item.id


# --- record_free_workout (Часть 10, п. 18) -----------------------------------------


async def test_record_free_workout_stores_reps_as_block_a_max(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    workout = await repo.record_free_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1), reps=8,
    )

    block_a, block_b = _block(workout, "a"), _block(workout, "b")
    assert block_a.working_reps == []
    assert block_a.max_reps == 8
    assert block_a.equipment_type == EquipmentType.BODYWEIGHT
    assert block_b.max_reps == 0
    assert workout.participates_in_cascade is False
    assert workout.sequence_number is None
    assert workout.is_free_entry is True


async def test_record_free_workout_does_not_increment_set_counter(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    await repo.record_free_workout(user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1), reps=8)

    workout_set = await WorkoutSetRepository(session).get_by_id(workout_set_id)
    assert workout_set.workouts_completed == 0


async def test_record_free_workout_does_not_affect_resolve_next_targets(session, user: User):
    """Часть 10: свободная тренировка не должна становиться "последним
    известным снарядом" для следующей структурированной — иначе прогрессия
    на реальном снаряде (например BAND) молча съехала бы на bodyweight."""
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)

    real_workout = await repo.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    real_block_a = _block(real_workout, "a")

    await repo.record_free_workout(user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(2), reps=8)

    target_a_state, _ = await repo.resolve_next_targets(user.id)
    assert target_a_state.equipment_type == EquipmentType.BAND
    assert target_a_state.target == real_block_a.target_after


async def test_record_free_workout_appears_in_list_for_user_for_stats(session, user: User):
    workout_set_id = await _make_set(session, user)
    repo = WorkoutRepository(session)
    await repo.record_free_workout(user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1), reps=8)

    history = await repo.list_for_user(user.id)
    assert len(history) == 1
    assert history[0].is_free_entry is True
