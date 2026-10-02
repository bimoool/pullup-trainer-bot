"""Pydantic-схемы для живой (server-driven) сессии и каскада прогрессии
(issue #165, продолжение волны 3 — "сессия — live", разделы 10.7-10.9/11/12
docs/plan-and-specs.md) — отдельный файл от app/web/schemas_v2.py (тот уже
большой, см. план задачи), но переиспользует оттуда SetLogResponse/
SessionProgressionResponse/SetLogInputSchema, не дублирует их формы."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.web.schemas_v2 import (
    IntervalConfigResponse,
    SessionProgressionResponse,
    SetLogInputSchema,
    SetLogResponse,
)

# --- POST /sessions/live -----------------------------------------------------------------


class LiveSessionStartRequest(BaseModel):
    """client_session_id генерируется КЛИЕНТОМ до первого запроса к серверу
    (офлайн-контракт, раздел 12) — идемпотентность старта живой сессии:
    повтор с тем же UUID возвращает уже созданную сессию, не плодит вторую."""

    client_session_id: UUID
    plan_item_ids: list[int] = Field(default_factory=list)
    # «Начать» на Workout Detail: свободная сессия из снимка своей тренировки,
    # взаимоисключающе с plan_item_ids.
    workout_id: int | None = None

    @model_validator(mode="after")
    def _workout_xor_plan_items(self) -> "LiveSessionStartRequest":
        if self.workout_id is not None and self.plan_item_ids:
            raise ValueError("workout_id и plan_item_ids взаимоисключающи")
        return self


# --- POST /sessions/live/{id}/phase/next -------------------------------------------------


class LiveSessionPhaseNextRequest(BaseModel):
    """expected_phase_index сравнивается с серверным phase_index — совпал —
    переход, иначе (клиент отстал или обогнал) сервер молча отдаёт текущее
    состояние, БЕЗ ошибки (см. app.services.live_session.advance_phase)."""

    expected_phase_index: int


# --- POST /sessions/live/{id}/blocks/start | /blocks/finish -------------------------------


class LiveSessionBlockRequest(BaseModel):
    """expected_block_index — блок, который клиент считает текущим. Не
    совпал (клиент отстал/обогнал, двойной клик) — сервер молча отдаёт
    текущее состояние без изменений, как и phase/next."""

    expected_block_index: int


# --- POST /sessions/live/{id}/sets:batch --------------------------------------------------


class LiveSetBatchEntry(BaseModel):
    """set_index — стабильный ключ идемпотентности подхода В СЕССИИ ЦЕЛИКОМ
    (клиент назначает), не set_number (тот назначает сервер внутри блока
    при первой вставке, см. TrainingSessionRepository.upsert_set_logs_batch).
    client_ts принимается, но НЕ персистится нигде на этой волне — задел на
    будущее (упорядочивание/отладка офлайн-очереди), не молчаливая заглушка:
    поле явно объявлено необязательным и не участвует в апсерте."""

    set_index: int
    exercise_id: int
    value: Decimal
    effort: Decimal | None = None
    note: str | None = None
    client_ts: datetime | None = None
    # R1: блок, для которого записан подход (дубли упражнения в тренировке);
    # None — старый клиент, берётся текущий блок сессии.
    block_index: int | None = None
    # issue #264: подход сверх плана («+ Ещё подход»); не цель, не в прогрессии.
    is_extra: bool = False


class LiveSetBatchRequest(BaseModel):
    sets: list[LiveSetBatchEntry]


# --- POST /sessions/live/{id}/complete ----------------------------------------------------


class LiveSessionCompleteRequest(BaseModel):
    abandoned: bool = False
    # Оценка тренировки целиком (необязательно); на прогрессию не влияет.
    effort: Decimal | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def _blank_comment_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


# --- Общий ответ по живой сессии -----------------------------------------------------------


class LiveSessionPhaseResponse(BaseModel):
    name: str
    ends_at: datetime | None


class LiveSetTargetResponse(BaseModel):
    set_number: int
    metric_type: str
    value: str
    unit: str


class LiveSessionBlockResponse(BaseModel):
    order_index: int
    exercise_id: int | None
    complex_id: int | None
    targets: list[LiveSetTargetResponse]
    set_logs: list[SetLogResponse]
    # R1: идентичность блока берётся из ЗАМОРОЖЕННОГО снимка (позиционно), не
    # из изменяемого ComplexItem. None у legacy/STEP-блоков (без снимка).
    protocol_type: str | None = None
    exercise_name: str | None = None
    rest_seconds: int | None = None
    started_at: datetime | None = None
    interval_config: IntervalConfigResponse | None = None
    # Phase B2 gate fix (issue #215) — SessionBlock.result (Phase B1), для
    # interval — полный контракт {type, started_at, completed_at,
    # planned_duration_seconds, actual_duration_seconds, completed_cycles}.
    # None для standard STANDARD/REPS/MAX блоков (result там не пишется).
    result: dict | None = None


class IntervalStateResponse(BaseModel):
    """Phase B1 (issue #215): server-authoritative interval timing state —
    вычисляется на лету по performed_at + protocol, не персистится в БД.
    Только для interval workouts, None для standard STEP/manual path."""

    execution_started_at: datetime
    total_end_at: datetime
    phase: str  # get_ready|work|rest|done
    phase_ends_at: datetime | None
    total_duration_seconds: int
    work_seconds: int
    rest_seconds: int
    completed_cycles: int


class LiveSessionResponse(BaseModel):
    id: int
    client_session_id: UUID
    status: str
    phase: LiveSessionPhaseResponse
    phase_index: int
    current_block_index: int
    current_set_number: int
    blocks: list[LiveSessionBlockResponse]
    server_time: datetime  # Phase B1: UTC timestamp генерации ответа
    interval: IntervalStateResponse | None  # R1: ТЕКУЩИЙ начатый interval-блок, иначе None
    # R1: сессия стоит перед ещё не начатым блоком — фронт показывает
    # interstitial "Готово ✓ / Следующее упражнение / Начать".
    awaiting_block_start: bool = False
    # Phase B2 gate fix (issue #215) — найдено живым reload-прогоном:
    # /sessions/live/active не резолвил title вообще, App.tsx's resumedSession
    # ветка передавала PlanSessionFlow пустую строку — "3 минуты подтягиваний"
    # исчезал после reload (был тем же пробелом и для standard-сессий,
    # раньше не был явно виден/потребован). Опционально — None, если сессия
    # не resolvable (тот же честный пробел, что _resolve_session_titles
    # уже применяет для Журнала).
    title: str | None = None


class LiveSessionCompleteResponse(LiveSessionResponse):
    """См. SessionResponse.progression_result/progression_skipped_reason в
    schemas_v2.py — та же пара "результат или явная причина пропуска", не
    молчаливое отсутствие."""

    progression_result: SessionProgressionResponse | None
    progression_skipped_reason: str | None


class LiveSessionActiveResponse(BaseModel):
    """None — нет незавершённой сессии (обычный случай, не ошибка) — GET
    /sessions/live/active для баннера "продолжить тренировку" (10.8)."""

    session: LiveSessionResponse | None


# --- Каскад прогрессии ---------------------------------------------------------------------


class ProgressionPreviewRequest(BaseModel):
    """block_a/block_b оба None — предпросмотр БЕЗ правок (полезно как
    no-op база для сверки, но основной сценарий — хотя бы одно поле
    заполнено запросом правки исторической сессии, раздел 10.6)."""

    edited_session_id: int
    block_a: list[SetLogInputSchema] | None = None
    block_b: list[SetLogInputSchema] | None = None


class PlanItemDeltaResponse(BaseModel):
    plan_item_id: int | None
    exercise: str
    before: int
    after: int


class ProgressionPreviewResponse(BaseModel):
    """Пустой deltas — валидный ответ (правка ничего не меняет в итоговой
    цели), не ошибка — см. app.services.progression_cascade.preview."""

    deltas: list[PlanItemDeltaResponse]


# --- PATCH /sessions/{id} и POST /sessions/{id}/clone (#262) ------------------------------


class SessionSetEditSchema(BaseModel):
    """Подход блока (order_index + set_number) — value/effort/note заменяются
    целиком (effort/note = null очищают). Новые подходы добавить нельзя."""

    block_index: int = Field(ge=0)
    set_number: int = Field(ge=1)
    value: Decimal = Field(ge=0, le=Decimal("99999.99"))
    effort: Decimal | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _blank_note_is_none(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class SessionEditRequest(BaseModel):
    """Незаданные поля не меняются; effort/comment = null очищают.
    performed_on — ЛОКАЛЬНЫЙ день пользователя (не в будущем), время суток
    сохраняется."""

    performed_on: date | None = None
    effort: Decimal | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    sets: list[SessionSetEditSchema] = Field(default_factory=list, max_length=200)

    @field_validator("comment")
    @classmethod
    def _blank_comment_is_none(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class SessionCloneRequest(BaseModel):
    performed_on: date | None = None  # по умолчанию — сегодня (локальный день)
