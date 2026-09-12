from collections.abc import Sequence
from enum import StrEnum


class ElectiveType(StrEnum):
    """4 самостоятельных формата факультативной нагрузки — вне плана,
    идут в статистику/объём, но не в прогрессию целей (не участвуют в
    recalculate_target, не привязаны к WorkoutSet/сету из 12). Отдельная
    сущность от "доп. упражнений на отдыхе" между блоками A/B живой
    тренировки (app/bot/handlers/workout.py, OPTIONAL_EXERCISE_*) —
    те приседания/выпады, не вращаются в цикле, не ограничены неделей."""

    MAX_REPS_LADDER = "max_reps_ladder"
    W_LADDER = "w_ladder"
    THREE_MINUTES = "three_minutes"
    VOLUME_TARGET = "volume_target"


# --- 1. Подтягивания на максимум --------------------------------------------------

MAX_REPS_LADDER_SETS: int = 4
# Между подходом 1→2, 2→3, 3→4 — отдых убывает, не константа.
MAX_REPS_LADDER_REST_SECONDS: tuple[int, int, int] = (180, 120, 60)

# --- 2. Подтягивания W -------------------------------------------------------------

# Прописана справочно (текст подсказки) — реально выполненное количество на
# каждом подходе вводится пользователем, не проверяется на точное совпадение
# с лесенкой (человек может не дотянуть до цели подхода, это не аномалия).
W_LADDER: tuple[int, ...] = (5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5)
W_LADDER_REST_SECONDS: int = 10

# --- 3. 3 минуты подтягиваний -------------------------------------------------------

THREE_MINUTES_WORK_SECONDS: int = 10
THREE_MINUTES_REST_SECONDS: int = 20
THREE_MINUTES_MAX_INTERVALS: int = 6

# --- 4. Подтягивания на объём --------------------------------------------------------

VOLUME_TARGET_MULTIPLIER: int = 5
VOLUME_TARGET_MIN_REPS_PER_SET: int = 6
VOLUME_TARGET_MAX_REPS_PER_SET: int = 10

# --- Ротация и лимит -----------------------------------------------------------------

# Было 1 (пакет #6), поднято до 2 по запросу продукта (issue #94) — то же
# скользящее 7-дневное окно (ELECTIVE_WEEK_WINDOW_DAYS), не календарная
# неделя, тот же принцип, что и period="week" лидерборда (issue #74).
ELECTIVE_MAX_PER_WEEK: int = 2
ELECTIVE_WEEK_WINDOW_DAYS: int = 7


def available_elective_types(history: Sequence[ElectiveType]) -> frozenset[ElectiveType]:
    """Цикл без повтора из 4 (пакет #6), свободный порядок выбора — не
    "какой следующий", а "какие ещё не сделаны в текущем незавершённом
    цикле". history — типы уже выполненных факультативов в хронологическом
    порядке (старые первыми).

    Последние (len(history) % 4) записей — то, что уже сделано в текущем
    цикле; остальные (len(history) % 4 не может быть 4) типы доступны.
    Как только очередной цикл из 4 завершается (остаток снова 0) — доступны
    сразу все четыре. Никогда не возвращает пустое множество — ротация
    сама по себе не блокирует выбор целиком, это может только недельный
    лимит (см. is_elective_allowed)."""
    cycle_length = len(ElectiveType)
    remainder = len(history) % cycle_length
    done_in_current_cycle = set(history[-remainder:]) if remainder else set()
    return frozenset(ElectiveType) - done_in_current_cycle


def is_elective_allowed(entries_in_last_week: int) -> bool:
    return entries_in_last_week < ELECTIVE_MAX_PER_WEEK


def volume_target_goal(current_volume_block_target: int) -> int:
    """Целевой суммарный объём факультатива №4 — текущая плановая цель
    блока на объём × 5 (план 10 -> цель 50)."""
    return current_volume_block_target * VOLUME_TARGET_MULTIPLIER
