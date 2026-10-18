"""PlanSpec (UX-EDITOR contract §2, §4): числа посчитаны вручную по контракту, не выведены из кода."""

import pytest

from app.domain.plan_occurrence import CustomPlanRepeat, custom_week_occurrences
from app.domain.plan_spec import (
    PlanSpec,
    PlanSpecError,
    add_workout,
    delete_week,
    derive_spec_from_legacy,
    insert_week,
    remove_workout,
    with_phase,
    with_quantities,
)

A, B, C = 101, 102, 103


def _spec_a() -> PlanSpec:
    # (a): A 2/2/0/1, B 1/1/1/1
    return PlanSpec((A, B), ((2, 2, 0, 1), (1, 1, 1, 1)), ("base",) * 4)


def test_totals_per_week_example_a():
    spec = _spec_a()
    assert spec.totals() == [3, 3, 1, 2]
    assert sum(spec.totals()) == 9
    assert spec.expected_counts(0) == {A: 2, B: 1}
    assert spec.expected_counts(2) == {B: 1}
    assert spec.expected_counts(4) == {}  # вне плана


def test_legacy_conversion_two_workouts():
    spec = derive_spec_from_legacy([A, B], [2, 2, 0, 2], CustomPlanRepeat.ONCE)
    assert spec.quantities == ((1, 1, 0, 1), (1, 1, 0, 1))
    assert spec.totals() == [2, 2, 0, 2]
    assert spec.phases == ("base",) * 4


def test_legacy_conversion_odd_rotation():
    spec = derive_spec_from_legacy([A, B, C], [2, 2, 2], CustomPlanRepeat.ONCE)
    assert spec.quantities == ((1, 1, 0), (1, 0, 1), (0, 1, 1))


def test_legacy_cycle_unroll():
    spec = derive_spec_from_legacy([A, B], [3], CustomPlanRepeat.CYCLE)
    assert spec.quantities == ((2, 1), (1, 2))
    assert spec.repeat == CustomPlanRepeat.CYCLE
    assert spec.totals() == [3, 3]


def test_legacy_cycle_stable_keeps_length():
    spec = derive_spec_from_legacy([A, B], [2, 2], CustomPlanRepeat.CYCLE)
    assert spec.week_count == 2 and spec.quantities == ((1, 1), (1, 1))


@pytest.mark.parametrize(
    ("workouts", "weeks", "repeat"),
    [([A, B], [2, 2, 0, 2], "once"), ([A, B, C], [2, 2, 2], "once"), ([A, B], [3], "cycle"),
     ([A, B, C], [4, 1, 0, 3], "cycle"), ([A, A, B], [3, 3], "once")],
)
def test_derived_spec_matches_legacy_materialisation(workouts, weeks, repeat):
    """Мультимножество занятий недели совпадает с прежним custom_week_occurrences (кроме порядка индексов)."""
    repeat_enum = CustomPlanRepeat(repeat)
    spec = derive_spec_from_legacy(workouts, weeks, repeat_enum)
    for offset in range(12):
        legacy: dict[int, int] = {}
        for occ in custom_week_occurrences(
            workout_ids=workouts, weeks=weeks, repeat=repeat_enum, week_offset=offset, preferred_weekdays=None,
        ):
            legacy[occ.workout_definition_id] = legacy.get(occ.workout_definition_id, 0) + 1
        assert spec.expected_counts(offset) == legacy, (offset, spec)


def test_insert_week_after_week_two():
    spec = insert_week(_spec_a(), 2)  # после недели 2 → индекс 2 (0-based)
    assert spec.quantities == ((2, 2, 0, 0, 1), (1, 1, 0, 1, 1))
    assert spec.totals() == [3, 3, 0, 1, 2]
    assert spec.phases == ("base",) * 5


def test_delete_week_three():
    spec = delete_week(_spec_a(), 2)
    assert spec.quantities == ((2, 2, 1), (1, 1, 1))
    assert spec.totals() == [3, 3, 2]


def test_with_quantities_and_limits():
    spec = with_quantities(_spec_a(), 1, {A: 1})
    assert spec.quantities[0] == (2, 1, 0, 1)
    with pytest.raises(PlanSpecError) as err:
        with_quantities(_spec_a(), 0, {A: 15})
    assert err.value.code == "invalid_quantity"
    with pytest.raises(PlanSpecError):
        with_quantities(_spec_a(), 0, {A: 14, B: 1})  # неделя 15 > 14


def test_phase_workout_ops():
    spec = with_phase(_spec_a(), 2, "rest")
    assert spec.phases == ("base", "base", "rest", "base")
    added = add_workout(spec, C)
    assert added.quantities[2] == (0, 0, 0, 0)
    assert remove_workout(added, A).workouts == (B, C)
    with pytest.raises(PlanSpecError) as err:
        remove_workout(PlanSpec((A,), ((1,),), ("base",)), A)
    assert err.value.code == "last_workout"
