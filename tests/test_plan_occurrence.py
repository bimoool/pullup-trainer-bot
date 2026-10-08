"""Domain: Program + Plan v2 (issue #304, PROGRAM_PLAN_V2 §1, §4–§7) — чистые функции, без БД.

OD-2 (решение владельца 2026-10-08): «2 дня отдыха между MAIN» = ДВА ПОЛНЫХ дня отдыха →
min_days_between_starts = 3: Пн — тренировка, Вт и Ср — отдых, ближайший следующий MAIN — Чт.
"""

from datetime import date, timedelta
from itertools import pairwise

import pytest

from app.domain.plan_occurrence import (
    DEFAULT_MAIN_MIN_DAYS_BETWEEN_STARTS,
    MAIN_SLOT_KEY,
    MAIN_SPACING_GROUP,
    CustomPlanError,
    CustomPlanRepeat,
    OccurrenceInput,
    OccurrenceState,
    SlotRole,
    assign_aggregate_credits,
    available_from,
    custom_week_count,
    custom_week_occurrences,
    derive_occurrence_states,
    derive_slots,
    feasible_remaining,
    is_too_early,
    spacing_days_by_group,
    summarize_week,
    validate_custom_plan,
)

MON = date(2026, 10, 5)  # понедельник
TUE, WED, THU, FRI, SAT, SUN = (MON + timedelta(days=i) for i in range(1, 7))
NEXT_MON = MON + timedelta(days=7)
MAIN = MAIN_SPACING_GROUP
DAYS = {MAIN: 3}


# --- OD-2: два полных дня отдыха -------------------------------------------------------------


def test_default_value_is_two_full_rest_days():
    assert DEFAULT_MAIN_MIN_DAYS_BETWEEN_STARTS == 3


def test_monday_main_next_main_is_thursday():
    available = available_from(MON, 3)
    assert available == THU
    assert is_too_early(TUE, available)
    assert is_too_early(WED, available)  # Пн → Ср НЕ допустим (это был старый MIN_REST_DAYS=2)
    assert not is_too_early(THU, available)
    assert not is_too_early(FRI, available)


def test_no_history_never_too_early():
    assert available_from(None, 3) is None
    assert not is_too_early(MON, None)


def test_spacing_days_from_constraints_and_default():
    assert spacing_days_by_group(None, default_main=3) == {MAIN: 3}
    assert spacing_days_by_group([{"spacing_group": "main", "min_days_between_starts": 4}], default_main=3) == {MAIN: 4}
    # мусор игнорируется, main остаётся
    assert spacing_days_by_group([{"spacing_group": 1}, "x", {"min_days_between_starts": -1}], default_main=3) == {
        MAIN: 3,
    }


# --- K2: желаемая частота ≠ размещение ----------------------------------------------------


def test_k2_example_wednesday_after_monday_two_feasible():
    """PROGRAM_PLAN §4 K2: value 3, today Wed, last main Mon → available Thu → Thu, Sun → 2 feasible."""
    assert feasible_remaining(MON, today=WED, available=THU, min_days=3) == 2


def test_feasible_remaining_fresh_week_and_end_of_week():
    assert feasible_remaining(MON, today=MON, available=None, min_days=3) == 3  # Пн, Чт, Вс
    assert feasible_remaining(MON, today=SAT, available=None, min_days=3) == 1
    assert feasible_remaining(MON, today=SUN, available=NEXT_MON, min_days=3) == 0


def _occ(item_id, week_start=MON, index=1, *, completed=False, group=MAIN, scheduled=None):
    return OccurrenceInput(
        item_id=item_id, week_start=week_start, occurrence_index=index, spacing_group=group,
        completed=completed, scheduled_date=scheduled,
    )


def test_states_current_week_last_main_monday_today_wednesday():
    occurrences = [_occ(1, index=1, completed=True), _occ(2, index=2), _occ(3, index=3)]
    states = derive_occurrence_states(
        occurrences, today=WED, available_from_by_group={MAIN: THU}, min_days_by_group=DAYS,
    )
    assert states[1].state == OccurrenceState.COMPLETED
    assert states[2].state == OccurrenceState.TOO_EARLY
    assert states[2].available_from == THU and states[2].projected_date == THU
    assert states[3].state == OccurrenceState.TOO_EARLY and states[3].projected_date == SUN
    summary = summarize_week(occurrences, states)
    assert (summary.planned, summary.completed, summary.infeasible) == (3, 1, 0)


def test_states_thursday_available():
    occurrences = [_occ(1, completed=True), _occ(2, index=2), _occ(3, index=3)]
    states = derive_occurrence_states(occurrences, today=THU, available_from_by_group={MAIN: THU}, min_days_by_group=DAYS)
    assert states[2].state == OccurrenceState.AVAILABLE
    assert states[3].state == OccurrenceState.AVAILABLE and states[3].projected_date == SUN


def test_three_per_week_infeasible_when_desired_volume_does_not_fit():
    """Fresh week, today Wed, no history: Wed, Sat fit; the 3rd is «не успеть на этой неделе»."""
    occurrences = [_occ(1), _occ(2, index=2), _occ(3, index=3)]
    states = derive_occurrence_states(occurrences, today=WED, available_from_by_group={MAIN: None}, min_days_by_group=DAYS)
    assert [states[i].state for i in (1, 2, 3)] == [
        OccurrenceState.AVAILABLE, OccurrenceState.AVAILABLE, OccurrenceState.INFEASIBLE,
    ]
    assert states[1].projected_date == WED and states[2].projected_date == SAT and states[3].projected_date is None
    summary = summarize_week(occurrences, states)
    assert (summary.planned, summary.infeasible) == (3, 1)  # «0 из 3», одно — «не успеть», не долг


def test_chain_continues_into_future_weeks_without_violating_rest():
    this_week = [_occ(1), _occ(2, index=2), _occ(3, index=3)]  # Пн, Чт, Вс
    next_week = [_occ(4, NEXT_MON), _occ(5, NEXT_MON, 2), _occ(6, NEXT_MON, 3)]
    states = derive_occurrence_states(
        this_week + next_week, today=MON, available_from_by_group={MAIN: None}, min_days_by_group=DAYS,
    )
    projected = [states[i].projected_date for i in range(1, 7)]
    assert projected[:3] == [MON, THU, SUN]
    assert projected[3:5] == [NEXT_MON + timedelta(days=2), NEXT_MON + timedelta(days=5)]  # Ср, Сб
    assert states[6].state == OccurrenceState.INFEASIBLE
    dates = [d for d in projected if d is not None]
    assert all((b - a).days >= 3 for a, b in pairwise(dates))


def test_future_week_occurrence_is_available_not_locked():
    occurrences = [_occ(1, NEXT_MON)]
    states = derive_occurrence_states(occurrences, today=WED, available_from_by_group={MAIN: None}, min_days_by_group=DAYS)
    assert states[1].state == OccurrenceState.AVAILABLE  # §6: будущие недели стартуемы


def test_past_week_open_occurrence_is_missed_not_debt():
    past = MON - timedelta(days=7)
    occurrences = [_occ(1, past, completed=True), _occ(2, past, 2), _occ(3, MON)]
    states = derive_occurrence_states(occurrences, today=MON, available_from_by_group={MAIN: None}, min_days_by_group=DAYS)
    assert states[2].state == OccurrenceState.MISSED
    assert states[3].state == OccurrenceState.AVAILABLE  # перенос долга не порождается (PL5)


def test_occurrences_without_spacing_group_are_available():
    occurrences = [_occ(1, group=None, scheduled=FRI), _occ(2, index=2, group=None)]
    states = derive_occurrence_states(occurrences, today=MON, available_from_by_group={MAIN: THU}, min_days_by_group=DAYS)
    assert states[1].state == OccurrenceState.AVAILABLE and states[1].projected_date == FRI
    assert states[2].state == OccurrenceState.AVAILABLE


def test_completed_future_occurrence_counts_in_its_week():
    occurrences = [_occ(1, NEXT_MON, completed=True), _occ(2, NEXT_MON, 2)]
    states = derive_occurrence_states(occurrences, today=MON, available_from_by_group={MAIN: THU}, min_days_by_group=DAYS)
    assert states[1].state == OccurrenceState.COMPLETED
    assert summarize_week(occurrences, states).completed == 1


def test_legacy_aggregate_counts_its_count_per_week():
    past = MON - timedelta(days=7)
    aggregate = OccurrenceInput(
        item_id=9, week_start=past, occurrence_index=None, spacing_group=None, completed=False,
        legacy_aggregate=True, planned_count=3, done_count=2,
    )
    states = derive_occurrence_states([aggregate], today=MON, available_from_by_group={}, min_days_by_group={})
    assert states[9].state == OccurrenceState.MISSED
    summary = summarize_week([aggregate], states)
    assert (summary.planned, summary.completed) == (3, 2)


def test_one_occurrence_counts_as_one():
    occurrences = [_occ(i, index=i) for i in (1, 2, 3)]
    states = derive_occurrence_states(occurrences, today=MON, available_from_by_group={MAIN: None}, min_days_by_group=DAYS)
    assert summarize_week(occurrences, states).planned == 3  # «0 из 3», без скрытого множителя


# --- Слоты ----------------------------------------------------------------------------------


def _legacy_snapshot():
    return {
        "exercises": [{"role": "block_a", "exercise_id": 11}, {"role": "block_b", "exercise_id": 12}],
        "program_items": [
            {"id": 1, "exercise_id": 11, "complex_id": None, "count_per_week": 3},
            {"id": 2, "exercise_id": 12, "complex_id": None, "count_per_week": 3},
        ],
    }


def test_legacy_step_snapshot_has_one_main_slot_a_plus_b():
    slots = derive_slots(_legacy_snapshot())
    assert len(slots) == 1
    main = slots[0]
    assert (main.key, main.role, main.sessions_per_week, main.spacing_group) == (MAIN_SLOT_KEY, SlotRole.MAIN, 3, MAIN)
    assert [m.exercise_id for m in main.members] == [11, 12]  # одно занятие = блоки A + Б (AD-3)
    assert main.exercise_id == 11 and main.counts_toward_progression


def test_catalogue_frequency_overrides_legacy_count():
    slots = derive_slots(_legacy_snapshot(), program_frequency={"sessions_per_week": 2, "per_slot": {}})
    assert slots[0].sessions_per_week == 2


def test_non_role_program_items_group_by_day_into_optional_slots_outside_main_group():
    """Прежняя семантика плана: элементы одного дня (NULL — пул) исполнялись одной тренировкой."""
    snapshot = {"program_items": [
        {"id": 7, "exercise_id": 70, "complex_id": None, "count_per_week": 2},
        {"id": 8, "exercise_id": 80, "complex_id": None, "count_per_week": 2},
        {"id": 9, "exercise_id": 90, "complex_id": 900, "count_per_week": 1, "day_of_week": 2},
    ]}
    slots = derive_slots(snapshot)
    assert [(s.key, s.role, s.sessions_per_week, s.spacing_group, s.day_of_week) for s in slots] == [
        ("pool", SlotRole.OPTIONAL, 2, None, None), ("day2", SlotRole.OPTIONAL, 1, None, 2),
    ]
    assert [m.exercise_id for m in slots[0].members] == [70, 80]
    assert slots[1].workout_definition_id == 900


def test_frozen_slots_win_and_round_trip():
    frozen = [s.to_dict() for s in derive_slots(_legacy_snapshot())]
    snapshot = {**_legacy_snapshot(), "slots": frozen, "program_items": []}
    assert derive_slots(snapshot) == derive_slots(_legacy_snapshot())


# --- Свой план: объём по неделям ----------------------------------------------------------


VECTOR = [2, 2, 0, 2, 2, 0]


def test_custom_vector_exact_counts_including_zero():
    assert [custom_week_count(VECTOR, CustomPlanRepeat.ONCE, offset) for offset in range(8)] == [2, 2, 0, 2, 2, 0, 0, 0]
    assert [custom_week_count(VECTOR, CustomPlanRepeat.CYCLE, offset) for offset in range(8)] == [2, 2, 0, 2, 2, 0, 2, 2]


def test_custom_occurrences_rotation_and_weekday_hint_do_not_change_volume():
    for offset, expected in enumerate(VECTOR):
        with_hint = custom_week_occurrences(
            workout_ids=[100, 200], weeks=VECTOR, repeat=CustomPlanRepeat.ONCE, week_offset=offset,
            preferred_weekdays=[1, 3, 5],
        )
        without = custom_week_occurrences(
            workout_ids=[100, 200], weeks=VECTOR, repeat=CustomPlanRepeat.ONCE, week_offset=offset,
            preferred_weekdays=None,
        )
        assert len(with_hint) == len(without) == expected
    week4 = custom_week_occurrences(
        workout_ids=[100, 200, 300], weeks=VECTOR, repeat=CustomPlanRepeat.ONCE, week_offset=3, preferred_weekdays=[0],
    )
    # сквозная ротация: до недели 4 было 2+2+0 = 4 занятия → 4 % 3 = 1 → 200, 300
    assert [(o.occurrence_index, o.workout_definition_id, o.day_of_week) for o in week4] == [(1, 200, 0), (2, 300, None)]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"workout_count": 0, "weeks": [1], "preferred_weekdays": None}, "хотя бы одна"),
        ({"workout_count": 1, "weeks": [], "preferred_weekdays": None}, "Недель"),
        ({"workout_count": 1, "weeks": [15], "preferred_weekdays": None}, "от 0 до"),
        ({"workout_count": 1, "weeks": [-1], "preferred_weekdays": None}, "от 0 до"),
        ({"workout_count": 1, "weeks": [0, 0], "preferred_weekdays": None}, "Хотя бы в одной"),
        ({"workout_count": 1, "weeks": [1], "preferred_weekdays": [7]}, "Дни недели"),
        ({"workout_count": 1, "weeks": [1], "preferred_weekdays": [1, 1]}, "Дни недели"),
    ],
)
def test_custom_plan_validation(kwargs, message):
    with pytest.raises(CustomPlanError, match=message):
        validate_custom_plan(**kwargs)


def test_custom_plan_zero_week_is_valid():
    validate_custom_plan(workout_count=1, weeks=VECTOR, preferred_weekdays=None)


# --- Разворот агрегата ---------------------------------------------------------------------


def test_assign_aggregate_credits_in_performed_order_and_never_invents():
    sessions = [(31, MON + timedelta(days=3)), (30, MON)]
    assert assign_aggregate_credits([1, 2, 3], sessions) == {1: 30, 2: 31}
    assert assign_aggregate_credits([1], sessions) == {1: 30}  # лишняя сессия не засчитывается
    assert assign_aggregate_credits([], sessions) == {}
