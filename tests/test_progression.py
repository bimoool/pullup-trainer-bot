from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType, to_signed_load
from app.domain.progression import (
    ProgressionResult,
    TransitionOutcome,
    check_transition_outcome,
    count_consecutive_weak_trainings,
    initial_volume_target,
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
    # avg_working=19, growth=22-19=3, step=min(3,ceil(1.5))=2 -> round(19)+2=21
    assert result.new_target == 21


def test_volume_missed_target_but_volume_grew_stays_flat():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=37, prev_volume=30, equipment_type=EquipmentType.BAND,
    )
    assert result.new_target == 10


# --- recalculate_target: отсрочка отката, 3 подряд "слабых" (Часть 10, пакет #2, п.13) ---

def test_volume_equal_volume_is_not_weak_stays_flat_regardless_of_streak():
    # Часть 10, пакет #2: раньше volume == prev_volume откатывало сразу
    # (была else-ветка "volume > prev_volume, иначе -1"), теперь равный
    # объём — НЕ слабая тренировка вовсе, откат тут в принципе не
    # применим, streak не при чём.
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=37, prev_volume=37, equipment_type=EquipmentType.BAND,
        consecutive_weak_before=5,
    )
    assert result.new_target == 10


def test_volume_first_weak_training_does_not_rollback():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=30, prev_volume=37, equipment_type=EquipmentType.BAND,
        consecutive_weak_before=0,
    )
    assert result.new_target == 10


def test_volume_second_consecutive_weak_training_still_no_rollback():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=30, prev_volume=37, equipment_type=EquipmentType.BAND,
        consecutive_weak_before=1,
    )
    assert result.new_target == 10


def test_volume_third_consecutive_weak_training_rolls_back():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=30, prev_volume=37, equipment_type=EquipmentType.BAND,
        consecutive_weak_before=2,
    )
    assert result.new_target == 9


def test_volume_fourth_and_beyond_consecutive_weak_keeps_rolling_back():
    # consecutive_weak_before уже >= порога — правило "не после первой", а
    # не "ровно на третьей": продолжает откатывать каждую следующую слабую.
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 8), max_reps=9,
        volume=30, prev_volume=37, equipment_type=EquipmentType.BAND,
        consecutive_weak_before=3,
    )
    assert result.new_target == 9


# --- recalculate_target: формула роста (Часть 10, пакет #2, п.12) -----------
# ПОЛНАЯ замена прежнего правила "объём везде, без отката" — не дополняет
# его, замещает целиком. Все 6 примеров из промпта.

def test_growth_formula_example_18_18_18_21_at_target_10():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(18, 18, 18), max_reps=21,
        volume=75, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # avg=18, growth=21-18=3, step=min(3,ceil(1.5))=2 -> round(18)+2=20
    assert result.new_target == 20


def test_growth_formula_example_18_18_18_23_hypothetical_at_target_10():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(18, 18, 18), max_reps=23,
        volume=77, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # avg=18, growth=23-18=5, step=min(3,ceil(2.5))=3 (кап) -> round(18)+3=21
    assert result.new_target == 21


def test_growth_formula_example_15_15_15_16_at_target_15_unchanged_from_first_version():
    result = recalculate_target(
        VOLUME_BLOCK, target=15, working_reps=(15, 15, 15), max_reps=16,
        volume=61, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # avg=15, growth=1, step=min(3,ceil(0.5))=1 -> round(15)+1=16
    assert result.new_target == 16


def test_growth_formula_example_15_15_15_20_at_target_15_unchanged_from_first_version():
    result = recalculate_target(
        VOLUME_BLOCK, target=15, working_reps=(15, 15, 15), max_reps=20,
        volume=65, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # avg=15, growth=5, step=min(3,ceil(2.5))=3 (кап) -> round(15)+3=18
    assert result.new_target == 18


def test_growth_formula_example_10_10_10_16_at_target_10():
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(10, 10, 10), max_reps=16,
        volume=46, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    # avg=10, growth=6, step=min(3,ceil(3))=3 (кап) -> round(10)+3=13
    assert result.new_target == 13


def test_growth_formula_example_20_20_20_21_yields_to_equipment_change_threshold():
    # Пример из промпта ("20 20 20 21" при target=10 -> формула сама по
    # себе даёт 21), НО working_reps=20 на каждом рабочем подходе — это
    # ровно VOLUME_BLOCK.equipment_change_threshold, и смена снаряда
    # приоритетнее результата формулы (тот же приоритет, что уже был
    # установлен и подтверждён для прошлой версии формулы — жать 20+ на
    # всех рабочих подходах достаточно, чтобы предложить снаряд
    # потяжелее, а не просто поднять цифру цели на том же снаряде).
    # Изолированно от этого взаимодействия формула проверена в
    # test_growth_formula_example_18_18_18_21_at_target_10 (та же
    # арифметика, working_reps=18 — ниже порога смены снаряда).
    result = recalculate_target(
        VOLUME_BLOCK, target=10, working_reps=(20, 20, 20), max_reps=21,
        volume=81, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.equipment_changed is True
    assert result.new_target == VOLUME_BLOCK.base_target


def test_growth_formula_step_never_negative_when_working_reps_exceed_max():
    # Вырожденный случай: парсер ввода не проверяет, что working_reps <=
    # max_reps ("19 19 19 6" технически валидный ввод), avg_working может
    # оказаться намного выше max_reps, хотя max_reps всё ещё > target
    # (ветка успеха). Без max(0, ...) это дало бы отрицательный step и
    # абсурдный new_target ниже avg_working — здесь step floor'ится в 0,
    # new_target не проваливается ниже round(avg_working). working_reps=19,
    # не 20 — иначе сработал бы equipment_change_threshold (см. отдельный
    # тест на это взаимодействие) и замаскировал бы то, что здесь проверяется.
    result = recalculate_target(
        VOLUME_BLOCK, target=5, working_reps=(19, 19, 19), max_reps=6,
        volume=63, prev_volume=0, equipment_type=EquipmentType.BAND,
    )
    assert result.new_target == 19  # round(avg_working=19) + max(0, ...) = 19
    assert result.equipment_changed is False


# --- count_consecutive_weak_trainings (Часть 10, пакет #2, п.13) ------------

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
    # слабая, потом рост, потом снова слабая — считает только ХВОСТ (1),
    # а не общее число слабых записей во всей истории (было бы 2)
    assert count_consecutive_weak_trainings([10, 8, 9, 7]) == 1


# --- recalculate_target: потолок объёмного блока на собственном весе --------

def test_volume_ceiling_not_yet_reached_grows_normally():
    result = recalculate_target(
        VOLUME_BLOCK, target=20, working_reps=(21, 21, 21), max_reps=22,
        volume=85, prev_volume=0, equipment_type=EquipmentType.BODYWEIGHT,
    )
    # avg=21, growth=1, step=min(3,ceil(0.5))=1 -> round(21)+1=22; порог 20
    # взят, но на bodyweight переходить некуда — не считается сменой снаряда
    assert result == ProgressionResult(new_target=22, equipment_changed=False, ceiling_reached=False)


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


# --- initial_volume_target: "замер минус 25%" (Часть 10, пакет #2, п.14) ----

@pytest.mark.parametrize(
    "baseline_reps, expected",
    [
        (0, VOLUME_BLOCK.base_target),  # старт с резины -> флэт base_target, без изменений
        (5, VOLUME_BLOCK.base_target),
        (10, VOLUME_BLOCK.base_target),  # == base_target -> НЕ строго больше -> резина, флэт
        (11, 9),  # ceil(11*0.75)=ceil(8.25)=9 — граница чуть выше 10, формула уже применяется
        (20, 15),  # пример из промпта: ceil(20*0.75)=15
        (15, 12),  # ceil(11.25)=12
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


def test_recalculate_cascade_propagates_weak_streak_from_starting_value():
    # Часть 10, пакет #2, п.13 — starting_weak_streak_a приходит от
    # вызывающего кода (edit_workout: стрик ДО отредактированной записи +
    # сама она, если тоже оказалась слабой) и переигрывается ВНУТРИ
    # каскада бегущим счётчиком, а не отдельной хранимой сущностью.
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((10, 10, 8), 9, target_before=0),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )

    # starting_weak_streak_a=2, запись сама слабая (volume 37 < prev 40) ->
    # итоговый стрик 3 -> откат на -1 (10 -> 9).
    updated = recalculate_cascade(
        starting_target_a=10, starting_target_b=3,
        starting_volume_a=40, starting_volume_b=12,
        subsequent_workouts=[record],
        starting_weak_streak_a=2, starting_weak_streak_b=0,
    )

    assert updated[0].block_a.target_after == 9


def test_recalculate_cascade_weak_streak_defaults_to_zero_when_not_passed():
    # Обратная совместимость: без starting_weak_streak_* первая слабая
    # тренировка в цепочке не откатывает цель сразу (не после первой).
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
