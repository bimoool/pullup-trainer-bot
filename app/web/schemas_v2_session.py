"""Pydantic-схемы для живой (server-driven) сессии и каскада прогрессии
(issue #165, продолжение волны 3 — "сессия — live", разделы 10.7-10.9/11/12
docs/plan-and-specs.md) — отдельный файл от app/web/schemas_v2.py (тот уже
большой, см. план задачи), но переиспользует оттуда SetLogResponse/
SessionProgressionResponse/SetLogInputSchema, не дублирует их формы."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.live_engine import CLIENT_EVENT_TYPES
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
    # issue #306: 2 — сессия исполняется Live Engine v2 (новый клиент шлёт явно); без поля — движок v1
    # (старые закэшированные бандлы Mini App продолжают работать, MIGRATION_V2 §6).
    engine_version: int = Field(default=1, ge=1, le=2)

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


# --- POST /sessions/live/{id}/phase/back -------------------------------------------------


class LiveSessionPhaseBackRequest(BaseModel):
    """#292: expected_phase_index — фаза, которую клиент считает текущей.
    Не совпал — 409 (в отличие от phase/next: «назад» не должен молча
    применяться к состоянию, которого клиент не видел)."""

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
    # issue #307 (R3, TRAINING_SESSION_V2 §8): активная длительность от движка (паузы исключены).
    # Нет — сервер берёт стенные часы старт → завершение в окне [1 мин, 6 ч].
    active_elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)

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


class LiveSetLogResponse(SetLogResponse):
    """#292: SetLogResponse + set_index — ключ, под которым клиент
    перезаписывает переоткрытый («назад») подход, не создавая новую строку."""

    set_index: int | None = None


class LiveSessionBlockResponse(BaseModel):
    order_index: int
    exercise_id: int | None
    complex_id: int | None
    targets: list[LiveSetTargetResponse]
    set_logs: list["LiveSetLogResponse"]
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
    # issue #306: 1 — движок v1 (phase/next…); 2 — Live Engine v2 (POST …/events), см. engine.
    engine_version: int | None = None
    engine: "LiveEngineView | None" = None
    # Отменена (T5): сессия хранится архивом, не идёт и не засчитана.
    engine_status: str | None = None


class LiveEngineView(BaseModel):
    """issue #306 (LIVE_ENGINE_V2 §1–§2, §6): состояние движка v2 — единственный источник отсчёта.
    Клиент берёт server_offset = server_time_ms − (момент ответа по своим часам) и рисует
    deadline − (now + offset); своих констант длительности и переходов у него нет. timeline — аудио-хуки
    текущей и следующей фазы (прошедшие клиент не воспроизводит, P4)."""

    plan: dict
    state: dict
    server_time_ms: int
    timeline: list[dict]


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


# --- POST /sessions/live/{id}/events (issue #306) -----------------------------------------


class LiveEngineEventRequest(BaseModel):
    """Одно событие движка v2 (имена — LIVE_ENGINE_V2 §3). client_event_id — ключ идемпотентности
    (повтор — no-op, 200); client_at — недоверенное время клиента (сервер зажимает в [last_at, now])."""

    client_event_id: UUID
    type: str = Field(min_length=1, max_length=32)
    payload: dict = Field(default_factory=dict)
    client_at: datetime | None = None

    @field_validator("type")
    @classmethod
    def _client_event_type(cls, value: str) -> str:
        # start/deadline — только серверные события; чужие имена контракта не принимаются.
        if value not in CLIENT_EVENT_TYPES:
            raise ValueError(f"неизвестное событие клиента: {value}")
        return value

    @field_validator("payload")
    @classmethod
    def _small_payload(cls, value: dict) -> dict:
        if len(str(value)) > 4000:
            raise ValueError("payload слишком большой")
        return value


class LiveEngineEventsRequest(BaseModel):
    """Офлайн-очередь досылается одним запросом в порядке возникновения (C4)."""

    events: list[LiveEngineEventRequest] = Field(default_factory=list, max_length=200)


class LiveEngineEventResult(BaseModel):
    client_event_id: UUID
    outcome: str  # applied | noop | duplicate


class LiveEngineEventsResponse(LiveSessionCompleteResponse):
    event_results: list[LiveEngineEventResult]


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
    # issue #307 (TRAINING_SESSION_V2 §4): длительность (секунды; null — неизвестна), тип и дистанция
    # внешней активности. Что из этого разрешено у сессии — editable_fields в ответе (ED1).
    duration_seconds: int | None = Field(default=None, ge=1)
    activity_type: str | None = None
    distance_meters: int | None = Field(default=None, ge=1)

    @field_validator("comment")
    @classmethod
    def _blank_comment_is_none(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class SessionCloneRequest(BaseModel):
    performed_on: date | None = None  # по умолчанию — сегодня (локальный день)


LiveSessionResponse.model_rebuild()
LiveSessionCompleteResponse.model_rebuild()
LiveEngineEventsResponse.model_rebuild()
