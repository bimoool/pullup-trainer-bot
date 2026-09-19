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
    на каждое упражнение внутри)."""

    __tablename__ = "complexes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplexItem(Base):
    """Состав комплекса — нормализованная дочерняя таблица (не JSONB на
    Complex), потому что каждое упражнение внутри несёт собственные
    sets/target_value/rest_seconds."""

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
    тренировки не всегда имеют план, с которым сопоставлять факт."""

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
