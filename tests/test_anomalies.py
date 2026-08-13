"""detect_anomalies (пакет #4) — три независимых мягких проверки введённого
результата плюс их комбинация. Чистая доменная логика, без БД/бота."""

from app.domain.anomalies import AnomalyFlags, detect_anomalies
from app.domain.session import BlockLog


def test_clean_input_has_no_anomalies():
    flags = detect_anomalies(
        BlockLog(working_reps=(15, 15, 15), max_reps=18), previous_avg_working=14.0, expected_work_sets=3,
    )
    assert flags.is_empty()


# --- 1. Абсолютно большое число -----------------------------------------------


def test_working_rep_above_threshold_flagged():
    flags = detect_anomalies(BlockLog(working_reps=(15, 55, 15), max_reps=18), expected_work_sets=3)
    assert flags.large_value == 55


def test_max_rep_above_threshold_flagged():
    flags = detect_anomalies(BlockLog(working_reps=(15, 15, 15), max_reps=55), expected_work_sets=3)
    assert flags.large_value == 55


def test_value_exactly_at_threshold_not_flagged():
    flags = detect_anomalies(BlockLog(working_reps=(15, 15, 15), max_reps=50), expected_work_sets=3)
    assert flags.large_value is None


def test_largest_offending_value_reported_when_several_exceed():
    flags = detect_anomalies(BlockLog(working_reps=(51, 60, 15), max_reps=18), expected_work_sets=3)
    assert flags.large_value == 60


# --- 2. Резкий скачок относительно истории -------------------------------------


def test_no_history_skips_jump_check():
    flags = detect_anomalies(
        BlockLog(working_reps=(30, 30, 30), max_reps=35), previous_avg_working=None, expected_work_sets=3,
    )
    assert flags.previous_avg is None
    assert flags.current_avg is None


def test_double_the_previous_average_flagged():
    flags = detect_anomalies(
        BlockLog(working_reps=(24, 24, 24), max_reps=28), previous_avg_working=12.0, expected_work_sets=3,
    )
    assert flags.previous_avg == 12.0
    assert flags.current_avg == 24.0


def test_just_under_double_not_flagged():
    flags = detect_anomalies(
        BlockLog(working_reps=(23, 23, 23), max_reps=28), previous_avg_working=12.0, expected_work_sets=3,
    )
    assert flags.previous_avg is None


def test_drop_below_previous_average_not_flagged():
    # Только рост, не падение — п.2 пакета #4 говорит "минимум в 2 раза выше".
    flags = detect_anomalies(
        BlockLog(working_reps=(3, 3, 3), max_reps=4), previous_avg_working=12.0, expected_work_sets=3,
    )
    assert flags.previous_avg is None


def test_empty_working_reps_skips_jump_check():
    # Единичный ввод (свободные подтягивания одним числом) — нет рабочих
    # подходов вообще, сравнивать нечего.
    flags = detect_anomalies(BlockLog(working_reps=(), max_reps=30), previous_avg_working=12.0)
    assert flags.previous_avg is None
    assert flags.current_avg is None


def test_previous_average_zero_does_not_trigger_on_any_growth():
    # Вырожденный случай — прошлая тренировка вся из нулей, avg=0. Любое
    # текущее значение технически ">= 0 * 2", но это не содержательный
    # сигнал, только шум.
    flags = detect_anomalies(
        BlockLog(working_reps=(5, 5, 5), max_reps=6), previous_avg_working=0.0, expected_work_sets=3,
    )
    assert flags.previous_avg is None


# --- 3. Другое количество рабочих подходов -------------------------------------


def test_fewer_sets_than_expected_flagged():
    flags = detect_anomalies(BlockLog(working_reps=(15, 15), max_reps=18), expected_work_sets=3)
    assert flags.expected_set_count == 3
    assert flags.actual_set_count == 2


def test_more_sets_than_expected_flagged():
    flags = detect_anomalies(BlockLog(working_reps=(15, 15, 15, 15, 15), max_reps=18), expected_work_sets=3)
    assert flags.expected_set_count == 3
    assert flags.actual_set_count == 5


def test_matching_set_count_not_flagged():
    flags = detect_anomalies(BlockLog(working_reps=(15, 15, 15), max_reps=18), expected_work_sets=3)
    assert flags.actual_set_count is None


def test_expected_none_disables_set_count_check_entirely():
    # Свободные подтягивания — структурного ожидания просто нет.
    flags = detect_anomalies(BlockLog(working_reps=(8, 6, 5), max_reps=4), expected_work_sets=None)
    assert flags.actual_set_count is None


# --- Комбинация ------------------------------------------------------------------


def test_all_three_anomalies_at_once():
    flags = detect_anomalies(
        BlockLog(working_reps=(55, 55), max_reps=60), previous_avg_working=10.0, expected_work_sets=3,
    )
    assert flags.large_value == 60
    assert flags.previous_avg == 10.0
    assert flags.current_avg == 55.0
    assert flags.actual_set_count == 2
    assert not flags.is_empty()


def test_anomaly_flags_is_empty_true_for_default_instance():
    assert AnomalyFlags().is_empty()
