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
