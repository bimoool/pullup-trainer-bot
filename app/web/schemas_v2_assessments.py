"""Схемы /api/v2/assessments (Tests hub, #260). Значения — строками (Decimal), как в
остальных v2-ответах; фронт форматирует."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

_VALUE = Field(gt=0, le=Decimal(9999), decimal_places=2)
_NOTE = Field(default=None, max_length=500)


class AssessmentResultCreate(BaseModel):
    performed_on: date
    value: Decimal = _VALUE
    note: str | None = _NOTE


class AssessmentResultUpdate(BaseModel):
    """Частичная правка: переданные поля меняются, note=null очищает заметку."""

    performed_on: date | None = None
    value: Decimal | None = Field(default=None, gt=0, le=Decimal(9999), decimal_places=2)
    note: str | None = _NOTE


class AssessmentResultResponse(BaseModel):
    id: int
    protocol_id: int
    performed_on: date  # локальная дата пользователя
    value: str
    unit: str
    note: str | None = None


class AssessmentProtocolResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    metric_type: str
    unit: str
    last_result: AssessmentResultResponse | None = None
    results_count: int
    trend: list[str]  # значения от старых к новым (последние 12), для мини-графика


class AssessmentsListResponse(BaseModel):
    protocols: list[AssessmentProtocolResponse]


class AssessmentDetailResponse(BaseModel):
    protocol: AssessmentProtocolResponse
    results: list[AssessmentResultResponse]  # новые первыми


class PeerCohortResponse(BaseModel):
    level: str  # gender_age | gender | all
    label: str  # «Мужчины 30–39 лет» / «Женщины» / «Все пользователи»
    size_bucket: str  # «20–49» / «50–99» / «100+» — грубо, не точное число


class PeerNextTargetResponse(BaseModel):
    percentile: int
    value: str


class PeerInsightsResponse(BaseModel):
    """Peer Insights (#276): только агрегаты. status: ok | insufficient | no_result; числовые
    поля заполнены только при ok, чужих id и значений в ответе нет."""

    status: str
    min_cohort_size: int
    unit: str
    own_value: str | None = None
    cohort: PeerCohortResponse | None = None
    percentile: int | None = None  # доля когорты, которую обходит ваш результат (1..99)
    median: str | None = None
    next_target: PeerNextTargetResponse | None = None
