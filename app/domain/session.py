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

    reported_volume (issue #88) — итог за тренировку, введённый напрямую,
    БЕЗ раскладки по подходам (сценарий бэкдейта блока Б: "не помню, сколько
    было в каждом подходе, но общее число знаю"). Когда задан, ПЕРЕОПРЕДЕЛЯЕТ
    volume — working_reps в этом случае всегда () (раскладки просто нет), а
    max_reps — либо 0 (максимум не зафиксирован), либо реально введённый
    лучший подход. Ключевая причина завести отдельное поле, а не втиснуть
    итог в max_reps/working_reps: max_reps/best_set — это метрика "лучший
    ОДИН подход" (см. best_set ниже, и app.db.repositories.leaderboard —
    MAX_REPS/MAX_WEIGHT читают их напрямую), а итог за тренировку — это
    СУММА за много подходов; подставить туда одно большое число значило бы
    воспроизвести ровно тот баг, который эта фича чинит (см. issue #88:
    "60" за всю тренировку записывалось как настоящий максимум за подход)."""

    working_reps: tuple[int, ...]
    max_reps: int
    reported_volume: int | None = None

    @property
    def volume(self) -> int:
        """Сумма всех повторений блока: рабочие подходы + подход на
        максимум — если только reported_volume не задан явно (см. его
        докстринг), тогда используется он, а не пересчёт из working_reps/
        max_reps (при reported_volume working_reps пуст, а max_reps может
        быть 0 — пересчёт дал бы 0 вместо реального итога)."""
        if self.reported_volume is not None:
            return self.reported_volume
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
    # Чётная ("тяжёлая") тренировка блока Б в рамках сета из 12 (issue #97) —
    # только для блока Б, у блока A всегда False. Фиксированные повторения в
    # подходе, повышенный вес; не участвует в пересчёте прогрессии (target_
    # before/after равны, как и у is_deload выше) — только в статистике/
    # объёме/тренде app.domain.reports.epley_progress (там нормализуется
    # формулой Эпли наравне с обычными тренировками, отдельного случая не
    # требует).
    is_heavy: bool = False
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
    # Официальная тренировка основной программы (см. Workout.participates_in_
    # cascade) vs бэкдейт/свободный ввод (issue #88/#94). Дефолт True — так
    # исторически ведёт себя большинство тренировок, и не ломает конструкторы
    # WorkoutRecord в существующих тестах/коде, которым это различие
    # безразлично. Используется для формулы Эпли (app.domain.reports.
    # epley_progress, issue #96) — "прошлая"/"первая" тренировка блока Б для
    # % прироста берётся только среди official-записей, бэкдейт/свободные
    # видны на графике факта, но не становятся анкорами для сравнения.
    participates_in_cascade: bool = True
