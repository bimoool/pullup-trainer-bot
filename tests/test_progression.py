from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.constants import (
    STRENGTH_BLOCK,
    VOLUME_BIG_OVERSHOOT_THRESHOLD,
    VOLUME_BLOCK,
    VOLUME_MODERATE_ROLLBACK_TARGET,
    VOLUME_STALL_THRESHOLD,
    VOLUME_TARGET_CEILING,
    VOLUME_WORK_SETS_CEILING,
    EquipmentType,
    to_signed_load,
)
from app.domain.progression import (
    ProgressionResult,
    TransitionOutcome,
    VolumeBlockResult,
    check_transition_outcome,
    count_consecutive_stalled_workouts,
    count_consecutive_weak_trainings,
    grow_volume_weight_kg,
    initial_volume_target,
    is_retry_allowed,
    recalculate_cascade,
    recalculate_target,
    recalculate_volume_block,
    rollback_signed_load,
    rollback_target,
    suggest_starting_equipment,
    suggest_weight_range,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord

# --- to_signed_load ----------------------------------------------------------

def test_signed_load_band_is_negative():
    assert to_signed_load(EquipmentType.BAND, Decimal(30)) == -30


def test_signed_load_bodyweight_is_zero_regardless_of_value():
    assert to_signed_load(EquipmentType.BODYWEIGHT, None) == 0
    assert to_signed_load(EquipmentType.BODYWEIGHT, Decimal(5)) == 0


def test_signed_load_weight_is_positive():
    assert to_signed_load(EquipmentType.WEIGHT, Decimal(10)) == 10


def test_signed_load_weight_none_defaults_to_zero():
    assert to_signed_load(EquipmentType.WEIGHT, None) == 0


def test_signed_load_australian_raises():
    with pytest.raises(ValueError, match="australian"):
        to_signed_load(EquipmentType.AUSTRALIAN, None)


# --- recalculate_target: объёмный блок ---------------------------------------
# equipment_type больше не параметр recalculate_target (пятая ревизия формулы,
# см. app/domain/progression.py) — весь потолок/переход на вес для объёмного
# блока теперь в recalculate_volume_block, отдельно ниже.

def test_volume_small_overshoot_no_equipment_change():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 10), max_reps=11, volume=41, prev_volume=0,
    )
    assert result == ProgressionResult(new_target=11, equipment_changed=False)


def test_volume_threshold_hit_in_all_working_sets_triggers_change():
    # "20 20 20 21" — порог взят по факту, а не по расчётной цели
    result = recalculate_target(
        VOLUME_BLOCK, target=17, working_reps=(20, 20, 20), max_reps=21, volume=81, prev_volume=0,
    )
    assert result == ProgressionResult(new_target=VOLUME_BLOCK.base_target, equipment_changed=True)


def test_volume_high_max_but_working_sets_below_threshold_does_not_change():
    # "19 19 19 22" — максимум выше 20, но рабочие подходы не достали порог.
    # Новая формула: step=max(1,ceil(target*0.05))=max(1,ceil(17*0.05)=1)=1
    # -> round(19)+1=20 (было 21 при старой формуле с growth/coef).
    result = recalculate_target(
        VOLUME_BLOCK, target=17, working_reps=(19, 19, 19), max_reps=22, volume=79, prev_volume=0,
    )
    assert result.equipment_changed is False
    assert result.new_target == 20


def test_volume_missed_target_but_volume_grew_stays_flat():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9, volume=37, prev_volume=30,
    )
    assert result.new_target == 10


# --- recalculate_target: отсрочка отката, 3 подряд "слабых" -----------------
# Ветка провала (delta<=0) не зависит от процентного шага — числа не меняются.

def test_volume_equal_volume_is_not_weak_stays_flat_regardless_of_streak():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9, volume=37, prev_volume=37,
        consecutive_weak_before=5,
    )
    assert result.new_target == 10


def test_volume_first_weak_training_does_not_rollback():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9, volume=30, prev_volume=37,
        consecutive_weak_before=0,
    )
    assert result.new_target == 10


def test_volume_second_consecutive_weak_training_still_no_rollback():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9, volume=30, prev_volume=37,
        consecutive_weak_before=1,
    )
    assert result.new_target == 10


def test_volume_third_consecutive_weak_training_rolls_back():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9, volume=30, prev_volume=37,
        consecutive_weak_before=2,
    )
    assert result.new_target == 9


def test_volume_fourth_and_beyond_consecutive_weak_keeps_rolling_back():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9, volume=30, prev_volume=37,
        consecutive_weak_before=3,
    )
    assert result.new_target == 9


# --- recalculate_target: процентная формула шага (ревизия 5) ----------------
# Пересчитанная таблица примеров из плана (было при min(MAX_STEP,ceil(growth*coef))
# -> стало при max(1,ceil(target*STEP_PCT))).

def test_growth_formula_example_18_18_18_21_at_target_10():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(18, 18, 18), max_reps=21, volume=75, prev_volume=0,
    )
    # step=max(1,ceil(10*0.05)=1)=1 -> round(18)+1=19 (было 20)
    assert result.new_target == 19


def test_growth_formula_example_18_18_18_23_hypothetical_at_target_10():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(18, 18, 18), max_reps=23, volume=77, prev_volume=0,
    )
    # Шаг больше НЕ зависит от степени перевыполнения максимума — тот же
    # шаг(1), что и при max_reps=21 выше, несмотря на больший max_reps
    # (было 21 при старой формуле, чувствительной к growth).
    assert result.new_target == 19


def test_growth_formula_example_15_15_15_16_at_target_15():
    result = recalculate_target(
        VOLUME_BLOCK, target=15, working_reps=(15, 15, 15), max_reps=16, volume=61, prev_volume=0,
    )
    # step=max(1,ceil(15*0.05)=1)=1 -> round(15)+1=16 (совпадает со старым значением)
    assert result.new_target == 16


def test_growth_formula_example_15_15_15_20_at_target_15():
    result = recalculate_target(
        VOLUME_BLOCK, target=15, working_reps=(15, 15, 15), max_reps=20, volume=65, prev_volume=0,
    )
    # step=1 (было 3, кап по MAX_STEP) -> round(15)+1=16 (было 18)
    assert result.new_target == 16


def test_growth_formula_example_10_10_10_16_at_target_10():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 10), max_reps=16, volume=46, prev_volume=0,
    )
    # step=1 (было 3) -> round(10)+1=11 (было 13)
    assert result.new_target == 11


def test_growth_formula_example_20_20_20_21_yields_to_equipment_change_threshold():
    # "20 20 20 21" — working_reps=20 на каждом рабочем подходе = порог
    # смены снаряда, приоритетнее результата формулы (не зависит от шага).
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(20, 20, 20), max_reps=21, volume=81, prev_volume=0,
    )
    assert result.equipment_changed is True
    assert result.new_target == VOLUME_BLOCK.base_target


def test_growth_formula_step_is_always_at_least_one_even_when_working_reps_exceed_max():
    # Вырожденный случай: парсер ввода не проверяет working_reps <= max_reps
    # ("19 19 19 6" технически валидный ввод). Раньше max(0, ...) вокруг
    # шага мог занулить его при отрицательном growth, теперь шаг вообще не
    # зависит от growth — всегда >= 1, поэтому new_target гарантированно
    # строго больше avg_working (было 19 при старой формуле, стало 20).
    result = recalculate_target(
        VOLUME_BLOCK, target=5, working_reps=(19, 19, 19), max_reps=6, volume=63, prev_volume=0,
    )
    assert result.new_target == 20
    assert result.equipment_changed is False


# --- count_consecutive_weak_trainings ----------------------------------------

def test_weak_streak_empty_history_is_zero():
    assert count_consecutive_weak_trainings([]) == 0


def test_weak_streak_single_entry_has_nothing_to_compare_against():
    assert count_consecutive_weak_trainings([10]) == 0


def test_weak_streak_counts_trailing_consecutive_drops():
    assert count_consecutive_weak_trainings([10, 9]) == 1
    assert count_consecutive_weak_trainings([10, 9, 8]) == 2
    assert count_consecutive_weak_trainings([10, 9, 8, 7]) == 3


def test_weak_streak_equal_volume_resets_not_weak():
    assert count_consecutive_weak_trainings([10, 9, 9]) == 0


def test_weak_streak_only_counts_trailing_run_not_total_weak_count():
    assert count_consecutive_weak_trainings([10, 8, 9, 7]) == 1


# --- count_consecutive_stalled_workouts (иерархия роста, часть 2, застой) ---

def test_stall_streak_empty_history_is_zero():
    assert count_consecutive_stalled_workouts([]) == 0


def test_stall_streak_counts_trailing_non_growing_workouts():
    assert count_consecutive_stalled_workouts([True, False]) == 1
    assert count_consecutive_stalled_workouts([True, False, False]) == 2
    assert count_consecutive_stalled_workouts([True, False, False, False]) == 3


def test_stall_streak_growth_resets_to_zero():
    assert count_consecutive_stalled_workouts([False, False, True]) == 0


def test_stall_streak_only_counts_trailing_run():
    # Застой, потом рост, потом снова застой — хвост(1), не всего застоев(3)
    assert count_consecutive_stalled_workouts([False, False, True, False]) == 1


# --- recalculate_target: силовой блок ----------------------------------------

def test_strength_small_overshoot_no_change():
    result = recalculate_target(
        STRENGTH_BLOCK, target=3, working_reps=(3, 3, 3, 3), max_reps=4, volume=16, prev_volume=0,
    )
    assert result == ProgressionResult(new_target=4, equipment_changed=False)


def test_strength_threshold_hit_triggers_change():
    result = recalculate_target(
        STRENGTH_BLOCK, target=5, working_reps=(7, 7, 7, 7), max_reps=8, volume=36, prev_volume=0,
    )
    assert result == ProgressionResult(new_target=STRENGTH_BLOCK.base_target, equipment_changed=True)


# --- suggest_starting_equipment ----------------------------------------------

@pytest.mark.parametrize(
    "baseline_reps, expected",
    [
        (0, (EquipmentType.BAND, EquipmentType.BAND)),
        (2, (EquipmentType.BAND, EquipmentType.BAND)),
        (3, (EquipmentType.BAND, EquipmentType.BODYWEIGHT)),
        (7, (EquipmentType.BAND, EquipmentType.BODYWEIGHT)),
        (8, (EquipmentType.BAND, EquipmentType.WEIGHT)),
        (10, (EquipmentType.BAND, EquipmentType.WEIGHT)),
        (11, (EquipmentType.BODYWEIGHT, EquipmentType.WEIGHT)),
        (20, (EquipmentType.BODYWEIGHT, EquipmentType.WEIGHT)),
    ],
)
def test_suggest_starting_equipment(baseline_reps, expected):
    assert suggest_starting_equipment(baseline_reps) == expected


# --- initial_volume_target -----------------------------------------------------

@pytest.mark.parametrize(
    "baseline_reps, expected",
    [
        (0, VOLUME_BLOCK.base_target),
        (5, VOLUME_BLOCK.base_target),
        (10, VOLUME_BLOCK.base_target),
        (11, 9),
        (20, 15),
        (15, 12),
    ],
)
def test_initial_volume_target(baseline_reps, expected):
    assert initial_volume_target(baseline_reps) == expected


# --- check_transition_outcome / is_retry_allowed -----------------------------

def test_transition_not_applicable_when_not_first_workout():
    result = check_transition_outcome(VOLUME_BLOCK, max_reps=3, is_first_workout_on_new_gear=False)
    assert result == TransitionOutcome.NOT_APPLICABLE


def test_transition_viable_volume():
    result = check_transition_outcome(VOLUME_BLOCK, max_reps=12, is_first_workout_on_new_gear=True)
    assert result == TransitionOutcome.VIABLE


def test_transition_failed_volume_below_min_viable():
    result = check_transition_outcome(VOLUME_BLOCK, max_reps=8, is_first_workout_on_new_gear=True)
    assert result == TransitionOutcome.FAILED


def test_transition_viable_at_exact_min_viable_boundary():
    result = check_transition_outcome(STRENGTH_BLOCK, max_reps=3, is_first_workout_on_new_gear=True)
    assert result == TransitionOutcome.VIABLE


def test_transition_failed_strength_below_min_viable():
    result = check_transition_outcome(STRENGTH_BLOCK, max_reps=2, is_first_workout_on_new_gear=True)
    assert result == TransitionOutcome.FAILED


@pytest.mark.parametrize("count, expected", [(0, False), (3, False), (4, True), (5, True)])
def test_is_retry_allowed(count, expected):
    assert is_retry_allowed(count) is expected


# --- suggest_weight_range ------------------------------------------------------

def test_suggest_weight_range_none_from_zero():
    assert suggest_weight_range(Decimal(0)) is None


def test_suggest_weight_range_computes_10_to_15_percent():
    low, high = suggest_weight_range(Decimal(10))
    assert low == Decimal("11.25")
    assert high == Decimal("12.5")


# --- rollback_target / rollback_signed_load ----------------------------------

def test_rollback_target_subtracts_rollback_reps():
    assert rollback_target(17) == 15


def test_rollback_signed_load_weight_decreases_magnitude():
    result = rollback_signed_load(EquipmentType.WEIGHT, Decimal("13.75"))
    assert result == Decimal("11.25")


def test_rollback_signed_load_band_increases_magnitude():
    result = rollback_signed_load(EquipmentType.BAND, Decimal("13.75"))
    assert result == Decimal("16.25")
    assert result > Decimal("13.75")


@pytest.mark.parametrize("equipment_type", [EquipmentType.BAND, EquipmentType.WEIGHT])
def test_rollback_signed_load_always_moves_toward_easier(equipment_type):
    value = Decimal("20.0")
    before = to_signed_load(equipment_type, value)
    after_value = rollback_signed_load(equipment_type, value)
    after = to_signed_load(equipment_type, after_value)
    assert after < before


# --- grow_volume_weight_kg (иерархия роста, часть 3) -------------------------

def test_grow_volume_weight_from_start_5kg():
    # step=max(0.5, 5*0.05=0.25)=0.5 -> ceil_to_step(5.5, 1.25)=6.25
    assert grow_volume_weight_kg(Decimal(5)) == Decimal("6.25")


def test_grow_volume_weight_percentage_dominates_at_higher_weight():
    # На 20кг: step=max(0.5, 20*0.05=1.0)=1.0 -> ceil_to_step(21.0, 1.25)=21.25
    assert grow_volume_weight_kg(Decimal(20)) == Decimal("21.25")


def test_grow_volume_weight_always_increases():
    for start in (Decimal(5), Decimal("6.25"), Decimal(20), Decimal(50)):
        assert grow_volume_weight_kg(start) > start


# --- recalculate_volume_block: рост ниже потолка (часть 1, тот же процентный шаг) --

def test_volume_block_normal_growth_below_ceiling():
    result = recalculate_volume_block(
        target=17, work_sets=3, working_reps=(19, 19, 19), max_reps=22, volume=79, prev_volume=0,
        equipment_type=EquipmentType.BAND,
    )
    assert result == VolumeBlockResult(new_target=20, new_work_sets=3, equipment_changed=False)


def test_volume_block_band_equipment_change_unaffected_by_new_system():
    # BAND -> BODYWEIGHT (обычный порог смены снаряда) не тронут ревизией —
    # work_sets/вес тут ни при чём.
    result = recalculate_volume_block(
        target=17, work_sets=5, working_reps=(20, 20, 20), max_reps=21, volume=81, prev_volume=0,
        equipment_type=EquipmentType.BAND,
    )
    assert result == VolumeBlockResult(new_target=VOLUME_BLOCK.base_target, new_work_sets=5, equipment_changed=True)


def test_volume_block_bodyweight_suppresses_old_equipment_threshold():
    # Тот же ввод, что выше, но уже НА bodyweight — старый порог смены
    # снаряда (20) подавлен новой системой: цель растёт по формуле, а не
    # сбрасывается на base_target через смену снаряда.
    result = recalculate_volume_block(
        target=17, work_sets=5, working_reps=(20, 20, 20), max_reps=21, volume=81, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT,
    )
    assert result.equipment_changed is False
    assert result.new_target == 21  # step=max(1,ceil(17*0.05)=1)=1 -> round(20)+1=21
    assert result.new_work_sets == 5


# --- recalculate_volume_block: потолок 30 (часть 2, п.3) ---------------------

def test_volume_block_ceiling_moderate_overshoot_rolls_back_to_20_plus_one_set():
    # target=28, work_sets=6, working=28x6, max=32 -> step=ceil(28*0.05)=2,
    # computed=30 (>=30, <50) -> откат до 20, +1 подход (6->7).
    result = recalculate_volume_block(
        target=28, work_sets=6, working_reps=(28,) * 6, max_reps=32, volume=28 * 6 + 32, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT,
    )
    assert result == VolumeBlockResult(
        new_target=VOLUME_MODERATE_ROLLBACK_TARGET, new_work_sets=7, equipment_changed=False,
    )


def test_volume_block_ceiling_big_overshoot_rolls_back_to_30_plus_computed_sets():
    # target=48, work_sets=7, working=48x7, max=55 -> step=ceil(48*0.05)=3,
    # computed=51 (>=50) -> откат до 30, +ceil(51/30)=2 подхода (7->8, капается).
    result = recalculate_volume_block(
        target=48, work_sets=7, working_reps=(48,) * 7, max_reps=55, volume=48 * 7 + 55, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT,
    )
    assert result == VolumeBlockResult(new_target=VOLUME_TARGET_CEILING, new_work_sets=8, equipment_changed=False)
    assert VOLUME_BIG_OVERSHOOT_THRESHOLD == 50


def test_volume_block_ceiling_sets_addition_capped_at_eight():
    # target=150, work_sets=3, max=160 -> step=ceil(150*0.05)=8, computed=158,
    # sets_to_add=ceil(158/30)=6 -> 3+6=9, но капается до 8.
    result = recalculate_volume_block(
        target=150, work_sets=3, working_reps=(150,) * 3, max_reps=160, volume=150 * 3 + 160, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT,
    )
    assert result.new_target == VOLUME_TARGET_CEILING
    assert result.new_work_sets == VOLUME_WORK_SETS_CEILING


def test_volume_block_ceiling_immediate_weight_transition_when_sets_already_maxed():
    # work_sets уже 8 (потолок подходов достигнут раньше) — переход на
    # отягощение СРАЗУ в этой же тренировке, не откат/добавление подходов.
    result = recalculate_volume_block(
        target=29, work_sets=8, working_reps=(29,) * 8, max_reps=33, volume=29 * 8 + 33, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT,
    )
    assert result == VolumeBlockResult(
        new_target=VOLUME_TARGET_CEILING, new_work_sets=VOLUME_WORK_SETS_CEILING, equipment_changed=False,
    )


# --- recalculate_volume_block: уже на отягощении (часть 3) ------------------

def test_volume_block_already_on_weight_freezes_target_and_sets():
    result = recalculate_volume_block(
        target=30, work_sets=8, working_reps=(30,) * 8, max_reps=35, volume=30 * 8 + 35, prev_volume=0,
        equipment_type=EquipmentType.WEIGHT,
    )
    assert result == VolumeBlockResult(
        new_target=VOLUME_TARGET_CEILING, new_work_sets=VOLUME_WORK_SETS_CEILING, equipment_changed=False,
    )


def test_volume_block_on_weight_ignores_poor_performance():
    # На отягощении цель/подходы заморожены независимо от результата —
    # даже слабая тренировка (max_reps < target, объём упал) не откатывает.
    result = recalculate_volume_block(
        target=30, work_sets=8, working_reps=(20,) * 8, max_reps=22, volume=20 * 8 + 22, prev_volume=500,
        equipment_type=EquipmentType.WEIGHT,
    )
    assert result.new_target == VOLUME_TARGET_CEILING
    assert result.new_work_sets == VOLUME_WORK_SETS_CEILING


# --- recalculate_volume_block: застой (часть 2, п.2) -------------------------

def test_volume_block_stall_adds_set_after_four_consecutive_non_growing_workouts():
    # delta=0 (флэт) -> цель не выросла; 4-й подряд застой (consecutive=3+1=4) -> +1 подход
    result = recalculate_volume_block(
        target=20, work_sets=5, working_reps=(20, 20, 20), max_reps=20, volume=80, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT, consecutive_stall_before=3,
    )
    assert result.new_target == 20
    assert result.new_work_sets == 6


def test_volume_block_stall_below_threshold_does_not_add_set():
    result = recalculate_volume_block(
        target=20, work_sets=5, working_reps=(20, 20, 20), max_reps=20, volume=80, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT, consecutive_stall_before=2,
    )
    assert result.new_target == 20
    assert result.new_work_sets == 5


def test_volume_block_stall_does_not_add_set_once_sets_already_at_ceiling():
    # Потолок 8 подходов (часть 2, п.4) — застой больше не добавляет подходов.
    result = recalculate_volume_block(
        target=20, work_sets=8, working_reps=(20,) * 8, max_reps=20, volume=180, prev_volume=0,
        equipment_type=EquipmentType.BODYWEIGHT, consecutive_stall_before=10,
    )
    assert result.new_work_sets == 8


def test_volume_block_stall_threshold_constant_is_four():
    assert VOLUME_STALL_THRESHOLD == 4


# --- recalculate_cascade -------------------------------------------------------

def _block_assignment(working_reps, max_reps, target_before, equipment_type=EquipmentType.BAND, is_deload=False):
    return BlockAssignment(
        log=BlockLog(working_reps=working_reps, max_reps=max_reps),
        target_before=target_before,
        target_after=0,
        equipment_changed=False,
        equipment_type=equipment_type,
        is_deload=is_deload,
    )


def test_recalculate_cascade_chains_targets():
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((17, 17, 17), 19, target_before=0),
        block_b=_block_assignment((5, 5, 5, 5), 6, target_before=0),
    )

    updated = recalculate_cascade(
        starting_target_a=17, starting_target_b=5,
        starting_volume_a=68, starting_volume_b=21,
        subsequent_workouts=[record],
    )

    assert len(updated) == 1
    block_a = updated[0].block_a
    assert block_a.target_before == 17
    assert block_a.target_after == 18  # step=max(1,ceil(17*0.05)=1)=1 -> round(17)+1=18
    assert block_a.equipment_type == EquipmentType.BAND
    assert block_a.work_sets_before == VOLUME_BLOCK.work_sets
    assert block_a.work_sets_after == VOLUME_BLOCK.work_sets  # обычный рост, подходы не двигаются


def test_recalculate_cascade_empty_list_returns_empty():
    assert recalculate_cascade(10, 3, 0, 0, []) == []


def test_recalculate_cascade_propagates_weak_streak_from_starting_value():
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((10, 10, 8), 9, target_before=0),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )

    updated = recalculate_cascade(
        starting_target_a=10, starting_target_b=3,
        starting_volume_a=40, starting_volume_b=12,
        subsequent_workouts=[record],
        starting_weak_streak_a=2, starting_weak_streak_b=0,
    )

    assert updated[0].block_a.target_after == 9


def test_recalculate_cascade_weak_streak_defaults_to_zero_when_not_passed():
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((10, 10, 8), 9, target_before=0),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )

    updated = recalculate_cascade(
        starting_target_a=10, starting_target_b=3,
        starting_volume_a=40, starting_volume_b=12,
        subsequent_workouts=[record],
    )

    assert updated[0].block_a.target_after == 10


def test_recalculate_cascade_grows_work_sets_through_ceiling_hierarchy():
    # target=28, work_sets=6 -> тот же пример, что и в recalculate_volume_block
    # напрямую: откат до 20, +1 подход (7).
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((28,) * 6, 32, target_before=0, equipment_type=EquipmentType.BODYWEIGHT),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )

    updated = recalculate_cascade(
        starting_target_a=28, starting_target_b=3,
        starting_volume_a=28 * 6 + 30, starting_volume_b=12,
        subsequent_workouts=[record],
        starting_work_sets_a=6,
    )

    assert updated[0].block_a.target_after == VOLUME_MODERATE_ROLLBACK_TARGET
    assert updated[0].block_a.work_sets_after == 7


def test_recalculate_cascade_skips_deload_workout_entirely():
    # Разгрузка (часть 4) — не двигает и не откатывает прогрессию, проходит
    # через каскад без изменений: target/work_sets до и после совпадают.
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((50,), 0, target_before=0, is_deload=True),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )

    updated = recalculate_cascade(
        starting_target_a=20, starting_target_b=3,
        starting_volume_a=100, starting_volume_b=12,
        subsequent_workouts=[record],
        starting_work_sets_a=5,
    )

    block_a = updated[0].block_a
    assert block_a.target_before == 20
    assert block_a.target_after == 20
    assert block_a.work_sets_before == 5
    assert block_a.work_sets_after == 5
    assert block_a.is_deload is True


def test_recalculate_cascade_resumes_normal_progression_after_deload():
    # Следующая (недеградационная) запись после разгрузки считается от
    # состояния ДО разгрузки, как будто её не было.
    deload = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((50,), 0, target_before=0, is_deload=True),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )
    normal = WorkoutRecord(
        performed_at=datetime(2026, 1, 6, tzinfo=UTC),
        block_a=_block_assignment((17, 17, 17), 19, target_before=0),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )

    updated = recalculate_cascade(
        starting_target_a=17, starting_target_b=3,
        starting_volume_a=68, starting_volume_b=12,
        subsequent_workouts=[deload, normal],
        starting_work_sets_a=3,
    )

    assert updated[1].block_a.target_before == 17
    assert updated[1].block_a.target_after == 18  # тот же расчёт, что в test_recalculate_cascade_chains_targets
