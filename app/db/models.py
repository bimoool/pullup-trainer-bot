from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# EquipmentType/ExerciseType — доменные понятия, поэтому у db нет своей
# копии, только импорт.
from app.domain.constants import EquipmentType, ExerciseType
from app.domain.electives import ElectiveType


def _pg_enum(enum_cls: type[StrEnum], name: str) -> PgEnum:
    # sa.Enum по умолчанию хранит .name члена (NONE, TRIAL, ...) — нам нужны
    # именно .value (none, trial, ...), чтобы совпадать со StrEnum.value,
    # который использует server_default и который отдаёт домен/сервисы.
    return PgEnum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])


class WorkoutSetStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class WorkoutStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"


class BlockType(StrEnum):
    A = "a"  # объёмный блок — пользователь этой буквы не видит
    B = "b"  # силовой блок


class SubscriptionStatus(StrEnum):
    NONE = "none"
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"


class SubscriptionSource(StrEnum):
    TRIAL = "trial"
    STARS = "stars"
    COINS = "coins"
    ADMIN_GRANT = "admin_grant"
    TRIBUTE = "tribute"


class PendingPaymentProvider(StrEnum):
    TRIBUTE = "tribute"


class PendingPaymentStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class CoinReason(StrEnum):
    WORKOUT_COMPLETED = "workout_completed"
    ACHIEVEMENT_UNLOCKED = "achievement_unlocked"
    SUBSCRIPTION_EXTENSION = "subscription_extension"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    height_cm: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    gender: Mapped[Gender | None] = mapped_column(_pg_enum(Gender, "gender"), nullable=True)
    # Возраст больше не хранится числом (сразу устаревает) — дата рождения,
    # возраст на дисплей считается на лету (см. app/bot/formatting.py::
    # calculate_age), см. Часть 10 респека.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        _pg_enum(SubscriptionStatus, "subscription_status"),
        nullable=False,
        default=SubscriptionStatus.NONE,
        server_default=SubscriptionStatus.NONE.value,
    )
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coins_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Baseline(Base):
    """Замер — одно число: максимум подтягиваний с собственным весом.
    Ветки/снаряда замер больше не определяет (веток нет вообще) — снаряды
    для обоих блоков уточняются на первой тренировке отдельно."""

    __tablename__ = "baselines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reps: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EquipmentItem(Base):
    """Личный список резин пользователя — растёт по мере надобности, не
    заполняется заранее (см. Часть 8 респека). Только для BAND: у веса
    число и так чистое, у своего веса/австралийских числа нет вообще.

    resistance_kg опционален — в реальности резины в залах часто без
    маркировки ("широкая фиолетовая"), точное сопротивление не всегда
    известно. position задаёт порядок пользователя (0 — самый тяжёлый,
    то есть больше всего помощи) — именно порядок, а не кг, определяет,
    что значит "следующий снаряд" при переходах. Удаления нет (не
    запрашивалось) — FK с blocks всегда разрешим, снапшот имени на Block
    не нужен."""

    __tablename__ = "equipment_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    resistance_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "user_id", "position", name="uq_equipment_items_user_position", deferrable=True, initially="DEFERRED",
        ),
    )


class WorkoutSet(Base):
    __tablename__ = "workout_sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    started_from_baseline_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("baselines.id"), nullable=False,
    )
    set_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    workouts_completed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    status: Mapped[WorkoutSetStatus] = mapped_column(
        _pg_enum(WorkoutSetStatus, "workout_set_status"),
        nullable=False,
        default=WorkoutSetStatus.ACTIVE,
        server_default=WorkoutSetStatus.ACTIVE.value,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "set_number", name="uq_workout_sets_user_set_number"),)


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    workout_set_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workout_sets.id"), nullable=False, index=True,
    )
    # NULL, пока тренировка в статусе STARTED — хронологическая позиция для
    # каскада известна только у тренировок с посчитанными результатами.
    # NULL допустим в UNIQUE(user_id, sequence_number): в Postgres NULL != NULL,
    # так что несколько неоконченных тренировок не конфликтуют между собой.
    sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[WorkoutStatus] = mapped_column(
        _pg_enum(WorkoutStatus, "workout_status"),
        nullable=False,
        default=WorkoutStatus.STARTED,
        server_default=WorkoutStatus.STARTED.value,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Внесённые задним числом тренировки участвуют в статистике/объёме, но
    # не в каскадном пересчёте цепочки целей (WorkoutRepository фильтрует
    # по этому полю только при каскаде — при выводе ТЕКУЩЕЙ цели фильтра нет,
    # берётся хронологически последняя тренировка любого происхождения).
    participates_in_cascade: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    # "➕ Внести свободные подтягивания" (Часть 10, п. 18) — произвольная
    # тренировка вне схемы: не в сете из 12 (increment_completed не
    # вызывается), не в цепочке каскада (participates_in_cascade=False, как
    # у бэкдейта), И ДОПОЛНИТЕЛЬНО не должна становиться "последним снарядом/
    # целью" для следующей структурированной тренировки — WorkoutRepository.
    # resolve_next_targets/complete_workout явно фильтруют такие записи из
    # истории перед тем, как вывести из неё текущее состояние прогрессии
    # (см. комментарии там же). В "Историю"/статистику/объём попадает как
    # обычно — это НЕ фильтруется.
    is_free_entry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    exercise_type: Mapped[ExerciseType] = mapped_column(
        _pg_enum(ExerciseType, "exercise_type"),
        nullable=False,
        default=ExerciseType.PULL_UPS,
        server_default=ExerciseType.PULL_UPS.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    blocks: Mapped[list["Block"]] = relationship(back_populates="workout", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "sequence_number", name="uq_workouts_user_sequence_number", deferrable=True, initially="DEFERRED",
        ),
    )


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    block_type: Mapped[BlockType] = mapped_column(_pg_enum(BlockType, "block_type"), nullable=False)
    working_reps: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    max_reps: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_before: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_after: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    equipment_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Единая шкала нагрузки вместо раздельных band_thickness_mm/weight_kg:
    # equipment_type определяет точку на шкале, equipment_value — величину в
    # кг (сопротивление резины, суммарное при комбинации; вес отягощения;
    # NULL для BODYWEIGHT и AUSTRALIAN — там числа нет или оно не в кг).
    # Знак направления — только через domain.constants.to_signed_load(),
    # никогда напрямую по значению этого поля.
    equipment_type: Mapped[EquipmentType] = mapped_column(
        _pg_enum(EquipmentType, "equipment_type"), nullable=False,
    )
    equipment_value: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Ссылка на личный список резин пользователя (только для BAND — см.
    # EquipmentItem). Дальше equipment_value для BAND не заполняется:
    # число (если оно вообще известно) живёт на equipment_items.resistance_kg,
    # доступно через этот id. Для WEIGHT — по-прежнему equipment_value,
    # equipment_item_id остаётся NULL.
    equipment_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("equipment_items.id"), nullable=True,
    )
    # Первая тренировка на новом снаряде провалена (максимум ниже
    # min_viable_reps) — хранится явно, не восстанавливается сравнением
    # соседних тренировок (хрупко при правках истории).
    transition_failed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    workout: Mapped["Workout"] = relationship(back_populates="blocks")

    __table_args__ = (UniqueConstraint("workout_id", "block_type", name="uq_blocks_workout_block_type"),)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[SubscriptionStatus] = mapped_column(
        _pg_enum(SubscriptionStatus, "subscription_status"), nullable=False,
    )
    source: Mapped[SubscriptionSource] = mapped_column(
        _pg_enum(SubscriptionSource, "subscription_source"), nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Coin(Base):
    __tablename__ = "coins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[CoinReason] = mapped_column(_pg_enum(CoinReason, "coin_reason"), nullable=False)
    related_achievement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("achievements.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_achievements_user_code"),)


class PendingPayment(Base):
    """Заказ у асинхронного провайдера (сейчас — только Tribute), ожидающий
    подтверждения опросом (app/workers/tribute_sync.py). started_at/ends_at
    периода подписки здесь намеренно нет — они считаются в момент
    подтверждения (SubscriptionService.extend), а не в момент создания
    заказа, чтобы «продление стекается поверх остатка» работало от
    актуального состояния, а не от состояния на момент нажатия кнопки."""

    __tablename__ = "pending_payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[PendingPaymentProvider] = mapped_column(
        _pg_enum(PendingPaymentProvider, "pending_payment_provider"), nullable=False,
    )
    external_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[PendingPaymentStatus] = mapped_column(
        _pg_enum(PendingPaymentStatus, "pending_payment_status"),
        nullable=False,
        default=PendingPaymentStatus.PENDING,
        server_default=PendingPaymentStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SheetsSyncState(Base):
    """Курсоры выгрузки в Google Sheets (app/workers/sheets_sync.py) —
    одна строка (id=1), по одному last_*_id на каждый инкрементальный
    источник (лист events/workouts/electives/subscriptions/coins/
    achievements — у "workouts" их даже два, workouts и elective_workouts
    пишут в один лист, но каждый по своему курсору). Отдельная таблица, а
    не файл на диске — контейнер app пересоздаётся при каждом деплое,
    персистентного диска у него нет (в отличие от pgdata/redisdata),
    курсоры обязаны пережить рестарт/редеплой, иначе каждый деплой заново
    выгружал бы всю историю."""

    __tablename__ = "sheets_sync_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_workout_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_elective_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_subscription_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_coin_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_achievement_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class ElectiveWorkout(Base):
    """Факультативная нагрузка вне плана (пакет #6, app/domain/electives.py)
    — 4 самостоятельных формата, ротация без повтора + не чаще раза в
    неделю. Отдельная таблица, не workouts/blocks — не участвует в каскаде/
    прогрессии структурно (никогда не проходит через WorkoutRepository),
    без флагов is_free_entry/participates_in_cascade, без обязательного
    workout_set_id (в отличие от свободных подтягиваний, у которых Workout.
    workout_set_id NOT NULL вынуждает брать активный сет просто чтобы
    удовлетворить схему)."""

    __tablename__ = "elective_workouts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    elective_type: Mapped[ElectiveType] = mapped_column(_pg_enum(ElectiveType, "elective_type"), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Последовательность подходов — для 3 из 4 форматов (max_reps_ladder,
    # w_ladder, three_minutes); NULL для volume_target, там фиксируется
    # только итоговая сумма (см. total_reps), не сама последовательность.
    reps_sequence: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    # Заполнен всегда, для всех 4 форматов — единая колонка для агрегации
    # объёма факультативов в статистике, не завязанная на то, храним мы
    # последовательность или нет. Для 3 форматов — sum(reps_sequence), для
    # volume_target — введённое пользователем число напрямую.
    total_reps: Mapped[int] = mapped_column(Integer, nullable=False)
    # Снаряд — всегда тот же, что закреплён за пользователем в блоке на
    # объём на момент выполнения (без отдельного выбора, см. хендлер).
    equipment_type: Mapped[EquipmentType] = mapped_column(_pg_enum(EquipmentType, "equipment_type"), nullable=False)
    equipment_value: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    equipment_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("equipment_items.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
