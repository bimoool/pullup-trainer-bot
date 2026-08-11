from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType, to_signed_load
from app.domain.progression import (
    ProgressionResult,
    TransitionOutcome,
    check_transition_outcome,
    is_retry_allowed,
    recalculate_cascade,
    recalculate_target,
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

def test_volume_small_overshoot_no_equipment_change():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 10), max_reps=11,
        volume=41, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result == ProgressionResult(new_target=11, equipment_changed=False)


def test_volume_threshold_hit_in_all_working_sets_triggers_change():
    # "20 20 20 21" — порог взят по факту, а не по расчётной цели
    result = recalculate_target(
        VOLUME_BLOCK, target=17, working_reps=(20, 20, 20), max_reps=21,
        volume=81, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result == ProgressionResult(new_target=VOLUME_BLOCK.base_target, equipment_changed=True)


def test_volume_high_max_but_working_sets_below_threshold_does_not_change():
    # "19 19 19 22" — максимум выше 20, но рабочие подходы не достали порог
    result = recalculate_target(
        VOLUME_BLOCK, target=17, working_reps=(19, 19, 19), max_reps=22,
        volume=79, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.equipment_changed is False
    assert result.new_target == 20  # обычная формула: delta=5, ceil(2.5)=3, cap3 -> 20, но снаряд НЕ меняется


def test_volume_missed_target_but_volume_grew_stays_flat():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=37, prev_volume=30, equipment_type=EquipmentType.BAND,
    )
    assert result.new_target == 10


def test_volume_missed_target_and_volume_did_not_grow_steps_down():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=37, prev_volume=37, equipment_type=EquipmentType.BAND,
    )
    assert result.new_target == 9


# --- recalculate_target: "объём везде, без отката" (Часть 10) ----------------
# Три случая из живого тестирования + граничные (разброс ровно
# NO_CAP_MAX_SPREAD=2, минимум ровно на max_step выше цели).

def test_volume_even_working_sets_far_above_target_ignores_cap():
    # Пример из респека был "20 20 20 21" при цели 10 -> цель 20. Но 20 —
    # это ровно VOLUME_BLOCK.equipment_change_threshold, поэтому такие
    # working_reps одновременно попадают под УЖЕ существующий (и
    # протестированный) переход на новый снаряд, который приоритетнее —
    # см. test_volume_threshold_hit_in_all_working_sets_triggers_change.
    # Здесь та же арифметика "без отката", но working_reps ниже порога
    # смены снаряда, чтобы проверить именно новое правило изолированно.
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(17, 17, 17), max_reps=18,
        volume=69, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.new_target == 17
    assert result.equipment_changed is False


def test_volume_no_cap_rule_yields_to_equipment_change_threshold():
    # Когда working_reps одновременно попадают и под новое правило "без
    # отката", и под порог смены снаряда — смена снаряда приоритетнее:
    # если человек уже жмёт 20+ на всех рабочих подходах, разумнее
    # предложить снаряд потяжелее, а не просто поднять цифру цели на том
    # же снаряде.
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(20, 20, 20), max_reps=21,
        volume=81, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.equipment_changed is True
    assert result.new_target == VOLUME_BLOCK.base_target


def test_volume_uneven_working_sets_falls_back_to_capped_formula():
    # "10 10 10 16" при цели 10 -> 13 (разброс 0, но минимум-цель=0 < max_step=3 -> обычная формула)
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 10), max_reps=16,
        volume=46, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.new_target == 13


def test_volume_small_delta_does_not_need_the_new_rule():
    # "15 15 15 16" при цели 15 -> 16 (маленькая дельта, кап и так не мешал)
    result = recalculate_target(
        VOLUME_BLOCK, target=15, working_reps=(15, 15, 15), max_reps=16,
        volume=61, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.new_target == 16


def test_volume_no_cap_rule_boundary_spread_exactly_two_still_applies():
    # разброс ровно NO_CAP_MAX_SPREAD (2) -> граница включительно, правило применяется
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(18, 19, 20), max_reps=21,
        volume=78, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # min(18,19,20)=18, 18-10=8>=max_step(3) -> новое правило: round(mean(18,19,20))=19
    assert result.new_target == 19


def test_volume_no_cap_rule_boundary_spread_three_falls_back():
    # разброс 3 (>NO_CAP_MAX_SPREAD) -> правило НЕ применяется, обычная формула
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(17, 19, 20), max_reps=21,
        volume=77, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # delta=21-10=11, step=min(3, ceil(5.5))=3 -> 13
    assert result.new_target == 13


def test_volume_no_cap_rule_boundary_minimum_exactly_max_step_above_target():
    # минимум рабочих подходов ровно на max_step (3) выше цели -> граница включительно
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(13, 13, 14), max_reps=15,
        volume=55, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # spread=1<=2, min(13)-10=3>=3 -> round(mean(13,13,14))=13
    assert result.new_target == 13


def test_volume_no_cap_rule_boundary_minimum_one_below_max_step_falls_back():
    # минимум на max_step-1 выше цели -> НЕ применяется, обычная формула
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(12, 12, 13), max_reps=14,
        volume=51, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # delta=14-10=4, step=min(3, ceil(2))=2 -> 12
    assert result.new_target == 12


# --- recalculate_target: потолок объёмного блока на собственном весе --------

def test_volume_ceiling_not_yet_reached_grows_normally():
    result = recalculate_target(
        VOLUME_BLOCK, target=23, working_reps=(25, 25, 25), max_reps=25,
        volume=100, prev_volume=0, equipment_type=EquipmentType.BODYWEIGHT,
    )
    # delta=2, step=min(3, ceil(1))=1 -> 24; порог 20 взят, но на bodyweight
    # переходить некуда — просто не считается сменой снаряда
    assert result == ProgressionResult(new_target=24, equipment_changed=False, ceiling_reached=False)


def test_volume_ceiling_reached_caps_target_and_flags_it():
    result = recalculate_target(
        VOLUME_BLOCK, target=24, working_reps=(25, 25, 25), max_reps=26,
        volume=101, prev_volume=0, equipment_type=EquipmentType.BODYWEIGHT,
    )
    assert result == ProgressionResult(new_target=25, equipment_changed=False, ceiling_reached=True)


def test_volume_beyond_ceiling_stays_capped():
    result = recalculate_target(
        VOLUME_BLOCK, target=25, working_reps=(25, 25, 25), max_reps=28,
        volume=103, prev_volume=0, equipment_type=EquipmentType.BODYWEIGHT,
    )
    assert result.new_target == 25
    assert result.ceiling_reached is True
    assert result.equipment_changed is False


def test_volume_threshold_on_band_still_changes_equipment_not_capped():
    # потолок применяется только к bodyweight — на резине смена работает как обычно
    result = recalculate_target(
        VOLUME_BLOCK, target=17, working_reps=(20, 20, 20), max_reps=20,
        volume=80, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.equipment_changed is True
    assert result.new_target == VOLUME_BLOCK.base_target


# --- recalculate_target: силовой блок ----------------------------------------

def test_strength_small_overshoot_no_change():
    result = recalculate_target(
        STRENGTH_BLOCK, target=3, working_reps=(3, 3, 3, 3), max_reps=4,
        volume=16, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result == ProgressionResult(new_target=4, equipment_changed=False)


def test_strength_threshold_hit_triggers_change():
    result = recalculate_target(
        STRENGTH_BLOCK, target=5, working_reps=(7, 7, 7, 7), max_reps=8,
        volume=36, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result == ProgressionResult(new_target=STRENGTH_BLOCK.base_target, equipment_changed=True)


def test_strength_has_no_ceiling_on_bodyweight():
    result = recalculate_target(
        STRENGTH_BLOCK, target=5, working_reps=(7, 7, 7, 7), max_reps=8,
        volume=36, prev_volume=0, equipment_type=EquipmentType.BODYWEIGHT,
    )
    # bodyweight_ceiling=None для силового блока -> порог работает как обычно
    assert result.equipment_changed is True


# --- suggest_starting_equipment ----------------------------------------------
# Часть 10: у каждого блока свои пороги — раньше силовой блок ошибочно
# получал те же пороги, что и объёмный (баг: замер 20 -> "свой вес" вместо
# "отягощение" для силы, хотя 20 >= 8).

@pytest.mark.parametrize(
    "baseline_reps, expected",
    [
        (0, (EquipmentType.BAND, EquipmentType.BAND)),  # объём: <=10 -> резина; сила: <3 -> резина
        (2, (EquipmentType.BAND, EquipmentType.BAND)),
        (3, (EquipmentType.BAND, EquipmentType.BODYWEIGHT)),  # сила: 3<=x<8 -> свой вес
        (7, (EquipmentType.BAND, EquipmentType.BODYWEIGHT)),
        (8, (EquipmentType.BAND, EquipmentType.WEIGHT)),  # сила: >=8 -> отягощение
        (10, (EquipmentType.BAND, EquipmentType.WEIGHT)),  # объём: замер == 10 -> НЕ строго больше -> резина
        (11, (EquipmentType.BODYWEIGHT, EquipmentType.WEIGHT)),  # объём: >10 -> свой вес
        (20, (EquipmentType.BODYWEIGHT, EquipmentType.WEIGHT)),  # баг из живого тестирования: было (bodyweight, bodyweight)
    ],
)
def test_suggest_starting_equipment(baseline_reps, expected):
    assert suggest_starting_equipment(baseline_reps) == expected


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
    # отягощение: знаковая величина положительная, легче = МЕНЬШЕ кг.
    # 13.75 - 10% = 12.375 -> floor к шагу 1.25 = 11.25 (та же арифметика,
    # что была у прежней rollback_weight_kg, теперь через знаковую шкалу).
    result = rollback_signed_load(EquipmentType.WEIGHT, Decimal("13.75"))
    assert result == Decimal("11.25")


def test_rollback_signed_load_band_increases_magnitude():
    # резина: знаковая величина отрицательная, легче = БОЛЬШЕ кг
    # сопротивления (толще резина, больше помощи). Наивное умножение
    # |значения| на 0.9 дало бы 12.375 (легче число, но ЖЁСТЧЕ снаряд) —
    # правильный результат идёт в обратную сторону, в сторону увеличения.
    result = rollback_signed_load(EquipmentType.BAND, Decimal("13.75"))
    assert result == Decimal("16.25")
    assert result > Decimal("13.75")


@pytest.mark.parametrize("equipment_type", [EquipmentType.BAND, EquipmentType.WEIGHT])
def test_rollback_signed_load_always_moves_toward_easier(equipment_type):
    # Инвариант, который должен держаться для ЛЮБОГО снаряда на шкале:
    # знаковая нагрузка после отката строго МЕНЬШЕ прежней (легче), а не
    # только модуль числа — иначе для резины откат случайно утяжелит.
    value = Decimal("20.0")
    before = to_signed_load(equipment_type, value)
    after_value = rollback_signed_load(equipment_type, value)
    after = to_signed_load(equipment_type, after_value)
    assert after < before


# --- recalculate_cascade -------------------------------------------------------

def _block_assignment(working_reps, max_reps, target_before, equipment_type=EquipmentType.BAND):
    return BlockAssignment(
        log=BlockLog(working_reps=working_reps, max_reps=max_reps),
        target_before=target_before,
        target_after=0,
        equipment_changed=False,
        equipment_type=equipment_type,
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
    assert block_a.target_after == 18  # delta=2, step=min(3,ceil(1))=1
    assert block_a.equipment_type == EquipmentType.BAND


def test_recalculate_cascade_empty_list_returns_empty():
    assert recalculate_cascade(10, 3, 0, 0, []) == []
