from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.constants import EquipmentType, ExerciseType, VolumeGrowthReason


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

    @property
    def best_set(self) -> int:
        """Лучший фактический подход блока — рабочий или на максимум. Тот же
        смысл, что _BEST_SET_EXPR в app.db.repositories.leaderboard (issue
        #82: метрика "Максимум" графика прогресса), но в Python поверх уже
        загруженных объектов, а не как raw SQL — здесь запись уже в памяти,
        SQL-агрегация по всем пользователям разом не нужна."""
        return max((*self.working_reps, self.max_reps))


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
    # Ссылка на личный список резин пользователя (только для BAND) —
    # непрозрачный идентификатор для сравнения "тот же снаряд", устойчивый
    # к тому, что kg может быть неизвестен или отличаться (см.
    # app/domain/reports.py::current_equipment_progress). Для WEIGHT/
    # BODYWEIGHT/AUSTRALIAN всегда None.
    equipment_item_id: int | None = None
    transition_failed: bool = False
    # Иерархия роста блока на объём (ревизия формулы прогрессии, части 2-4)
    # — только для блока A; у силового блока подходы фиксированы, эти поля
    # у него всегда None/False. work_sets_before/after — число рабочих
    # подходов ДО/ПОСЛЕ этой тренировки (растёт по правилу застоя/потолка,
    # см. app.domain.progression.recalculate_volume_block). is_deload —
    # ежемесячная разгрузочная тренировка (часть 4): не участвует в
    # пересчёте прогрессии, только в статистике/объёме.
    work_sets_before: int | None = None
    work_sets_after: int | None = None
    is_deload: bool = False
    # Почему выросли рабочие подходы ЭТОЙ тренировки (issue #79) — застой
    # или упор в потолок повторений (см. app.domain.progression.
    # recalculate_volume_block). None, если work_sets не выросли за эту
    # тренировку (в т.ч. для work_sets_after is None/для блока Б).
    work_sets_growth_reason: VolumeGrowthReason | None = None


@dataclass(frozen=True)
class WorkoutRecord:
    """Историческая запись тренировки — единица данных для каскадного
    пересчёта при редактировании прошлой тренировки, а также для отчётов
    и экспорта (workout_set_id/exercise_type нужны там, чтобы группировать
    по циклам и — на будущее — по направлению тренировок)."""

    performed_at: datetime
    block_a: BlockAssignment
    block_b: BlockAssignment
    comment: str | None = None
    workout_set_id: int | None = None
    exercise_type: ExerciseType | None = None
