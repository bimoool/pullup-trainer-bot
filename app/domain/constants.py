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


class ExerciseType(StrEnum):
    """Задел под будущее расширение (отжимания на брусьях, выходы силой,
    подтягивания на одной руке) — сейчас только подтягивания. Раньше жил в
    app/db/models.py — перенесено в домен по той же логике, что и
    EquipmentType: это словарь предметной области, а не деталь схемы."""

    PULL_UPS = "pull_ups"


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

# Пороги стартового снаряда силового блока по замеру (Часть 10 — раньше
# suggest_starting_equipment ошибочно применял пороги объёмного блока к
# обоим блокам). Объёмный блок использует свой собственный порог —
# VOLUME_BLOCK.base_target, строго больше (не >=).
STRENGTH_START_WEIGHT_MIN_REPS: int = 8
STRENGTH_START_BODYWEIGHT_MIN_REPS: int = 3

# Отсрочка отката цели (Часть 10, пакет #2, п.13) — "слабая" тренировка
# (объём меньше предыдущего) откатывает цель на -1 только после стольких
# подряд слабых тренировок, не после первой же. Заменяет собой прежнее
# правило "объём везде, без отката" (NO_CAP_MAX_SPREAD удалён вместе с ним).
WEAK_STREAK_ROLLBACK_THRESHOLD: int = 3

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

# Продуктовая константа платной подписки (990₽/мес) — раньше жила в
# app/services/tribute.py (единственном на тот момент платёжном провайдере),
# перенесена сюда при удалении Tribute (отказ в верификации продавца):
# и Robokassa, и Stars (payments_stars.py) ссылаются на неё одинаково,
# провайдер-специфичного смысла в ней нет.
SUBSCRIPTION_PRICE_RUB: int = 990
SUBSCRIPTION_DAYS: int = 30
SUBSCRIPTION_DESCRIPTION: str = f"Доступ на {SUBSCRIPTION_DAYS} дней"

TRANSITION_RETRY_WORKOUTS: int = 4
# Тренировок на прежнем снаряде после неудачного перехода, прежде чем
# предлагать повторную попытку.

# --- Рекомендации (app/domain/recommendations.py) — типы 1 и 2 ------------------

UNDERWORKING_GAP_THRESHOLD: int = 5
# Максимум минус средние рабочие подходы >= этого — рабочие подходы идут
# сильно легче максимума, есть простор нагружать их больше.
EQUIPMENT_TOO_LIGHT_MARGIN: int = 5
EQUIPMENT_TOO_LIGHT_LOOKBACK: int = 3
# Максимум стабильно превышает цель на EQUIPMENT_TOO_LIGHT_MARGIN и больше
# на протяжении EQUIPMENT_TOO_LIGHT_LOOKBACK тренировок подряд на одном
# снаряде — снаряд явно недооценивает уровень.
WEAK_SET_DROP_THRESHOLD: int = 3
WEAK_SET_LOOKBACK: int = 3
# Конкретный по номеру рабочий подход в среднем ниже остальных подходов той
# же тренировки минимум на столько — за последние WEAK_SET_LOOKBACK тренировок.
VOLUME_DROP_LOOKBACK: int = 3
MINIMAL_REST_MARGIN_DAYS: int = 1
# Промежуток между тренировками не превышает MIN_REST_DAYS + этот запас —
# считается "на грани минимального отдыха".
CONSISTENT_STREAK_DAYS: int = 21

# --- Аномалии ввода (app/domain/anomalies.py) — пакет #4 --------------------------

ANOMALY_LARGE_VALUE_THRESHOLD: int = 50
# Любое число в подходе строго больше этого — повод переспросить, вне
# зависимости от истории. Ниже жёсткого предела ввода (parsing.MAX_REPS=100).
ANOMALY_JUMP_MULTIPLIER: float = 2.0
# Среднее рабочих подходов сейчас минимум во столько раз выше среднего
# прошлой тренировки этого же блока — повод переспросить. Именно среднее
# рабочих подходов (не объём и не максимум) — это та же метрика, на
# которой уже построена сама формула прогрессии (recalculate_target), и
# единственная из трёх, что остаётся сравнимой между тренировками с разным
# числом подходов (объём при большем числе подходов растёт тривиально).
