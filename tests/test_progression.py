from datetime import UTC, datetime

import pytest

from app.domain.constants import BLOCK_A, BLOCK_B
from app.domain.progression import (
    ProgressionResult,
    next_weight_kg,
    recalculate_cascade,
    recalculate_target,
    rollback_target,
    rollback_weight_kg,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord

# --- Блок A: recalculate_target -------------------------------------------

def test_block_a_small_overshoot_steps_up_by_delta():
    # 15 15 15 16, target=15 → 16
    result = recalculate_target(BLOCK_A, target=15, max_reps=16, volume=15 + 15 + 15 + 16, prev_volume=0)
    assert result == ProgressionResult(new_target=16, equipment_changed=False)


def test_block_a_large_overshoot_capped_by_max_step():
    # 15 15 15 20, target=15 → 18 (delta=5, ceil(2.5)=3, cap 3)
    result = recalculate_target(BLOCK_A, target=15, max_reps=20, volume=15 + 15 + 15 + 20, prev_volume=0)
    assert result == ProgressionResult(new_target=18, equipment_changed=False)


def test_block_a_exact_target_hit_stays_flat():
    # 15 15 15 15, target=15 → 15
    result = recalculate_target(BLOCK_A, target=15, max_reps=15, volume=15 * 4, prev_volume=0)
    assert result == ProgressionResult(new_target=15, equipment_changed=False)


def test_block_a_missed_target_but_volume_grew_stays_flat():
    # 15 15 13 14, volume вырос относительно прошлой → 15
    volume = 15 + 15 + 13 + 14
    result = recalculate_target(BLOCK_A, target=15, max_reps=14, volume=volume, prev_volume=volume - 1)
    assert result == ProgressionResult(new_target=15, equipment_changed=False)


def test_block_a_missed_target_and_volume_did_not_grow_steps_down():
    # 15 15 13 14, volume не вырос → 14
    volume = 15 + 15 + 13 + 14
    result = recalculate_target(BLOCK_A, target=15, max_reps=14, volume=volume, prev_volume=volume)
    assert result == ProgressionResult(new_target=14, equipment_changed=False)


def test_block_a_missed_target_and_volume_equal_counts_as_not_grown():
    volume = 40
    result = recalculate_target(BLOCK_A, target=15, max_reps=14, volume=volume, prev_volume=volume)
    assert result.new_target == 14


def test_block_a_reaching_change_at_switches_band_and_resets_target():
    # target=18, delta=3 → step=min(3, ceil(1.5))=2 → new_target=20 >= change_at(20)
    # Примечание: строка спеки "15 15 15 19 при target=17 (→20)" не сходится с
    # формулой (по формуле target=17, max=19 даёт new_target=18, а не 20) —
    # здесь используются числа, которые по формуле реально достигают 20,
    # чтобы проверить именно правило смены снаряда.
    result = recalculate_target(BLOCK_A, target=18, max_reps=21, volume=18 * 3 + 21, prev_volume=0)
    assert result == ProgressionResult(new_target=15, equipment_changed=True)


# --- Блок B: recalculate_target -------------------------------------------

def test_block_b_small_overshoot_steps_up_by_delta():
    # 3 3 3 3 4, target=3 → 4
    result = recalculate_target(BLOCK_B, target=3, max_reps=4, volume=3 * 4 + 4, prev_volume=0)
    assert result == ProgressionResult(new_target=4, equipment_changed=False)


def test_block_b_large_overshoot_capped_by_max_step():
    # 3 3 3 3 8, delta=5, ceil(2.5)=3, cap 2 → 5
    result = recalculate_target(BLOCK_B, target=3, max_reps=8, volume=3 * 4 + 8, prev_volume=0)
    assert result == ProgressionResult(new_target=5, equipment_changed=False)


def test_block_b_reaching_change_at_adds_weight_and_resets_target():
    # target=6, delta=3 → step=min(2, ceil(1.5))=2 → new_target=8 >= change_at(8)
    result = recalculate_target(BLOCK_B, target=6, max_reps=9, volume=6 * 4 + 9, prev_volume=0)
    assert result == ProgressionResult(new_target=3, equipment_changed=True)


# --- next_weight_kg (округление ВВЕРХ) --------------------------------------

@pytest.mark.parametrize(
    "current, expected",
    [
        (10.0, 11.25),   # 10 * 1.125 = 11.25, уже кратно шагу — без изменений
        (12.0, 13.75),   # 12 * 1.125 = 13.5 → ceil до шага 1.25 = 13.75
        (11.2, 13.75),   # 11.2 * 1.125 = 12.6 → чуть выше 12.5, но ceil всё равно даёт 13.75
        (0.0, 0.0),
    ],
)
def test_next_weight_kg(current, expected):
    assert next_weight_kg(current) == expected


def test_next_weight_kg_exact_halfway_between_steps_rounds_up():
    # 35/3 * 1.125 = 13.125 — ровно посередине между шагами 12.5 и 13.75
    assert next_weight_kg(35 / 3) == 13.75


def test_rollback_target_subtracts_rollback_reps():
    assert rollback_target(17) == 15


# --- rollback_weight_kg (округление ВНИЗ, наоборот) -------------------------

@pytest.mark.parametrize(
    "current, expected",
    [
        (13.75, 11.25),  # 13.75 * 0.9 = 12.375 → floor до шага 1.25 = 11.25 (не 12.5, как при "к ближайшему")
        (10.0, 8.75),     # 10 * 0.9 = 9.0 → уже кратно шагу — без изменений
        (13.6, 11.25),    # 13.6 * 0.9 = 12.24 → чуть ниже 12.5, но floor всё равно даёт 11.25
    ],
)
def test_rollback_weight_kg(current, expected):
    assert rollback_weight_kg(current) == expected


def test_rollback_weight_kg_exact_halfway_between_steps_rounds_down():
    # 175/12 * 0.9 = 13.125 — ровно посередине между шагами 12.5 и 13.75
    assert rollback_weight_kg(175 / 12) == 12.5


# --- recalculate_cascade ----------------------------------------------------

def _block_assignment(working_reps, max_reps, target_before, target_after=0, equipment_changed=False):
    return BlockAssignment(
        log=BlockLog(working_reps=working_reps, max_reps=max_reps),
        target_before=target_before,
        target_after=target_after,
        equipment_changed=equipment_changed,
    )


def test_recalculate_cascade_chains_targets_and_prev_volume():
    record_1 = WorkoutRecord(
        performed_at=datetime(2026, 1, 1, tzinfo=UTC),
        block_a=_block_assignment((16, 16, 16), 17, target_before=0),
        block_b=_block_assignment((4, 4, 4, 4), 5, target_before=0),
    )
    record_2 = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((17, 17, 17), 16, target_before=0),
        block_b=_block_assignment((5, 5, 5, 5), 4, target_before=0),
    )

    updated = recalculate_cascade(
        starting_target_a=16,
        starting_target_b=4,
        starting_volume_a=63,
        starting_volume_b=15,
        subsequent_workouts=[record_1, record_2],
    )

    assert len(updated) == 2

    first_a, first_b = updated[0].block_a, updated[0].block_b
    assert (first_a.target_before, first_a.target_after, first_a.equipment_changed) == (16, 17, False)
    assert (first_b.target_before, first_b.target_after, first_b.equipment_changed) == (4, 5, False)

    # record_2: delta<0 для обоих блоков, но volume вырос относительно record_1 → target не падает
    second_a, second_b = updated[1].block_a, updated[1].block_b
    assert (second_a.target_before, second_a.target_after, second_a.equipment_changed) == (17, 17, False)
    assert (second_b.target_before, second_b.target_after, second_b.equipment_changed) == (5, 5, False)

    # реальные reps не тронуты
    assert updated[0].block_a.log.working_reps == (16, 16, 16)
    assert updated[1].block_b.log.max_reps == 4


def test_recalculate_cascade_empty_list_returns_empty():
    assert recalculate_cascade(15, 3, 0, 0, []) == []
