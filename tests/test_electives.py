"""available_elective_types/is_elective_allowed/volume_target_goal (пакет
#6) — чистая доменная логика ротации без повтора (цикл из 4, свободный
порядок выбора) и недельного лимита."""

from app.domain.electives import (
    ElectiveType,
    available_elective_types,
    is_elective_allowed,
    volume_target_goal,
)

ALL_TYPES = frozenset(ElectiveType)


def test_empty_history_all_four_available():
    assert available_elective_types([]) == ALL_TYPES


def test_one_done_excludes_only_that_one():
    history = [ElectiveType.MAX_REPS_LADDER]
    available = available_elective_types(history)
    assert ElectiveType.MAX_REPS_LADDER not in available
    assert len(available) == 3


def test_two_done_in_any_order_excludes_both():
    history = [ElectiveType.W_LADDER, ElectiveType.VOLUME_TARGET]
    available = available_elective_types(history)
    assert available == ALL_TYPES - {ElectiveType.W_LADDER, ElectiveType.VOLUME_TARGET}


def test_three_done_leaves_exactly_one_available():
    history = [ElectiveType.MAX_REPS_LADDER, ElectiveType.W_LADDER, ElectiveType.THREE_MINUTES]
    available = available_elective_types(history)
    assert available == {ElectiveType.VOLUME_TARGET}


def test_full_cycle_of_four_resets_to_all_available_again():
    history = [ElectiveType.MAX_REPS_LADDER, ElectiveType.W_LADDER, ElectiveType.THREE_MINUTES, ElectiveType.VOLUME_TARGET]
    assert available_elective_types(history) == ALL_TYPES


def test_second_cycle_only_looks_at_current_cycle_not_whole_history():
    # Первый цикл завершён (4 записи), во втором цикле сделан только один.
    history = [
        ElectiveType.MAX_REPS_LADDER, ElectiveType.W_LADDER,
        ElectiveType.THREE_MINUTES, ElectiveType.VOLUME_TARGET,
        ElectiveType.W_LADDER,
    ]
    available = available_elective_types(history)
    assert available == ALL_TYPES - {ElectiveType.W_LADDER}


def test_free_order_choice_does_not_matter_only_the_set_done_matters():
    # Тот же набор "сделано", разный порядок — результат одинаковый.
    a = available_elective_types([ElectiveType.MAX_REPS_LADDER, ElectiveType.W_LADDER])
    b = available_elective_types([ElectiveType.W_LADDER, ElectiveType.MAX_REPS_LADDER])
    assert a == b


def test_available_never_empty_across_full_multi_cycle_history():
    history = []
    types = list(ElectiveType)
    for cycle in range(3):
        for t in types:
            assert available_elective_types(history) != frozenset()
            history.append(t)


# --- Недельный лимит ----------------------------------------------------------------


def test_allowed_when_zero_entries_this_week():
    assert is_elective_allowed(0) is True


def test_not_allowed_when_one_entry_this_week():
    assert is_elective_allowed(1) is False


def test_not_allowed_when_more_than_one_entry_this_week():
    assert is_elective_allowed(3) is False


# --- Цель факультатива на объём ------------------------------------------------------


def test_volume_target_goal_is_five_times_current_target():
    assert volume_target_goal(10) == 50
    assert volume_target_goal(20) == 100
