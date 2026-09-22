"""Многокурсовая доменная модель (волна 1, issue #160) — аддитивная схема
поверх существующей pull-up-специфичной схемы app/db/models.py, ничем с ней
не связанная (кроме FK на users.id) и нигде не подключённая в проде: ни
app/web/routes.py, ни бот её не используют. Отдельный модуль, не расширение
models.py — контекст будет расти волнами 2–10, models.py уже 600+ строк.

Три переименования относительно терминов документа
turnikmen-multicourse-architecture.md (раздел 2) — из-за коллизии имён:
Session -> TrainingSession (путаница с sqlalchemy.orm.Session),
Block -> SessionBlock (уже есть app.db.models.Block — блок А/Б подтягиваний,
другая сущность). Exercise не переименован — не конфликтует с классом,
соседствует с app.domain.constants.ExerciseType (независимое понятие).

Реализует только план волны 1 (см. обсуждение в issue #160) — только
таблицы + SQLAlchemy-модели, без сервисного слоя/бизнес-логики поверх."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.multi_program import MetricType, ProgramStructureType, SessionSource, WeekPhase
from app.domain.progression_strategy import ProgressionStrategyType


def _pg_enum(enum_cls: type[StrEnum], name: str) -> PgEnum:
    # Тот же приём, что app.db.models._pg_enum — хранить .value StrEnum'а
    # (не .name), см. комментарий там же.
    return PgEnum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])


class SessionStatus(StrEnum):
    """Чисто служебный статус жизненного цикла TrainingSession (DB-механика,
    не бизнес-понятие) — по аналогии с app.db.models.WorkoutStatus."""

    STARTED = "started"
    COMPLETED = "completed"


class SessionPhase(StrEnum):
    """Фаза внутри ACTIVE-состояния живой сессии (issue #165, продолжение
    волны 3 — "сессия — live", раздел 11 docs/plan-and-specs.md) — цикл
    get_ready -> go -> rest по кругу на каждый подход, done — сессия
    завершена (терминальное значение, используется и как дефолт для строк,
    никогда не бывших "живыми", см. миграцию 3d4e5f6a7b8c). Чистый
    датакласс-подобный StrEnum, независимый от app.domain.live_session.
    SessionPhaseName — та же конвенция "domain не импортирует app.db.*",
    что у остальных app/domain/ модулей (см. CLAUDE.md); сервисный слой
    явно конвертирует между ними (app.services.live_session)."""

    GET_READY = "get_ready"
    GO = "go"
    REST = "rest"
    DONE = "done"


# --- Контент (не зависит от пользователя) -----------------------------------


class MediaAsset(Base):
    """Видео/фото техники упражнения — хранение заглушка на этой волне,
    реальный видео-хостинг это волна 10 (см. issue #160), здесь только
    ссылка."""

    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Exercise(Base):
    """Каталожная единица — не привязана к пользователю. variants — список
    исполнений по снаряду/целевому RPE ({code, equipment_type, target_rpe,
    description}), свободная JSONB-форма на этой волне: без FK на
    app.domain.constants.EquipmentType, чтобы каталог multi-program не тащил
    зависимость на pull-up-специфичный enum."""

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_type: Mapped[MetricType] = mapped_column(_pg_enum(MetricType, "mp_metric_type"), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    variants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    media_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Complex(Base):
    """Именованная связка нескольких Exercise — сам Complex не задаёт общий
    тайминг, только группирует (см. ComplexItem — там свои sets/reps/rest
    на каждое упражнение внутри).

    source_type — "system" (каталожный комплекс, доступен всем) или "user"
    (пользовательский комплекс, привязан к owner_user_id). Инвариант
    (system → owner_user_id IS NULL, user → owner_user_id IS NOT NULL)
    проверяется на уровне сервисного слоя, не DB CHECK-констрейнтом —
    в проекте их нигде не используют (см. ProgramItem, "ровно одно из
    exercise_id/complex_id" — тот же принцип валидации сервисным слоем)."""

    __tablename__ = "complexes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="system", server_default="system")
    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplexItem(Base):
    """Состав комплекса — нормализованная дочерняя таблица (не JSONB на
    Complex), потому что каждое упражнение внутри несёт собственные
    sets/target_value/rest_seconds.

    protocol — произвольный JSON-объект (Pydantic-схема определяется Worker A
    параллельно, здесь просто JSONB-колонка). NULL для legacy-записей
    (созданных до введения protocol) — старые поля sets/target_value/
    target_unit/rest_seconds остаются compatibility path."""

    __tablename__ = "complex_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    complex_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("complexes.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    exercise_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exercises.id"), nullable=False, index=True)
    order_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sets: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    target_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rest_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    protocol: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProgressionStrategyProfile(Base):
    """Именованный конфиг конкретной ProgressionStrategy (волна 0,
    app.domain.progression_strategy) — стратегии волны 0 сами по себе Python-
    классы без параметров экземпляра (кроме PercentageProgressionStrategy(
    percentage)), Program.progression_strategy_id нужна строка БД, которая
    говорит, какая реализация и с каким конфигом используется.

    config — {} для step (сама стратегия без параметров), {"percentage":
    "0.85"} для percentage."""

    __tablename__ = "progression_strategy_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_type: Mapped[ProgressionStrategyType] = mapped_column(
        _pg_enum(ProgressionStrategyType, "mp_progression_strategy_type"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssessmentProtocol(Base):
    """Разовый тест-протокол (замер/тест на максимум) — не участвует в
    каскаде прогрессии, свой тренд/график считается по AssessmentResult."""

    __tablename__ = "assessment_protocols"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_type: Mapped[MetricType] = mapped_column(_pg_enum(MetricType, "mp_metric_type"), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentResult(Base):
    """История замеров пользователя по AssessmentProtocol — без этой
    таблицы протокол был бы просто справочником без данных, "свой
    тренд/график" из issue #160 требует именно историю значений во
    времени."""

    __tablename__ = "assessment_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    protocol_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("assessment_protocols.id"), nullable=False, index=True,
    )
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Program(Base):
    """Недельная матрица Exercise/Complex (см. ProgramItem) + конфиг
    прогрессии/констант. goal — свободный текст на этой волне (документ не
    перечисляет допустимые значения, не enum)."""

    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(String(255), nullable=False)
    structure_type: Mapped[ProgramStructureType] = mapped_column(
        _pg_enum(ProgramStructureType, "mp_program_structure_type"), nullable=False,
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    progression_strategy_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("progression_strategy_profiles.id", ondelete="SET NULL"), nullable=True,
    )
    # «Program может ссылаться на результат (например, 2ПМ) при расчёте %
    # нагрузки» — отдельная колонка с FK, не спрятано внутри config, ради
    # целостности ссылки.
    reference_assessment_protocol_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("assessment_protocols.id", ondelete="SET NULL"), nullable=True,
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProgramItem(Base):
    """Строка недельной матрицы Program — ровно одно из exercise_id/
    complex_id (проверяется сервисным слоем волны 2+, не CHECK-констрейнтом
    — в проекте их нигде не используют). day_of_week NULL значит "свободный
    пул недели". Это форма, которую при ProgramInclusion копируют строки
    PlanItem — не проверяется намеренно на уровне БД, чтобы не тащить
    двойное обязательство синхронизации схем раньше времени."""

    __tablename__ = "program_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    program_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    week_phase: Mapped[WeekPhase] = mapped_column(_pg_enum(WeekPhase, "mp_week_phase"), nullable=False)
    exercise_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("exercises.id"), nullable=True)
    complex_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("complexes.id"), nullable=True)
    count_per_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# --- План и прогресс (зависит от пользователя) ------------------------------


class TrainingPlan(Base):
    """Единственный активный план пользователя — одна строка на всю жизнь
    аккаунта (UNIQUE user_id), не последняя из нескольких исторических. Не
    ограничен по датам сам по себе — живёт, пока есть хотя бы один активный
    ProgramInclusion или ручной PlanItem (правило сервисного слоя, не БД)."""

    __tablename__ = "training_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlanWeek(Base):
    __tablename__ = "plan_weeks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    training_plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    week_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    phase: Mapped[WeekPhase] = mapped_column(_pg_enum(WeekPhase, "mp_week_phase"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("training_plan_id", "week_number", name="uq_plan_weeks_plan_week_number"),
    )


class ProgramInclusion(Base):
    """Program x TrainingPlan — хранит СНИМОК содержимого Program на момент
    подключения (snapshot), не live-ссылку: program_id — происхождение, не
    источник контента. Несколько ProgramInclusion могут сосуществовать в
    одном TrainingPlan."""

    __tablename__ = "program_inclusions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    training_plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    program_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("programs.id"), nullable=False, index=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Форма зависит от strategy_type — тот же принцип, что ProgressionContext/
    # PercentageProgressionContext волны 0 разные, не унифицированные.
    progression_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # Снимок progression_state НА МОМЕНТ создания инклюзии — в отличие от
    # progression_state выше (живое, мутируемое значение), это поле никогда
    # не переписывается после создания строки. Нужен как известная точка
    # старта для app.services.progression_cascade: воспроизвести всю цепочку
    # тренировок заново при правке исторической сессии, не полагаясь на
    # снимки состояния на каждую отдельную сессию (их нет).
    initial_progression_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlanItem(Base):
    """Строка недельной матрицы плана пользователя. source = program_
    inclusion_id или NULL (добавлено вручную) — строки от разных источников
    НЕ объединяются автоматически, даже ссылаясь на один Exercise (правило
    сервисного слоя волны 2+, не ограничение БД — намеренно без
    UNIQUE-констрейнта)."""

    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    training_plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    exercise_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exercises.id"), nullable=False, index=True)
    complex_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("complexes.id"), nullable=True)
    count_per_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # NULL у ручных строк = "каждую неделю независимо от фазы"; унаследовано
    # от program_items.week_phase, если пришло из инклюзии.
    week_phase: Mapped[WeekPhase | None] = mapped_column(_pg_enum(WeekPhase, "mp_week_phase"), nullable=True)
    program_inclusion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("program_inclusions.id", ondelete="CASCADE"), nullable=True,
    )
    # Checkpoint 1 (issue #188) — единственный отсутствовавший FK связки
    # Program/ProgramItem/ProgramInclusion/TrainingPlan/PlanWeek/PlanItem:
    # plan_weeks существовала с волны 1, но ни одна строка plan_items на неё
    # не ссылалась. NULL для строк, ещё не прошедших ensure_current_plan_week
    # (см. app/services/plan_week.py) — целевое состояние после бэкфилла
    # заполнено у всех.
    plan_week_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("plan_weeks.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TrainingSession(Base):
    """Фактически выполненная тренировка (термин документа — Session,
    переименовано из-за коллизии с sqlalchemy.orm.Session). source включает
    четвёртое значение elective (поправка Кирилла в issue #160) — сама
    миграция данных из app.db.models.ElectiveWorkout не делается в этой
    волне, это задел волны 2."""

    __tablename__ = "training_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    source: Mapped[SessionSource] = mapped_column(_pg_enum(SessionSource, "mp_session_source"), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        _pg_enum(SessionStatus, "mp_session_status"),
        nullable=False,
        default=SessionStatus.STARTED,
        server_default=SessionStatus.STARTED.value,
    )
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effort: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- Живая (server-driven) сессия (issue #165, продолжение волны 3) ---
    # client_session_id — идемпотентность POST /sessions/live по офлайн-
    # контракту (клиент генерирует UUID ДО первого запроса к серверу,
    # см. app.services.live_session.start_session). NULL и не уникален
    # относительно других NULL — сессии старого пути (POST /api/v2/sessions,
    # "записать уже выполненное целиком") никогда его не ставят.
    client_session_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    phase_name: Mapped[SessionPhase] = mapped_column(
        _pg_enum(SessionPhase, "mp_session_phase"),
        nullable=False, default=SessionPhase.DONE, server_default=SessionPhase.DONE.value,
    )
    phase_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_block_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    current_set_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    # Монотонный счётчик переходов фазы — см. докстринг миграции 3d4e5f6a7b8c:
    # офлайн-контракт сравнивает клиентский expected_phase_index с этим полем
    # одним int, не пересчитывает его на лету из block_index/set_number/
    # phase_name (риск разойтись с тем, что клиент видел в прошлом ответе).
    phase_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    # --- Interval workout snapshot (Phase B1, issue #215) ---
    # Immutable resolved WorkoutSnapshot (app.domain.workout_snapshot) на момент
    # старта interval-сессии — переживает изменение ComplexItem.protocol после
    # старта (снапшот не меняется). NULL для legacy rows и для non-interval
    # сессий (standard STEP/manual path).
    workout_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class SessionPlanItem(Base):
    """M2M — связь TrainingSession с одним или несколькими PlanItem."""

    __tablename__ = "session_plan_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    plan_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plan_items.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    __table_args__ = (
        UniqueConstraint("session_id", "plan_item_id", name="uq_session_plan_items_session_plan_item"),
    )


class SessionBlock(Base):
    """Часть сессии (термин документа — Block, переименовано из-за коллизии
    с app.db.models.Block — блок А/Б подтягиваний, другая сущность). Ровно
    одно из exercise_id/complex_id (сервисный слой, не CHECK)."""

    __tablename__ = "session_blocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    order_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    exercise_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("exercises.id"), nullable=True)
    complex_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("complexes.id"), nullable=True)
    # Interval workout result (Phase B1, issue #215) — summary после
    # finalization (lazy completion при GET active/list): completed_cycles,
    # actual_duration_seconds. NULL для legacy rows и для non-interval blocks.
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SetTarget(Base):
    """План на подход. metric_type — снимок с Exercise.metric_type на
    момент планирования (переживает будущую правку каталога так же, как
    equipment_item_name переживает переименование резины в старой схеме)."""

    __tablename__ = "set_targets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_block_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("session_blocks.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    set_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_max_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    metric_type: Mapped[MetricType] = mapped_column(_pg_enum(MetricType, "mp_metric_type"), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    effort: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SetLog(Base):
    """Факт по подходу. set_target_id NULL допустим — freeform/backdated
    тренировки не всегда имеют план, с которым сопоставлять факт.

    session_id/set_index — денормализация под батч-эндпоинт живой сессии
    (issue #165, продолжение волны 3): session_id уже доступен транзитивно
    через session_block_id -> session_blocks.session_id, но upsert-ключ
    офлайн-контракта (session_id, set_index) без него потребовал бы JOIN на
    каждый апсерт батча. NULL у обеих колонок для записей старого пути
    (POST /api/v2/sessions, TrainingSessionRepository.create_session) —
    он их не проставляет, а UNIQUE(session_id, set_index) не считает
    несколько NULL конфликтующими (Postgres), так что старые строки друг
    другу не мешают."""

    __tablename__ = "set_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_block_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("session_blocks.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    set_target_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("set_targets.id", ondelete="SET NULL"), nullable=True,
    )
    set_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_max_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    metric_type: Mapped[MetricType] = mapped_column(_pg_enum(MetricType, "mp_metric_type"), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    effort: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    set_index: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("session_id", "set_index", name="uq_set_logs_session_set_index"),
    )
