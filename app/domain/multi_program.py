from datetime import date, timedelta
from enum import StrEnum


class MetricType(StrEnum):
    """Единица измерения подхода/упражнения (волна 1 многокурсовой
    платформы, issue #160) — то, что раньше в pull-up-специфичной схеме
    было неявным (working_reps/max_reps всегда "повторения"), здесь
    становится явным полем: разные Exercise измеряются по-разному
    (время в планке, вес в жиме, угол в статике на кольцах)."""

    REPS = "reps"
    TIME = "time"
    WEIGHT = "weight"
    ANGLE = "angle"
    DISTANCE = "distance"


class ProgramStructureType(StrEnum):
    """Как Program разворачивается во времени. RECURRING — повторяющаяся
    недельная матрица (как текущая схема подтягиваний), FIXED —
    фиксированное число недель с заранее известным концом, SINGLE_LESSON —
    разовое занятие, не растянутое на недели."""

    RECURRING = "recurring"
    FIXED = "fixed"
    SINGLE_LESSON = "single_lesson"


class WeekPhase(StrEnum):
    """Фаза недели тренировочного плана — та же линза периодизации, что
    уже применяется в спортивной науке (накопление/восстановление/пик),
    не специфична для подтягиваний."""

    BASE = "base"
    REST = "rest"
    PEAK = "peak"


class SessionSource(StrEnum):
    """Происхождение TrainingSession — тот же смысл, что у
    app.db.models.Workout.is_free_entry/participates_in_cascade в старой
    схеме подтягиваний, но явным полем вместо двух булевых флагов.

    ELECTIVE подтверждено Кириллом в issue #160 (поправка к документу) —
    закладывается как валидное значение уже в волне 1, само слияние
    app.db.models.ElectiveWorkout в TrainingSession — задача волны 2, не
    делается здесь."""

    PLAN = "plan"
    FREEFORM = "freeform"
    BACKDATED = "backdated"
    ELECTIVE = "elective"


# --- Номер недели плана (Checkpoint 1, issue #188) ---------------------------------------
#
# TrainingPlan не имеет отдельной start_date — по прямому указанию
# (не добавлять новую колонку ради этого) номер недели считается от даты
# TrainingPlan.created_at, с началом недели в понедельник (явно
# зафиксировано, не оставлено неявным допущением ORM/локали). Чистая
# функция по date, не datetime — время суток не участвует в расчёте.


def _monday_on_or_before(day: date) -> date:
    return day - timedelta(days=day.weekday())  # Monday.weekday() == 0


def plan_week_number(plan_created_at: date, today: date) -> int:
    """Номер календарной недели плана (1-based), считая от недели, в
    которую попадает plan_created_at. Недели, наступившие ДО создания
    плана, не бывает — today раньше plan_created_at не ожидается вызывающим
    кодом, но при равных датах корректно даёт 1."""
    origin_monday = _monday_on_or_before(plan_created_at)
    current_monday = _monday_on_or_before(today)
    return (current_monday - origin_monday).days // 7 + 1


def plan_week_start_date(plan_created_at: date, week_number: int) -> date:
    """Дата понедельника, с которой начинается указанная неделя плана —
    обратная функция к plan_week_number, нужна при создании строки PlanWeek
    (её start_date)."""
    origin_monday = _monday_on_or_before(plan_created_at)
    return origin_monday + timedelta(weeks=week_number - 1)
