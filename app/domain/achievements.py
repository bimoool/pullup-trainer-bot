from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise

from app.domain.constants import GAP_ROLLBACK_DAYS


class AchievementCode(StrEnum):
    FIRST_BASELINE = "first_baseline"
    TEN_WORKOUTS_STREAK = "ten_workouts_streak"
    BAND_CHANGED = "band_changed"
    FIRST_WEIGHTED_PULLUP = "first_weighted_pullup"
    SET_COMPLETED = "set_completed"
    MAX_REPS_PLUS_FIVE = "max_reps_plus_five"
    MONTH_NO_GAPS = "month_no_gaps"


def check_first_baseline(is_first_baseline: bool) -> AchievementCode | None:
    """FIRST_BASELINE — при самом первом замере пользователя."""
    return AchievementCode.FIRST_BASELINE if is_first_baseline else None


def check_workout_streak(consecutive_completed_workouts: int) -> AchievementCode | None:
    """TEN_WORKOUTS_STREAK — при 10 подряд завершённых тренировках без пропуска."""
    return (
        AchievementCode.TEN_WORKOUTS_STREAK
        if consecutive_completed_workouts == 10
        else None
    )


def check_band_changed(equipment_changed_block_a: bool) -> AchievementCode | None:
    """BAND_CHANGED — когда блок A сообщает equipment_changed=True."""
    return AchievementCode.BAND_CHANGED if equipment_changed_block_a else None


def check_first_weighted_pullup(is_first_block_b_workout: bool) -> AchievementCode | None:
    """FIRST_WEIGHTED_PULLUP — на первой тренировке, где вообще был блок B
    (переход из ASSISTED либо первый BAND-цикл)."""
    return AchievementCode.FIRST_WEIGHTED_PULLUP if is_first_block_b_workout else None


def check_set_completed(is_set_complete: bool) -> AchievementCode | None:
    """SET_COMPLETED — сет закрыт (см. rules.is_set_complete)."""
    return AchievementCode.SET_COMPLETED if is_set_complete else None


def check_max_reps_gain(max_reps_now: int, max_reps_at_baseline: int) -> AchievementCode | None:
    """MAX_REPS_PLUS_FIVE — максимум вырос на >=5 повторений относительно
    последнего замера."""
    return (
        AchievementCode.MAX_REPS_PLUS_FIVE
        if (max_reps_now - max_reps_at_baseline) >= 5
        else None
    )


def check_month_without_gaps(workout_dates: list[date], current_date: date) -> AchievementCode | None:
    """MONTH_NO_GAPS — за последние 30 дней ни разу не было пропуска
    >= GAP_ROLLBACK_DAYS ни между соседними тренировками, ни на краях
    окна (от начала месяца до первой тренировки и от последней до
    текущей даты) — иначе достаточно двух тренировок в начале и конце
    месяца, чтобы засчитать "без пропусков".
    """
    window_start = current_date - timedelta(days=30)
    dates_in_window = sorted(d for d in workout_dates if window_start <= d <= current_date)
    if not dates_in_window:
        return None

    checkpoints = [window_start, *dates_in_window, current_date]
    for earlier, later in pairwise(checkpoints):
        if (later - earlier).days >= GAP_ROLLBACK_DAYS:
            return None
    return AchievementCode.MONTH_NO_GAPS
