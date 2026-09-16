"""Рекомендации типов 1 (снаряд/цифры) и 2 (режим тренировок) — см. Часть 6
респека. Тип 3 (подбор факультативов под слабое место) сознательно не
реализован: требует списка упражнений, которого пока нет ("не выдумывай
содержание" — прямая инструкция пользователя).

Каждая check_* функция — чистая проверка от истории (list[WorkoutRecord]),
без побочных эффектов и без знания о текстах/Telegram. Формирование текста
из Recommendation — забота вызывающего кода (по аналогии с
domain/achievements.py)."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise
from statistics import mean

from app.domain.constants import (
    CONSISTENT_STREAK_DAYS,
    EQUIPMENT_TOO_LIGHT_LOOKBACK,
    EQUIPMENT_TOO_LIGHT_MARGIN,
    GAP_ROLLBACK_DAYS,
    MIN_REST_DAYS,
    MINIMAL_REST_MARGIN_DAYS,
    UNDERWORKING_GAP_THRESHOLD,
    VOLUME_DROP_LOOKBACK,
    WEAK_SET_DROP_THRESHOLD,
    WEAK_SET_LOOKBACK,
    EquipmentType,
)
from app.domain.session import BlockAssignment, WorkoutRecord


class RecommendationCode(StrEnum):
    UNDERWORKING_SETS = "underworking_sets"
    EQUIPMENT_TOO_LIGHT = "equipment_too_light"
    WEAK_SET_INDEX = "weak_set_index"
    MINIMAL_REST_VOLUME_DROP = "minimal_rest_volume_drop"
    CONSISTENT_STREAK = "consistent_streak"


@dataclass(frozen=True)
class Recommendation:
    code: RecommendationCode
    context: dict = field(default_factory=dict)


def _block(record: WorkoutRecord, block: str) -> BlockAssignment:
    return record.block_a if block == "a" else record.block_b


# --- Тип 1: по снаряду и цифрам ---------------------------------------------------


def check_underworking_sets(record: WorkoutRecord, block: str) -> Recommendation | None:
    """«Максимум намного выше рабочих подходов — недорабатываешь в
    рабочих»: если максимум систематически намного превышает средние
    рабочие подходы, в рабочих подходах явно остаётся запас, который
    можно нагружать сильнее."""
    working_reps = _block(record, block).log.working_reps
    if not working_reps:
        return None
    gap = _block(record, block).log.max_reps - mean(working_reps)
    if gap >= UNDERWORKING_GAP_THRESHOLD:
        return Recommendation(RecommendationCode.UNDERWORKING_SETS, {"block": block, "gap": round(gap, 1)})
    return None


def _same_equipment(a: BlockAssignment, b: BlockAssignment) -> bool:
    """«Тот же снаряд» — для BAND сравниваем личный список пользователя
    (equipment_item_id, kg не всегда известен и может отличаться на одном
    и том же снаряде после редактирования), для WEIGHT — по-прежнему
    equipment_value. См. ту же логику в domain/reports.py — здесь не
    импортирую оттуда намеренно: это маленький, самодостаточный предикат,
    не стоит городить общий модуль ради восьми строк.

    equipment_item_id может стать None и для уже использованной резины
    (issue #148, удаление — ON DELETE SET NULL) — без тай-брейка по
    equipment_item_name (снапшот на момент тренировки, переживает
    удаление) две РАЗНЫЕ удалённые резины (оба id None) выглядели бы тем
    же снарядом, см. идентичное рассуждение в domain/reports.py."""
    if a.equipment_type != b.equipment_type:
        return False
    if a.equipment_type == EquipmentType.BAND:
        if a.equipment_item_id is not None or b.equipment_item_id is not None:
            return a.equipment_item_id == b.equipment_item_id
        return a.equipment_item_name == b.equipment_item_name
    if a.equipment_type == EquipmentType.WEIGHT:
        return a.equipment_value == b.equipment_value
    return True


def check_equipment_too_light(
    records: list[WorkoutRecord], block: str, lookback: int = EQUIPMENT_TOO_LIGHT_LOOKBACK,
) -> Recommendation | None:
    """Снаряд слишком лёгкий: максимум стабильно (на протяжении `lookback`
    тренировок подряд на одном и том же снаряде) превышает цель на
    EQUIPMENT_TOO_LIGHT_MARGIN и больше — большой запас каждый раз."""
    recent = records[-lookback:]
    if len(recent) < lookback:
        return None

    first_equipment = _block(recent[0], block)
    if not all(_same_equipment(_block(r, block), first_equipment) for r in recent):
        return None

    if all(_block(r, block).log.max_reps - _block(r, block).target_before >= EQUIPMENT_TOO_LIGHT_MARGIN for r in recent):
        return Recommendation(RecommendationCode.EQUIPMENT_TOO_LIGHT, {"block": block})
    return None


def check_weak_set_index(
    records: list[WorkoutRecord], block: str, lookback: int = WEAK_SET_LOOKBACK,
) -> Recommendation | None:
    """Конкретный по позиции рабочий подход стабильно проваливается
    относительно остальных подходов той же тренировки — за последние
    `lookback` тренировок. Сигнал "не хватает отдыха между подходами"."""
    recent = records[-lookback:]
    if len(recent) < lookback:
        return None

    reps_matrix = [_block(r, block).log.working_reps for r in recent]
    if not reps_matrix[0] or any(len(row) != len(reps_matrix[0]) for row in reps_matrix):
        return None

    set_count = len(reps_matrix[0])
    for index in range(set_count):
        this_set = [row[index] for row in reps_matrix]
        other_sets = [value for row in reps_matrix for pos, value in enumerate(row) if pos != index]
        if not other_sets:
            continue
        if mean(this_set) <= mean(other_sets) - WEAK_SET_DROP_THRESHOLD:
            return Recommendation(RecommendationCode.WEAK_SET_INDEX, {"block": block, "set_number": index + 1})
    return None


# --- Тип 2: по режиму тренировок --------------------------------------------------


def check_minimal_rest_volume_drop(
    records: list[WorkoutRecord], lookback: int = VOLUME_DROP_LOOKBACK,
) -> Recommendation | None:
    """Тренируешься на грани минимального отдыха, и объём при этом падает
    от тренировки к тренировке — возможно, не хватает восстановления,
    стоит взять лишний день."""
    recent = records[-lookback:]
    if len(recent) < lookback:
        return None

    at_minimal_rest = all(
        (later.performed_at.date() - earlier.performed_at.date()).days <= MIN_REST_DAYS + MINIMAL_REST_MARGIN_DAYS
        for earlier, later in pairwise(recent)
    )
    if not at_minimal_rest:
        return None

    volumes = [r.block_a.log.volume + r.block_b.log.volume for r in recent]
    volume_dropping = all(later < earlier for earlier, later in pairwise(volumes))
    if volume_dropping:
        return Recommendation(RecommendationCode.MINIMAL_REST_VOLUME_DROP)
    return None


def check_consistent_streak(
    records: list[WorkoutRecord], current_date: date, streak_days: int = CONSISTENT_STREAK_DAYS,
) -> Recommendation | None:
    """Три недели без пропусков — тот же принцип, что и
    achievements.check_month_without_gaps (сравнение соседних
    контрольных точек, включая края окна), но короче: 21 день, а не 30."""
    window_start = current_date - timedelta(days=streak_days)
    dates_in_window = sorted(r.performed_at.date() for r in records if window_start <= r.performed_at.date() <= current_date)
    if not dates_in_window:
        return None

    checkpoints = [window_start, *dates_in_window, current_date]
    for earlier, later in pairwise(checkpoints):
        if (later - earlier).days >= GAP_ROLLBACK_DAYS:
            return None
    return Recommendation(RecommendationCode.CONSISTENT_STREAK, {"days": streak_days})
