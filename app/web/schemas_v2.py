"""Pydantic-схемы для app/web/routes_v2.py (issue #165, волна 3) — новая
многокурсовая схема (app/db/models_program.py), параллельно app/web/schemas.py
(старая схема подтягиваний), не расширяет его: поля/формы здесь принципиально
другие (Exercise/TrainingSession вместо Block/Workout)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --- Каталог (read-only на этой волне) ---------------------------------------------


class ProgramResponse(BaseModel):
    id: int
    name: str
    goal: str
    structure_type: str
    category: str | None
    progression_strategy_type: str | None


class ProgramListResponse(BaseModel):
    programs: list[ProgramResponse]


class ExerciseResponse(BaseModel):
    """Checkpoint 3A (issue #196) — минимальная Exercise Library без UI.
    Только поля, реально существующие в Exercise model (не equipment/
    difficulty/duration/muscles — этих полей в схеме волны 1 нет)."""

    id: int
    name: str
    metric_type: str
    category: str
    subcategory: str | None


class ExerciseListResponse(BaseModel):
    exercises: list[ExerciseResponse]


class ExerciseCreateRequest(BaseModel):
    """Phase C1 (issue #188) — минимальный запрос для пользовательского
    Exercise (Workout Builder foundation). Только name — global uniqueness
    намеренно не проверяется (пользовательские "Подтягивания" от разных
    владельцев и от system должны сосуществовать)."""

    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Название не может быть пустым")
        return trimmed


class WorkoutResponse(BaseModel):
    """Phase C2 (issue #188) — минимальный ответ для экрана "Мои
    тренировки"/detail. title — продуктовый термин (Complex.name в БД, не
    переименовано в схеме хранения — issue #188 прямо просит не делать
    искусственный rename поля)."""

    id: int
    title: str
    source_type: str
    owner_user_id: int | None


class WorkoutListResponse(BaseModel):
    workouts: list[WorkoutResponse]


class WorkoutCreateRequest(BaseModel):
    """Global uniqueness намеренно не проверяется — тот же принцип, что
    ExerciseCreateRequest."""

    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Название не может быть пустым")
        return trimmed


class WorkoutUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Название не может быть пустым")
        return trimmed


# --- План пользователя --------------------------------------------------------------


class ProgramInclusionResponse(BaseModel):
    id: int
    program_id: int
    program_name: str
    is_active: bool
    started_at: datetime
    expires_at: datetime | None
    snapshot: dict
    progression_state: dict


class PlanItemResponse(BaseModel):
    id: int
    exercise_id: int
    complex_id: int | None
    count_per_week: int
    day_of_week: int | None
    week_phase: str | None
    program_inclusion_id: int | None
    plan_week_id: int | None
    # Phase B2 gate fix (issue #215) — Workout title (Complex.name) для
    # complex-based PlanItem (interval/будущие Workout-based карточки).
    # Без этого DashboardScreen.tsx::exerciseLabel не могла показать
    # реальное название ("3 минуты подтягиваний") — только "Комплекс"
    # (технический fallback) или, что хуже, имя несвязанного exercise_id.
    # Опционально, None для call site'ов, не резолвящих его (не всем
    # нужно на каждый PlanItem-запрос — только листингу на "Планах").
    complex_name: str | None = None


class PlanWeekResponse(BaseModel):
    """issue #193 — PlanWeek не отдавалась в GET /api/v2/plan вообще, хотя
    Checkpoint 1/1.1 (issue #188) уже материализует её и проставляет
    PlanItem.plan_week_id. Без этого поля фронтенд не мог сгруппировать
    plan_items по РЕАЛЬНОЙ неделе (только по week_phase — общее свойство
    строки плана, не то же самое, что конкретная календарная неделя)."""

    id: int
    week_number: int
    start_date: date
    phase: str


class TrainingPlanResponse(BaseModel):
    id: int
    created_at: datetime
    program_inclusions: list[ProgramInclusionResponse]
    plan_items: list[PlanItemResponse]
    plan_weeks: list[PlanWeekResponse]


class PlanResponse(BaseModel):
    """None, если TrainingPlan для пользователя ещё не создан — GET не
    создаёт его молча (побочный эффект на чтении), см. план issue #165:
    план создаётся лениво первым POST /program-inclusions или
    POST /plan-items."""

    plan: TrainingPlanResponse | None


class PlanItemListResponse(BaseModel):
    items: list[PlanItemResponse]


# --- POST /program-inclusions --------------------------------------------------------


class ProgramInclusionCreateRequest(BaseModel):
    program_id: int
    # Для STEP-стратегии — стартовые значения цепочки; None значит "с нуля",
    # как у нового пользователя без замера (config.block_a/b.base_target).
    # Интеграция с AssessmentResult — вне охвата этой волны (план issue #165,
    # открытый вопрос, подтверждено Кириллом).
    initial_target_a: int | None = None
    initial_target_b: int | None = None
    initial_volume_a: int = 0
    initial_volume_b: int = 0


# --- Сессии ---------------------------------------------------------------------------


class SetLogInputSchema(BaseModel):
    set_number: int
    metric_type: Literal["reps", "time", "weight", "angle", "distance"]
    value: Decimal
    unit: str
    is_max_set: bool = False
    effort: Decimal | None = None
    note: str | None = None


class SessionBlockInputSchema(BaseModel):
    sets: list[SetLogInputSchema]
    exercise_id: int | None = None
    complex_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "SessionBlockInputSchema":
        if (self.exercise_id is None) == (self.complex_id is None):
            raise ValueError("ровно одно из exercise_id/complex_id")
        if not self.sets:
            raise ValueError("sets не может быть пустым")
        return self


class SessionCreateRequest(BaseModel):
    source: Literal["plan", "freeform", "backdated", "elective"]
    performed_at: datetime
    blocks: list[SessionBlockInputSchema]
    program_inclusion_id: int | None = None
    effort: Decimal | None = None
    comment: str | None = None


class SetLogResponse(BaseModel):
    set_number: int
    is_max_set: bool
    metric_type: str
    value: str
    unit: str
    effort: str | None
    note: str | None


class SessionBlockResponse(BaseModel):
    order_index: int
    exercise_id: int | None
    complex_id: int | None
    set_logs: list[SetLogResponse]
    # Phase B2 gate fix (issue #215) — тот же result, что LiveSessionBlockResponse,
    # нужен Журналу для отображения завершённых interval-тренировок.
    result: dict | None = None


class BlockProgressionResponse(BaseModel):
    target_before: int
    target_after: int
    equipment_changed: bool


class SessionProgressionResponse(BaseModel):
    block_a: BlockProgressionResponse
    block_b: BlockProgressionResponse


class SessionResponse(BaseModel):
    id: int
    source: str
    status: str
    performed_at: datetime
    effort: str | None
    comment: str | None
    # Checkpoint 4C (issue #188) — резолвится на бэкенде через
    # SessionPlanItem -> PlanItem -> ProgramInclusion.program_name
    # (program-backed) или -> Exercise.name (manual), не пересчитывается на
    # фронте (раздел 5 задачи — не N+1 на фронте). None — сессия без
    # SessionPlanItem вообще (создана мимо create_live_session, до
    # Checkpoint 4A) либо чужого/удалённого PlanItem — честный пробел, не
    # выдуманное имя.
    title: str | None
    blocks: list[SessionBlockResponse]
    # None, если пересчёт прогрессии не применялся к этой сессии — вместе с
    # progression_skipped_reason объясняет ПОЧЕМУ (не молчаливое отсутствие,
    # см. CLAUDE.md о явных пробелах): "no_program_inclusion"/
    # "not_step_strategy"/"blocks_do_not_match_step_roles" либо None, если
    # пересчёт применился.
    progression_result: SessionProgressionResponse | None
    progression_skipped_reason: str | None


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


# --- Строки недельной матрицы (ручной ввод) -------------------------------------------


class PlanItemCreateRequest(BaseModel):
    count_per_week: int
    exercise_id: int | None = None
    complex_id: int | None = None
    # Checkpoint 3B (issue #197) требовал "невалидный day_of_week
    # отклоняется" — Worker B написал тест на это (test_create_plan_item_
    # with_invalid_day_of_week_is_rejected), но саму валидацию не добавил;
    # реальный прогон integration review поймал 200 OK на day_of_week=7,
    # где ожидался 422. Field(ge=0, le=6) — тот же диапазон, что
    # DashboardScreen.tsx::DAY_NAMES (0=понедельник..6=воскресенье).
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    week_phase: Literal["base", "rest", "peak"] | None = None
    plan_week_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "PlanItemCreateRequest":
        if (self.exercise_id is None) == (self.complex_id is None):
            raise ValueError("ровно одно из exercise_id/complex_id")
        return self
