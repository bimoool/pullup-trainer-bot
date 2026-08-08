import math
from dataclasses import dataclass

from app.domain.constants import (
    BLOCK_A,
    BLOCK_B,
    ROLLBACK_REPS,
    ROLLBACK_WEIGHT_PCT,
    WEIGHT_ROUND_TO_KG,
    WEIGHT_STEP_PCT,
    BlockConfig,
)
from app.domain.session import BlockAssignment, WorkoutRecord


@dataclass(frozen=True)
class ProgressionResult:
    """Результат пересчёта цели по одному блоку.

    equipment_changed=True означает, что new_target уже сброшен на
    block.base_target — резина тоньше (блок A) либо вес +12.5% (блок B).
    Какая именно следующая резина — вне домена; для веса формула есть
    в next_weight_kg ниже.
    """

    new_target: int
    equipment_changed: bool


def recalculate_target(
    block: BlockConfig,
    target: int,
    max_reps: int,
    volume: int,
    prev_volume: int,
) -> ProgressionResult:
    """Единая формула пересчёта цели для блока A и блока B.

    delta = max_reps - target
    delta > 0  → new_target = target + min(block.max_step, ceil(delta * block.coef))
    delta == 0 → new_target = target
    delta < 0  → new_target = target, если volume > prev_volume, иначе target - 1

    Если итоговый new_target >= block.change_at — equipment_changed=True,
    а new_target сбрасывается на block.base_target.
    """
    delta = max_reps - target
    if delta > 0:
        step = min(block.max_step, math.ceil(delta * block.coef))
        new_target = target + step
    elif delta == 0:
        new_target = target
    else:
        new_target = target if volume > prev_volume else target - 1

    if new_target >= block.change_at:
        return ProgressionResult(new_target=block.base_target, equipment_changed=True)
    return ProgressionResult(new_target=new_target, equipment_changed=False)


def _ceil_to_step(value: float, step: float) -> float:
    # round() перед ceil/floor гасит шум плавающей точки (1e-9 << 1.25),
    # чтобы значение, которое математически ровно на шаге, не съезжало
    # на следующий шаг из-за представления float.
    ratio = round(value / step, 9)
    return round(math.ceil(ratio) * step, 2)


def _floor_to_step(value: float, step: float) -> float:
    ratio = round(value / step, 9)
    return round(math.floor(ratio) * step, 2)


def next_weight_kg(current_weight_kg: float) -> float:
    """Новый вес блока B после смены снаряда: +WEIGHT_STEP_PCT (12.5%),
    округление ВВЕРХ до шага WEIGHT_ROUND_TO_KG (1.25 кг) — блинов меньше
    шага не бывает, а округление вниз могло бы застопорить прогрессию при
    небольшом приросте."""
    return _ceil_to_step(current_weight_kg * (1 + WEIGHT_STEP_PCT), WEIGHT_ROUND_TO_KG)


def rollback_target(target: int) -> int:
    """Откат цели блока A при пропуске 21–35 дней: target - ROLLBACK_REPS."""
    return target - ROLLBACK_REPS


def rollback_weight_kg(current_weight_kg: float) -> float:
    """Откат веса блока B при пропуске 21–35 дней: -ROLLBACK_WEIGHT_PCT (10%),
    округление ВНИЗ до шага WEIGHT_ROUND_TO_KG (в отличие от next_weight_kg).
    Итоговый вес получается <= точного значения -10%, то есть фактическое
    снижение веса всегда не меньше 10%."""
    return _floor_to_step(current_weight_kg * (1 - ROLLBACK_WEIGHT_PCT), WEIGHT_ROUND_TO_KG)


def recalculate_cascade(
    starting_target_a: int,
    starting_target_b: int,
    starting_volume_a: int,
    starting_volume_b: int,
    subsequent_workouts: list[WorkoutRecord],
) -> list[WorkoutRecord]:
    """Каскадный пересчёт цепочки тренировок после редактирования более
    ранней тренировки.

    starting_target_a/b — цели, которые действуют СРАЗУ ПОСЛЕ
    отредактированной тренировки (new_target из recalculate_target,
    посчитанного на изменённых данных этой более ранней тренировки).
    starting_volume_a/b — объёмы (BlockLog.volume) этой же отредактированной
    тренировки: они нужны как prev_volume для самой первой тренировки
    из subsequent_workouts (recalculate_target не работает без prev_volume,
    а взять его больше неоткуда — предыдущая тренировка не входит в список).

    subsequent_workouts — все тренировки, идущие ПОСЛЕ отредактированной,
    в хронологическом порядке, с их РЕАЛЬНО введёнными повторениями
    (BlockLog.working_reps/max_reps не меняются — переиграть факт нельзя,
    меняются только выведенные из него target_before/target_after/
    equipment_changed).

    Возвращает новый список WorkoutRecord той же длины и порядка с
    обновлёнными полями block_a/block_b.
    """
    updated: list[WorkoutRecord] = []
    target_a, target_b = starting_target_a, starting_target_b
    prev_volume_a, prev_volume_b = starting_volume_a, starting_volume_b

    for record in subsequent_workouts:
        result_a = recalculate_target(
            BLOCK_A, target_a, record.block_a.log.max_reps, record.block_a.log.volume, prev_volume_a,
        )
        result_b = recalculate_target(
            BLOCK_B, target_b, record.block_b.log.max_reps, record.block_b.log.volume, prev_volume_b,
        )
        updated.append(
            WorkoutRecord(
                performed_at=record.performed_at,
                block_a=BlockAssignment(
                    log=record.block_a.log,
                    target_before=target_a,
                    target_after=result_a.new_target,
                    equipment_changed=result_a.equipment_changed,
                ),
                block_b=BlockAssignment(
                    log=record.block_b.log,
                    target_before=target_b,
                    target_after=result_b.new_target,
                    equipment_changed=result_b.equipment_changed,
                ),
                comment=record.comment,
            )
        )
        target_a, target_b = result_a.new_target, result_b.new_target
        prev_volume_a, prev_volume_b = record.block_a.log.volume, record.block_b.log.volume

    return updated
