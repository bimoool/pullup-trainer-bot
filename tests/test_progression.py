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
    rollback_target,
    rollback_weight_kg,
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

@pytest.mark.parametrize(
    "baseline_reps, expected",
    [
        (0, (EquipmentType.BAND, EquipmentType.BAND)),
        (9, (EquipmentType.BAND, EquipmentType.BAND)),
        (10, (EquipmentType.BODYWEIGHT, EquipmentType.BODYWEIGHT)),
        (25, (EquipmentType.BODYWEIGHT, EquipmentType.BODYWEIGHT)),
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


# --- rollback_target / rollback_weight_kg (без изменений) -------------------

def test_rollback_target_subtracts_rollback_reps():
    assert rollback_target(17) == 15


def test_rollback_weight_kg_rounds_down():
    assert rollback_weight_kg(13.75) == 11.25  # 13.75*0.9=12.375 -> floor к шагу 1.25 = 11.25


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
