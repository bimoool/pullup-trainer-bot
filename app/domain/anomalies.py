from dataclasses import dataclass

from app.domain.constants import ANOMALY_JUMP_MULTIPLIER, ANOMALY_LARGE_VALUE_THRESHOLD
from app.domain.session import BlockLog


@dataclass(frozen=True)
class AnomalyFlags:
    """Что именно показалось подозрительным во введённом результате —
    ничего из этого не блокирует запись, только повод переспросить (см.
    app.bot.formatting.format_anomaly_message)."""

    large_value: int | None = None
    previous_avg: float | None = None
    current_avg: float | None = None
    expected_set_count: int | None = None
    actual_set_count: int | None = None

    def is_empty(self) -> bool:
        return self.large_value is None and self.previous_avg is None and self.actual_set_count is None


def detect_anomalies(
    block_log: BlockLog,
    *,
    previous_avg_working: float | None = None,
    expected_work_sets: int | None = None,
    large_value_threshold: int = ANOMALY_LARGE_VALUE_THRESHOLD,
    jump_multiplier: float = ANOMALY_JUMP_MULTIPLIER,
) -> AnomalyFlags:
    """Три независимые мягкие проверки (пакет #4) — любая их комбинация
    возвращается сразу, вызывающий сам решает, объединять ли в одно
    сообщение (см. format_anomaly_message):

    1. Абсолютно большое число — любое значение (рабочий подход или
       максимум) строго больше large_value_threshold, вне зависимости от
       истории.
    2. Резкий скачок относительно истории — среднее рабочих подходов
       сейчас минимум в jump_multiplier раз выше среднего прошлой
       тренировки этого же блока. previous_avg_working=None (истории нет
       или там нет рабочих подходов — например, единичный ввод) —
       проверка пропускается. working_reps сейчас пуст — тоже
       пропускается (не с чем сравнивать полноценно).
    3. Другое количество рабочих подходов, чем ожидалось структурно.
       expected_work_sets=None — проверка неприменима (свободные
       подтягивания, где структурного ожидания нет вообще)."""
    all_values = (*block_log.working_reps, block_log.max_reps)
    large_value = max((v for v in all_values if v > large_value_threshold), default=None)

    current_avg = None
    jump_previous = None
    jump_current = None
    if block_log.working_reps:
        current_avg = sum(block_log.working_reps) / len(block_log.working_reps)
        if (
            previous_avg_working is not None
            and previous_avg_working > 0
            and current_avg >= previous_avg_working * jump_multiplier
        ):
            jump_previous, jump_current = previous_avg_working, current_avg

    actual_set_count = None
    if expected_work_sets is not None and len(block_log.working_reps) != expected_work_sets:
        actual_set_count = len(block_log.working_reps)

    return AnomalyFlags(
        large_value=large_value,
        previous_avg=jump_previous,
        current_avg=jump_current,
        expected_set_count=expected_work_sets if actual_set_count is not None else None,
        actual_set_count=actual_set_count,
    )
