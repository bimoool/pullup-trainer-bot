from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class EquipmentType(StrEnum):
    """Точка на единой шкале нагрузки: толстая резина → тонкая резина →
    собственный вес → отягощение. AUSTRALIAN — не про сопротивление в кг
    вообще (регулируется углом корпуса), поэтому вне числовой шкалы —
    to_signed_load() для неё не определена."""

    BAND = "band"
    BODYWEIGHT = "bodyweight"
    WEIGHT = "weight"
    AUSTRALIAN = "australian"


def to_signed_load(equipment_type: EquipmentType, equipment_value: Decimal | None) -> Decimal:
    """Переводит снаряд в одну знаковую величину общей шкалы нагрузки.

    У резины и веса противоположный знак у "большего числа": толще резина
    (больше кг сопротивления) — легче тянуться, поэтому резина уходит в
    минус; больше отягощение — тяжелее, значит в плюс. Все сравнения
    "легче/тяжелее" и "прежний/следующий снаряд" должны идти только через
    эту функцию, а не напрямую через equipment_value — иначе направление
    легко перепутать местами.
    """
    if equipment_type == EquipmentType.BAND:
        return -abs(equipment_value or Decimal(0))
    if equipment_type == EquipmentType.BODYWEIGHT:
        return Decimal(0)
    if equipment_type == EquipmentType.WEIGHT:
        return abs(equipment_value or Decimal(0))
    raise ValueError(f"{equipment_type} не имеет знаковой величины на шкале нагрузки")


@dataclass(frozen=True)
class BlockConfig:
    """Параметры прогрессии одного блока. equipment здесь больше нет —
    снаряд не привязан к блоку жёстко, оба блока независимо двигаются по
    одной шкале (см. EquipmentType)."""

    base_target: int
    work_sets: int
    max_step: int
    coef: float
    equipment_change_threshold: int
    # Снаряд меняется, когда КАЖДЫЙ рабочий подход факт достиг этого порога —
    # сравнение с сырыми повторениями, а не с расчётной новой целью (было
    # раньше: "new_target >= change_at"; теперь механизм другой).
    min_viable_reps: int
    # Максимум ниже этого на новом снаряде — снаряд подобран неверно.
    bodyweight_ceiling: int | None
    # Только для объёмного блока (25) — цель не растёт выше на собственном
    # весе, дальше некуда переходить. None — потолка нет (силовой блок).


VOLUME_BLOCK = BlockConfig(
    base_target=10, work_sets=3, max_step=3, coef=0.5,
    equipment_change_threshold=20, min_viable_reps=10, bodyweight_ceiling=25,
)
STRENGTH_BLOCK = BlockConfig(
    base_target=3, work_sets=4, max_step=2, coef=0.5,
    equipment_change_threshold=7, min_viable_reps=3, bodyweight_ceiling=None,
)

WEIGHT_STEP_PCT: float = 0.125
WEIGHT_ROUND_TO_KG: float = 1.25
MIN_REST_DAYS: int = 2
SET_LENGTH: int = 12
BASELINE_VALID_DAYS: int = 35
GAP_ROLLBACK_DAYS: int = 21
GAP_RETEST_DAYS: int = 35
ROLLBACK_REPS: int = 2
ROLLBACK_WEIGHT_PCT: float = 0.10
TRIAL_DAYS: int = 14
TRANSITION_RETRY_WORKOUTS: int = 4
# Тренировок на прежнем снаряде после неудачного перехода, прежде чем
# предлагать повторную попытку.
