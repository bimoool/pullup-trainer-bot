from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise

from app.domain.constants import GAP_ROLLBACK_DAYS


class AchievementCode(StrEnum):
    FIRST_BASELINE = "first_baseline"
    TEN_WORKOUTS_STREAK = "ten_workouts_streak"
    EQUIPMENT_CHANGED = "equipment_changed"
    FIRST_WEIGHTED_PULLUP = "first_weighted_pullup"
    SET_COMPLETED = "set_completed"
    MAX_REPS_PLUS_TEN = "max_reps_plus_ten"
    MONTH_NO_GAPS = "month_no_gaps"
    VOLUME_100 = "volume_100"
    VOLUME_1000 = "volume_1000"
    VOLUME_10000 = "volume_10000"
    VOLUME_100000 = "volume_100000"


def check_first_baseline(is_first_baseline: bool) -> AchievementCode | None:
    """FIRST_BASELINE — при самом первом замере пользователя."""
    return AchievementCode.FIRST_BASELINE if is_first_baseline else None


def check_workout_streak(consecutive_completed_workouts: int) -> AchievementCode | None:
    """TEN_WORKOUTS_STREAK — от 10 подряд завершённых тренировок без
    пропуска (>=, не ==: unlock_achievement идемпотентен, а пользователь
    может прийти к проверке уже с более длинной серией — например, если
    достиг 10+ до того, как эта ачивка была подключена — точное совпадение
    в этом случае никогда бы не сработало)."""
    return (
        AchievementCode.TEN_WORKOUTS_STREAK
        if consecutive_completed_workouts >= 10
        else None
    )


def consecutive_streak_length(dates: list[date]) -> int:
    """Длина хвостовой серии tail(dates) без пропуска >= GAP_ROLLBACK_DAYS
    между соседними датами — вход для check_workout_streak. dates не
    обязаны быть упорядочены заранее (сортируем сами, тот же принцип, что
    и в check_month_without_gaps)."""
    ordered = sorted(dates)
    if not ordered:
        return 0
    streak = 1
    for later, earlier in pairwise(reversed(ordered)):
        if (later - earlier).days >= GAP_ROLLBACK_DAYS:
            break
        streak += 1
    return streak


def check_equipment_changed(equipment_changed: bool) -> AchievementCode | None:
    """EQUIPMENT_CHANGED — любой блок сообщает equipment_changed=True
    (переход на следующий снаряд по шкале — в любую сторону, не только
    "резина потоньше", как раньше в BAND_CHANGED)."""
    return AchievementCode.EQUIPMENT_CHANGED if equipment_changed else None


def check_first_weighted_pullup(is_first_workout_with_added_weight: bool) -> AchievementCode | None:
    """FIRST_WEIGHTED_PULLUP — первая тренировка, где силовой блок выполнен
    с equipment_type == WEIGHT (раньше это совпадало с "первая тренировка
    вообще" в ветке BAND — теперь силовой блок может стартовать и на
    резине, так что это отдельная, более поздняя точка)."""
    return AchievementCode.FIRST_WEIGHTED_PULLUP if is_first_workout_with_added_weight else None


def check_set_completed(is_set_complete: bool) -> AchievementCode | None:
    """SET_COMPLETED — сет закрыт (см. rules.is_set_complete)."""
    return AchievementCode.SET_COMPLETED if is_set_complete else None


def check_max_reps_gain(max_reps_now: int, max_reps_at_baseline: int) -> AchievementCode | None:
    """MAX_REPS_PLUS_TEN — максимум вырос на >=10 повторений относительно
    последнего замера."""
    return (
        AchievementCode.MAX_REPS_PLUS_TEN
        if (max_reps_now - max_reps_at_baseline) >= 10
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


_VOLUME_MILESTONES: tuple[tuple[int, AchievementCode], ...] = (
    (100, AchievementCode.VOLUME_100),
    (1_000, AchievementCode.VOLUME_1000),
    (10_000, AchievementCode.VOLUME_10000),
    (100_000, AchievementCode.VOLUME_100000),
)


def check_volume_milestones(total_volume: int) -> list[AchievementCode]:
    """Все пороги пожизненного объёма подтягиваний, достигнутые к
    total_volume (обычные тренировки + бэкдейт + свободные + факультативы
    — сумма считается вызывающим кодом, здесь только сравнение с
    порогами). Возвращает ВСЕ достигнутые коды, а не только новый —
    unlock_achievement идемпотентен, так что уже разблокированные пороги
    просто не начислят монеты повторно; это же делает функцию безопасной
    для ретроактивного бэкфилла, где объём мог перескочить сразу через
    несколько порогов."""
    return [code for threshold, code in _VOLUME_MILESTONES if total_volume >= threshold]
