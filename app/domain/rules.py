from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from app.domain.constants import (
    BACKDATE_MAX_DAYS,
    BASELINE_VALID_DAYS,
    BLOCK_A,
    GAP_RETEST_DAYS,
    GAP_ROLLBACK_DAYS,
    MIN_REST_DAYS,
    SET_LENGTH,
    Branch,
)


class TrainingReadiness(StrEnum):
    """Статус готовности к следующей тренировке по дате последней тренировки."""

    READY = "ready"
    TOO_EARLY = "too_early"
    GAP_ROLLBACK = "gap_rollback"
    GAP_RETEST_REQUIRED = "gap_retest_required"


@dataclass(frozen=True)
class ReadinessCheck:
    status: TrainingReadiness
    ready_at: date | None = None
    days_since_last_workout: int = 0


def check_training_readiness(last_workout_date: date, current_date: date) -> ReadinessCheck:
    """Определяет, можно ли тренироваться сейчас, и почему нет, если нельзя.

    days = current_date - last_workout_date
    days < MIN_REST_DAYS                          → TOO_EARLY
    MIN_REST_DAYS <= days < GAP_ROLLBACK_DAYS      → READY
    GAP_ROLLBACK_DAYS <= days <= GAP_RETEST_DAYS   → GAP_ROLLBACK
    days > GAP_RETEST_DAYS                         → GAP_RETEST_REQUIRED
    """
    days = (current_date - last_workout_date).days

    if days < MIN_REST_DAYS:
        ready_at = last_workout_date + timedelta(days=MIN_REST_DAYS)
        return ReadinessCheck(
            status=TrainingReadiness.TOO_EARLY, ready_at=ready_at, days_since_last_workout=days,
        )
    if days < GAP_ROLLBACK_DAYS:
        return ReadinessCheck(status=TrainingReadiness.READY, days_since_last_workout=days)
    if days <= GAP_RETEST_DAYS:
        return ReadinessCheck(status=TrainingReadiness.GAP_ROLLBACK, days_since_last_workout=days)
    return ReadinessCheck(status=TrainingReadiness.GAP_RETEST_REQUIRED, days_since_last_workout=days)


def is_baseline_expired(baseline_date: date, current_date: date) -> bool:
    """Замер просрочен, если с даты замера прошло >= BASELINE_VALID_DAYS (35) дней.

    Это другая точка отсчёта, чем в check_training_readiness: здесь считаем
    от даты замера, а не от даты последней тренировки, поэтому граница
    независима от GAP_RETEST_DAYS и остаётся нестрогой (>=).
    """
    return (current_date - baseline_date).days >= BASELINE_VALID_DAYS


def is_backdate_allowed(workout_date: date, current_date: date) -> bool:
    """Тренировку можно внести задним числом не глубже BACKDATE_MAX_DAYS (7)
    дней от текущей даты (и не в будущее)."""
    days = (current_date - workout_date).days
    return 0 <= days <= BACKDATE_MAX_DAYS


def is_set_complete(completed_workouts_in_set: int) -> bool:
    """Сет завершён по достижении SET_LENGTH (12) полностью завершённых
    тренировок (замеры в счётчик не входят — считать их снаружи)."""
    return completed_workouts_in_set >= SET_LENGTH


def determine_branch(reps: int) -> Branch:
    """Ветка по итогам замера: BAND, если сделано хотя бы BLOCK_A.base_target
    повторений на резине (тот же порог, что и стартовая цель блока A — это
    не совпадение, а одно и то же число), иначе ASSISTED."""
    return Branch.BAND if reps >= BLOCK_A.base_target else Branch.ASSISTED
