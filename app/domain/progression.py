import math
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.constants import (
    ROLLBACK_REPS,
    ROLLBACK_WEIGHT_PCT,
    STRENGTH_BLOCK,
    TRANSITION_RETRY_WORKOUTS,
    VOLUME_BLOCK,
    WEIGHT_ROUND_TO_KG,
    BlockConfig,
    EquipmentType,
)
from app.domain.session import BlockAssignment, WorkoutRecord


@dataclass(frozen=True)
class ProgressionResult:
    """Результат пересчёта цели по одному блоку.

    equipment_changed=True означает, что new_target уже сброшен на
    block.base_target — снаряд меняется на следующий по шкале. Какой именно
    (толщина резины/конкретный вес) — вне домена, пользователь вводит сам.
    ceiling_reached=True — только для объёмного блока на собственном весе:
    цель дошла до bodyweight_ceiling и дальше не растёт (переходить некуда).
    """

    new_target: int
    equipment_changed: bool
    ceiling_reached: bool = False


def recalculate_target(
    block: BlockConfig,
    target: int,
    working_reps: tuple[int, ...],
    max_reps: int,
    volume: int,
    prev_volume: int,
    equipment_type: EquipmentType,
) -> ProgressionResult:
    """Единая формула пересчёта цели для объёмного и силового блока.

    delta = max_reps - target
    delta > 0  → new_target = target + min(block.max_step, ceil(delta * block.coef))
    delta == 0 → new_target = target
    delta < 0  → new_target = target, если volume > prev_volume, иначе target - 1

    Снаряд меняется, когда КАЖДЫЙ элемент working_reps (рабочие подходы,
    без учёта подхода на максимум) достиг block.equipment_change_threshold —
    сравнение идёт с фактическими повторениями, не с расчётной new_target
    ("20 20 20 21" — порог взят; "19 19 19 22" — нет, хотя максимум выше).

    Исключение — объёмный блок на собственном весе с заданным
    bodyweight_ceiling: там переходить дальше некуда, поэтому вместо смены
    снаряда new_target просто не растёт выше потолка.
    """
    delta = max_reps - target
    if delta > 0:
        step = min(block.max_step, math.ceil(delta * block.coef))
        new_target = target + step
    elif delta == 0:
        new_target = target
    else:
        new_target = target if volume > prev_volume else target - 1

    threshold_hit = bool(working_reps) and all(r >= block.equipment_change_threshold for r in working_reps)
    at_ceiling_equipment = block.bodyweight_ceiling is not None and equipment_type == EquipmentType.BODYWEIGHT

    if threshold_hit and not at_ceiling_equipment:
        return ProgressionResult(new_target=block.base_target, equipment_changed=True)

    ceiling_reached = False
    if at_ceiling_equipment:
        ceiling_reached = new_target >= block.bodyweight_ceiling
        new_target = min(new_target, block.bodyweight_ceiling)

    return ProgressionResult(new_target=new_target, equipment_changed=False, ceiling_reached=ceiling_reached)


def suggest_starting_equipment(baseline_reps: int) -> tuple[EquipmentType, EquipmentType]:
    """(объёмный, силовой) — стартовый тип снаряда по итогам замера (только
    число подтягиваний на собственном весе). Точное сопротивление резины
    или вес отягощения бот не подбирает — пользователь вводит фактическое
    на первой тренировке, здесь только тип.

    Силовой блок никогда не легче объёмного (см. спеку: "блок на силу
    всегда правее по шкале") — если объёмный стартует на резине, силовой
    тоже на резине; если объёмный сразу на собственном весе, силовой
    предлагается туда же (консервативный старт, не сразу отягощение).
    """
    if baseline_reps >= VOLUME_BLOCK.base_target:
        return EquipmentType.BODYWEIGHT, EquipmentType.BODYWEIGHT
    return EquipmentType.BAND, EquipmentType.BAND


class TransitionOutcome(StrEnum):
    """Результат проверки первой тренировки на новом снаряде."""

    NOT_APPLICABLE = "not_applicable"  # не первая тренировка на этом снаряде — проверка не при делах
    VIABLE = "viable"
    FAILED = "failed"  # максимум ниже min_viable_reps — снаряд подобран неверно


def check_transition_outcome(
    block: BlockConfig, max_reps: int, *, is_first_workout_on_new_gear: bool,
) -> TransitionOutcome:
    """Проверка идёт по факту тренировки (не пробным подходом заранее) —
    is_first_workout_on_new_gear вычисляет вызывающий код по истории (он и
    так знает equipment_changed предыдущей тренировки), домен остаётся
    чистым от истории."""
    if not is_first_workout_on_new_gear:
        return TransitionOutcome.NOT_APPLICABLE
    return TransitionOutcome.VIABLE if max_reps >= block.min_viable_reps else TransitionOutcome.FAILED


def is_retry_allowed(workouts_since_revert: int) -> bool:
    """После неудачного перехода — TRANSITION_RETRY_WORKOUTS (4) тренировок
    на прежнем снаряде, прежде чем снова предлагать переход."""
    return workouts_since_revert >= TRANSITION_RETRY_WORKOUTS


def _ceil_to_step(value: float, step: float) -> float:
    # round() перед ceil/floor гасит шум плавающей точки (1e-9 << 1.25),
    # чтобы значение, которое математически ровно на шаге, не съезжало
    # на следующий шаг из-за представления float.
    ratio = round(value / step, 9)
    return round(math.ceil(ratio) * step, 2)


def _floor_to_step(value: float, step: float) -> float:
    ratio = round(value / step, 9)
    return round(math.floor(ratio) * step, 2)


def suggest_weight_range(current_weight_kg: Decimal) -> tuple[Decimal, Decimal] | None:
    """Диапазон рекомендованной прибавки при переходе силового блока на
    больший вес (+10–15%) — бот больше не считает точный новый вес сам
    (было раньше — next_weight_kg), только подсказывает диапазон,
    пользователь вводит фактический вес, с которым стал заниматься.

    None, если current_weight_kg <= 0 — это переход с собственного веса
    НА отягощение впервые, процент от нуля ничего не значит; в этом случае
    пользователю нужно предложить взять небольшой стартовый вес, а не
    процентный диапазон (это уже забота вызывающего кода/текстов).
    """
    if current_weight_kg <= 0:
        return None
    low = _ceil_to_step(float(current_weight_kg) * 1.10, WEIGHT_ROUND_TO_KG)
    high = _ceil_to_step(float(current_weight_kg) * 1.15, WEIGHT_ROUND_TO_KG)
    return Decimal(str(low)), Decimal(str(high))


def rollback_target(target: int) -> int:
    """Откат цели объёмного блока при пропуске 21–35 дней: target - ROLLBACK_REPS."""
    return target - ROLLBACK_REPS


def rollback_weight_kg(current_weight_kg: float) -> float:
    """Откат нагрузки силового блока при пропуске 21–35 дней:
    -ROLLBACK_WEIGHT_PCT (10%), округление ВНИЗ до шага WEIGHT_ROUND_TO_KG
    (в отличие от прибавки). Итоговое значение получается <= точного
    -10%, то есть фактическое снижение всегда не меньше 10%. Применяется
    только к силовому блоку (отягощение) — цель по повторениям не трогаем."""
    return _floor_to_step(current_weight_kg * (1 - ROLLBACK_WEIGHT_PCT), WEIGHT_ROUND_TO_KG)


def recalculate_cascade(
    starting_target_a: int,
    starting_target_b: int,
    starting_volume_a: int,
    starting_volume_b: int,
    subsequent_workouts: list[WorkoutRecord],
) -> list[WorkoutRecord]:
    """Каскадный пересчёт цепочки тренировок после редактирования более
    ранней тренировки. Остаётся только для этого сценария — внесённые
    задним числом тренировки в каскад не входят вовсе (фильтрует
    вызывающий код, см. WorkoutRepository).

    starting_target_a/b — цели, которые действуют СРАЗУ ПОСЛЕ
    отредактированной тренировки. starting_volume_a/b — её объёмы, нужны
    как prev_volume для первой тренировки из subsequent_workouts.

    equipment_type и transition_failed каждой записи не пересчитываются —
    это факт того, что было в реальности, каскад его не переигрывает.
    """
    updated: list[WorkoutRecord] = []
    target_a, target_b = starting_target_a, starting_target_b
    prev_volume_a, prev_volume_b = starting_volume_a, starting_volume_b

    for record in subsequent_workouts:
        result_a = recalculate_target(
            VOLUME_BLOCK, target_a, record.block_a.log.working_reps, record.block_a.log.max_reps,
            record.block_a.log.volume, prev_volume_a, record.block_a.equipment_type,
        )
        result_b = recalculate_target(
            STRENGTH_BLOCK, target_b, record.block_b.log.working_reps, record.block_b.log.max_reps,
            record.block_b.log.volume, prev_volume_b, record.block_b.equipment_type,
        )
        updated.append(
            WorkoutRecord(
                performed_at=record.performed_at,
                block_a=BlockAssignment(
                    log=record.block_a.log,
                    target_before=target_a,
                    target_after=result_a.new_target,
                    equipment_changed=result_a.equipment_changed,
                    equipment_type=record.block_a.equipment_type,
                    equipment_value=record.block_a.equipment_value,
                    transition_failed=record.block_a.transition_failed,
                ),
                block_b=BlockAssignment(
                    log=record.block_b.log,
                    target_before=target_b,
                    target_after=result_b.new_target,
                    equipment_changed=result_b.equipment_changed,
                    equipment_type=record.block_b.equipment_type,
                    equipment_value=record.block_b.equipment_value,
                    transition_failed=record.block_b.transition_failed,
                ),
                comment=record.comment,
            )
        )
        target_a, target_b = result_a.new_target, result_b.new_target
        prev_volume_a, prev_volume_b = record.block_a.log.volume, record.block_b.log.volume

    return updated
