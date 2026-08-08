from dataclasses import dataclass
from enum import StrEnum


class Equipment(StrEnum):
    """Тип снаряда блока — определяет, как выглядит смена снаряда."""

    BAND = "band"
    WEIGHT = "weight"


class Branch(StrEnum):
    """Ветка тренировок пользователя, определяется по итогам замера."""

    BAND = "band"
    ASSISTED = "assisted"


@dataclass(frozen=True)
class BlockConfig:
    """Параметры прогрессии одного тренировочного блока."""

    equipment: Equipment
    base_target: int
    work_sets: int
    max_step: int
    coef: float
    change_at: int


BLOCK_A = BlockConfig(
    equipment=Equipment.BAND, base_target=15, work_sets=3, max_step=3, coef=0.5, change_at=20,
)
BLOCK_B = BlockConfig(
    equipment=Equipment.WEIGHT, base_target=3, work_sets=4, max_step=2, coef=0.5, change_at=8,
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
BACKDATE_MAX_DAYS: int = 7
TRIAL_DAYS: int = 14
