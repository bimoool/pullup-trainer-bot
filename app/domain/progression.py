import math
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from statistics import mean

from app.domain.constants import (
    ROLLBACK_REPS,
    ROLLBACK_WEIGHT_PCT,
    STRENGTH_BLOCK,
    STRENGTH_START_BODYWEIGHT_MIN_REPS,
    STRENGTH_START_WEIGHT_MIN_REPS,
    TRANSITION_RETRY_WORKOUTS,
    VOLUME_BLOCK,
    WEAK_STREAK_ROLLBACK_THRESHOLD,
    WEIGHT_ROUND_TO_KG,
    BlockConfig,
    EquipmentType,
    to_signed_load,
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
    consecutive_weak_before: int = 0,
) -> ProgressionResult:
    """Единая формула пересчёта цели для объёмного и силового блока
    (Часть 10, пакет #2, п.12-13 — третья по счёту правка этой функции,
    ПОЛНОСТЬЮ заменяет предыдущую версию "объём везде, без отката", не
    дополняет её).

    Вход в ветку успеха/провала решает delta = max_reps - target, как и
    раньше. Внутри ветки успеха величина шага роста считается не от
    target, а от среднего рабочих подходов (avg_working) — это позволяет
    цели расти сразу к тому уровню, который человек реально показал,
    вместо капа шагом от уже устаревшей цели:

        avg_working = mean(working_reps)
        growth = max_reps - avg_working
        step = max(0, min(block.max_step, ceil(growth * block.coef)))
        new_target = round(avg_working) + step

    round() — обычное (Python round-half-to-even), для согласованности с
    остальной кодовой базой; не критично, по просьбе зафиксировано явно.
    max(0, ...) вокруг step — защита от вырожденного случая, которого нет
    в исходной формуле: working_reps не обязаны быть <= max_reps (парсер
    ввода это не проверяет), и если avg_working сильно выше max_reps при
    этом max_reps всё равно > target (входим в ветку успеха), growth
    уходит в минус и без ограничения new_target мог бы провалиться ниже
    avg_working или даже уйти в отрицательные числа — на практике это
    ошибочный ввод, а не жать, но домен не должен реагировать на него
    абсурдным откатом.

    Ветка провала (delta <= 0) теперь с отсрочкой отката (п.13): "слабая"
    тренировка — объём меньше предыдущего; цель откатывается на -1 только
    после WEAK_STREAK_ROLLBACK_THRESHOLD (3) подряд слабых, не после
    первой. consecutive_weak_before — сколько таких подряд БЫЛО до этой
    тренировки, считает вызывающий код из истории (см.
    count_consecutive_weak_trainings) — домен сам историю не хранит.

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
        avg_working = mean(working_reps) if working_reps else float(target)
        growth = max_reps - avg_working
        step = max(0, min(block.max_step, math.ceil(growth * block.coef)))
        new_target = round(avg_working) + step
    elif delta == 0:
        new_target = target
    else:
        is_weak = volume < prev_volume
        if is_weak and consecutive_weak_before + 1 >= WEAK_STREAK_ROLLBACK_THRESHOLD:
            new_target = target - 1
        else:
            new_target = target

    threshold_hit = bool(working_reps) and all(r >= block.equipment_change_threshold for r in working_reps)
    at_ceiling_equipment = block.bodyweight_ceiling is not None and equipment_type == EquipmentType.BODYWEIGHT

    if threshold_hit and not at_ceiling_equipment:
        return ProgressionResult(new_target=block.base_target, equipment_changed=True)

    ceiling_reached = False
    if at_ceiling_equipment:
        ceiling_reached = new_target >= block.bodyweight_ceiling
        new_target = min(new_target, block.bodyweight_ceiling)

    return ProgressionResult(new_target=new_target, equipment_changed=False, ceiling_reached=ceiling_reached)


def count_consecutive_weak_trainings(volumes: list[int]) -> int:
    """Сколько подряд идущих "слабых" тренировок (Часть 10, пакет #2,
    п.13) стоят в конце volumes — хронологического списка объёмов ОДНОГО
    блока, НЕ включая тренировку, для которой сейчас считается
    consecutive_weak_before. "Слабая" — объём меньше, чем у той, что
    непосредственно перед ней (volumes[i] < volumes[i-1]); первый элемент
    списка сам по себе не может быть "слабым" — сравнивать не с чем.

    Вычисляется каждый раз заново из истории (list_for_user/каскад) — не
    хранимый счётчик, тот же принцип, что уже применён к повторным
    попыткам смены снаряда (is_retry_allowed) и к needs_new_equipment."""
    count = 0
    for i in range(len(volumes) - 1, 0, -1):
        if volumes[i] < volumes[i - 1]:
            count += 1
        else:
            break
    return count


def suggest_starting_equipment(baseline_reps: int) -> tuple[EquipmentType, EquipmentType]:
    """(объёмный, силовой) — стартовый тип снаряда по итогам замера (только
    число подтягиваний на собственном весе). Точное сопротивление резины
    или вес отягощения бот не подбирает — пользователь вводит фактическое
    на первой тренировке, здесь только тип.

    У каждого блока СВОИ пороги (Часть 10 — раньше по ошибке оба блока
    считались по порогу объёмного, силовой блок никогда не получал
    "отягощение" даже при большом замере):
    - объёмный: свой вес строго при замере > VOLUME_BLOCK.base_target (10),
      иначе резина;
    - силовой: отягощение при замере >= STRENGTH_START_WEIGHT_MIN_REPS (8),
      свой вес при STRENGTH_START_BODYWEIGHT_MIN_REPS (3) <= замер < 8,
      иначе (замер < 3) резина.
    """
    volume_equipment = EquipmentType.BODYWEIGHT if baseline_reps > VOLUME_BLOCK.base_target else EquipmentType.BAND

    if baseline_reps >= STRENGTH_START_WEIGHT_MIN_REPS:
        strength_equipment = EquipmentType.WEIGHT
    elif baseline_reps >= STRENGTH_START_BODYWEIGHT_MIN_REPS:
        strength_equipment = EquipmentType.BODYWEIGHT
    else:
        strength_equipment = EquipmentType.BAND

    return volume_equipment, strength_equipment


def initial_volume_target(baseline_reps: int) -> int:
    """Начальная цель объёмного блока при старте (первая тренировка/
    ретест) — Часть 10, пакет #2, п.14, "замер минус 25%".

    Старт на собственном весе (замер > VOLUME_BLOCK.base_target, см.
    suggest_starting_equipment) — начальная цель ceil(замер * 0.75), не
    флэт base_target: сразу отталкивается от реального уровня, а не
    занижает его до дефолтных 10. Округление вверх.

    Старт с резины (замер <= base_target) — без изменений: подбираем
    резину под ~base_target повторений, стартуем flat base_target-
    base_target-base_target-макс, как и раньше."""
    if baseline_reps > VOLUME_BLOCK.base_target:
        return math.ceil(baseline_reps * 0.75)
    return VOLUME_BLOCK.base_target


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


def rollback_signed_load(equipment_type: EquipmentType, equipment_value: Decimal) -> Decimal:
    """Предлагаемая нагрузка силового блока после отката (перерыв 21–35
    дней) — тот же снаряд, но примерно на ROLLBACK_WEIGHT_PCT (10%) легче
    ПО ЗНАКОВОЙ ШКАЛЕ (см. to_signed_load): знаковая величина должна
    УМЕНЬШИТЬСЯ в обоих случаях — для отягощения это меньший вес
    (+20 → +18), для резины — БОЛЬШЕЕ сопротивление в кг, то есть больше
    помощи (−30 → −33, кг резины 30 → 33).

    Именно поэтому здесь нельзя просто умножить |equipment_value| на 0.9:
    для резины это утащило бы знаковую величину К НУЛЮ (−30·0.9 = −27),
    то есть сделало бы снаряд ЖёстЧЕ — прямо противоположно смыслу отката.
    Вместо этого вычитаем долю МОДУЛЯ из знакового значения — это всегда
    двигает его в сторону "легче" независимо от знака.

    Округление — в сторону ещё легче (floor знакового значения), чтобы
    фактическое снижение нагрузки было не меньше заявленных 10%, как и в
    прежней (дошкальной) версии этой функции. Возвращает магнитуду
    (положительное число) — то, что показать пользователю в кг."""
    signed = to_signed_load(equipment_type, equipment_value)
    rolled_back_signed = float(signed) - abs(float(signed)) * ROLLBACK_WEIGHT_PCT
    floored = _floor_to_step(rolled_back_signed, WEIGHT_ROUND_TO_KG)
    return Decimal(str(abs(floored)))


def recalculate_cascade(
    starting_target_a: int,
    starting_target_b: int,
    starting_volume_a: int,
    starting_volume_b: int,
    subsequent_workouts: list[WorkoutRecord],
    starting_weak_streak_a: int = 0,
    starting_weak_streak_b: int = 0,
) -> list[WorkoutRecord]:
    """Каскадный пересчёт цепочки тренировок после редактирования более
    ранней тренировки. Остаётся только для этого сценария — внесённые
    задним числом тренировки в каскад не входят вовсе (фильтрует
    вызывающий код, см. WorkoutRepository).

    starting_target_a/b — цели, которые действуют СРАЗУ ПОСЛЕ
    отредактированной тренировки. starting_volume_a/b — её объёмы, нужны
    как prev_volume для первой тренировки из subsequent_workouts.
    starting_weak_streak_a/b (Часть 10, пакет #2, п.13) — сколько подряд
    слабых тренировок было ДО начала этой цепочки (обычно посчитано
    вызывающим кодом из истории вплоть до отредактированной тренировки
    включительно, см. WorkoutRepository.edit_workout) — дальше счётчик
    бегущий, обновляется по ходу цикла, отдельно нигде не хранится.

    equipment_type и transition_failed каждой записи не пересчитываются —
    это факт того, что было в реальности, каскад его не переигрывает.
    """
    updated: list[WorkoutRecord] = []
    target_a, target_b = starting_target_a, starting_target_b
    prev_volume_a, prev_volume_b = starting_volume_a, starting_volume_b
    weak_streak_a, weak_streak_b = starting_weak_streak_a, starting_weak_streak_b

    for record in subsequent_workouts:
        result_a = recalculate_target(
            VOLUME_BLOCK, target_a, record.block_a.log.working_reps, record.block_a.log.max_reps,
            record.block_a.log.volume, prev_volume_a, record.block_a.equipment_type,
            consecutive_weak_before=weak_streak_a,
        )
        result_b = recalculate_target(
            STRENGTH_BLOCK, target_b, record.block_b.log.working_reps, record.block_b.log.max_reps,
            record.block_b.log.volume, prev_volume_b, record.block_b.equipment_type,
            consecutive_weak_before=weak_streak_b,
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
                    equipment_item_id=record.block_a.equipment_item_id,
                    transition_failed=record.block_a.transition_failed,
                ),
                block_b=BlockAssignment(
                    log=record.block_b.log,
                    target_before=target_b,
                    target_after=result_b.new_target,
                    equipment_changed=result_b.equipment_changed,
                    equipment_type=record.block_b.equipment_type,
                    equipment_value=record.block_b.equipment_value,
                    equipment_item_id=record.block_b.equipment_item_id,
                    transition_failed=record.block_b.transition_failed,
                ),
                comment=record.comment,
                workout_set_id=record.workout_set_id,
                exercise_type=record.exercise_type,
            )
        )
        target_a, target_b = result_a.new_target, result_b.new_target
        weak_streak_a = weak_streak_a + 1 if record.block_a.log.volume < prev_volume_a else 0
        weak_streak_b = weak_streak_b + 1 if record.block_b.log.volume < prev_volume_b else 0
        prev_volume_a, prev_volume_b = record.block_a.log.volume, record.block_b.log.volume

    return updated
