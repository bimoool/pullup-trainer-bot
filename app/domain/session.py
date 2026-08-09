from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.constants import EquipmentType


@dataclass(frozen=True)
class BlockLog:
    """Фактически введённые повторения по одному блоку одной тренировки.

    working_reps — рабочие подходы в порядке выполнения (3 для объёмного
    блока, 4 для силового). max_reps — отдельный последний подход "на
    максимум", не входит в working_reps.
    """

    working_reps: tuple[int, ...]
    max_reps: int

    @property
    def volume(self) -> int:
        """Сумма всех повторений блока: рабочие подходы + подход на максимум."""
        return sum(self.working_reps) + self.max_reps


@dataclass(frozen=True)
class WorkoutLog:
    """Ввод одной тренировки целиком — оба блока плюс метаданные."""

    performed_at: datetime
    block_a: BlockLog
    block_b: BlockLog
    comment: str | None = None


@dataclass(frozen=True)
class BlockAssignment:
    """Блок с зафиксированным контекстом прогрессии — то, что нужно хранить
    в истории, чтобы потом каскадно пересчитать цепочку тренировок.
    """

    log: BlockLog
    target_before: int
    target_after: int
    equipment_changed: bool
    equipment_type: EquipmentType
    equipment_value: Decimal | None = None
    transition_failed: bool = False


@dataclass(frozen=True)
class WorkoutRecord:
    """Историческая запись тренировки — единица данных для каскадного
    пересчёта при редактировании прошлой тренировки."""

    performed_at: datetime
    block_a: BlockAssignment
    block_b: BlockAssignment
    comment: str | None = None
