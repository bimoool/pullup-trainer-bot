from datetime import date, timedelta

from app.domain.achievements import (
    AchievementCode,
    check_equipment_changed,
    check_first_baseline,
    check_first_weighted_pullup,
    check_max_reps_gain,
    check_month_without_gaps,
    check_set_completed,
    check_workout_streak,
)


def test_check_first_baseline_true():
    assert check_first_baseline(True) == AchievementCode.FIRST_BASELINE


def test_check_first_baseline_false():
    assert check_first_baseline(False) is None


def test_check_workout_streak_at_ten():
    assert check_workout_streak(10) == AchievementCode.TEN_WORKOUTS_STREAK


def test_check_workout_streak_not_ten():
    assert check_workout_streak(9) is None
    assert check_workout_streak(11) is None


def test_check_equipment_changed_true():
    assert check_equipment_changed(True) == AchievementCode.EQUIPMENT_CHANGED


def test_check_equipment_changed_false():
    assert check_equipment_changed(False) is None


def test_check_first_weighted_pullup_true():
    assert check_first_weighted_pullup(True) == AchievementCode.FIRST_WEIGHTED_PULLUP


def test_check_set_completed_true():
    assert check_set_completed(True) == AchievementCode.SET_COMPLETED


def test_check_set_completed_false():
    assert check_set_completed(False) is None


def test_check_max_reps_gain_at_five():
    assert check_max_reps_gain(max_reps_now=20, max_reps_at_baseline=15) == AchievementCode.MAX_REPS_PLUS_FIVE


def test_check_max_reps_gain_below_five():
    assert check_max_reps_gain(max_reps_now=19, max_reps_at_baseline=15) is None


def test_check_month_without_gaps_no_workouts():
    assert check_month_without_gaps([], date(2026, 1, 31)) is None


def test_check_month_without_gaps_dense_schedule():
    current = date(2026, 1, 31)
    dates = [current - timedelta(days=step) for step in range(0, 31, 3)]
    assert check_month_without_gaps(dates, current) == AchievementCode.MONTH_NO_GAPS


def test_check_month_without_gaps_with_large_gap_in_middle():
    current = date(2026, 1, 31)
    dates = [current, current - timedelta(days=5), current - timedelta(days=29)]
    # между -5 и -29 разрыв 24 дня >= GAP_ROLLBACK_DAYS(21)
    assert check_month_without_gaps(dates, current) is None


def test_check_month_without_gaps_missing_start_of_window():
    current = date(2026, 1, 31)
    # первая тренировка в окне только на 10-й день — от начала окна разрыв 10 дней, это ок,
    # но если она позже 21-го дня от начала — разрыв уже недопустим
    dates = [current - timedelta(days=25)]
    assert check_month_without_gaps(dates, current) is None
