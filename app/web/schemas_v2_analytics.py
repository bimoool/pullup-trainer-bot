"""Схемы GET /api/v2/analytics/training (REBUILD-1, R3). Числа отдаются
строками (Decimal), как и остальные v2-ответы; фронт форматирует."""

from datetime import date, datetime

from pydantic import BaseModel


class AnalyticsWeekResponse(BaseModel):
    week_start: date  # понедельник (локальная календарная неделя пользователя)
    sessions: int
    active_days: int


class AnalyticsActivityResponse(BaseModel):
    sessions_last_30_days: int
    active_days_last_30_days: int
    weeks: list[AnalyticsWeekResponse]


class AnalyticsPointResponse(BaseModel):
    at: datetime
    value: str
    best: str | None = None
    cumulative_best: str | None = None
    is_new_pb: bool | None = None
    cycles: int | None = None


class AnalyticsPanelResponse(BaseModel):
    """Одна пара (упражнение, протокол). Поля протокол-специфичны: у прочих
    протоколов они None (не 0 — "нет метрики", не "ноль")."""

    protocol_type: str
    session_count: int
    unit: str | None = None
    total_reps: str | None = None
    total_work_seconds: str | None = None
    set_count: int | None = None
    best_set: str | None = None
    attempt_count: int | None = None
    best: str | None = None
    actual_duration_seconds: int | None = None
    cycles: int | None = None
    points: list[AnalyticsPointResponse]
    points_total: int


class AnalyticsExerciseResponse(BaseModel):
    exercise_id: int
    exercise_name: str
    panels: list[AnalyticsPanelResponse]


class AnalyticsMetricWeekResponse(BaseModel):
    week_start: date
    workouts: int
    minutes: int


class AnalyticsMetricsResponse(BaseModel):
    """Недельные ряды обеих метрик за [date_from, date_to] (локальные даты
    пользователя). without_duration — тренировки диапазона без валидной
    длительности (в минуты не входят)."""

    date_from: date
    date_to: date
    weeks: list[AnalyticsMetricWeekResponse]
    total_workouts: int
    total_minutes: int
    without_duration: int


class AnalyticsDistributionSubResponse(BaseModel):
    name: str
    workouts: float
    minutes: float


class AnalyticsDistributionCategoryResponse(BaseModel):
    name: str
    workouts: float
    minutes: float
    subcategories: list[AnalyticsDistributionSubResponse]


class AnalyticsDistributionResponse(BaseModel):
    """Распределение тренировок/минут диапазона по категориям (#274). Смешанная
    сессия делится по долям блоков (дробные значения), итог по тренировкам =
    число тренировок диапазона. Категории каталога присутствуют с нулями."""

    categories: list[AnalyticsDistributionCategoryResponse]
    total_workouts: float
    total_minutes: float


class TrainingAnalyticsResponse(BaseModel):
    timezone: str
    metrics: AnalyticsMetricsResponse
    distribution: AnalyticsDistributionResponse
    activity: AnalyticsActivityResponse
    exercises: list[AnalyticsExerciseResponse]
