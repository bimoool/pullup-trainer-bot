from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
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


def _pg_enum(enum_cls: type[StrEnum], name: str) -> PgEnum:
    # sa.Enum по умолчанию хранит .name члена (NONE, TRIAL, ...) — нам нужны
    # именно .value (none, trial, ...), чтобы совпадать со StrEnum.value,
    # который использует server_default и который отдаёт домен/сервисы.
    return PgEnum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])


class Branch(StrEnum):
    BAND = "band"
    ASSISTED = "assisted"


class EquipmentType(StrEnum):
    BAND = "band"
    WEIGHT = "weight"


class WorkoutSetStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class WorkoutStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"


class BlockType(StrEnum):
    A = "a"
    B = "b"


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


class CoinReason(StrEnum):
    WORKOUT_COMPLETED = "workout_completed"
    ACHIEVEMENT_UNLOCKED = "achievement_unlocked"
    SUBSCRIPTION_EXTENSION = "subscription_extension"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    height_cm: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    age: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    branch: Mapped[Branch | None] = mapped_column(_pg_enum(Branch, "branch"), nullable=True)
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
    __tablename__ = "baselines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    branch_result: Mapped[Branch] = mapped_column(_pg_enum(Branch, "branch"), nullable=False)
    equipment_type: Mapped[EquipmentType] = mapped_column(
        _pg_enum(EquipmentType, "equipment_type"), nullable=False,
    )
    band_thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    reps: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[WorkoutStatus] = mapped_column(
        _pg_enum(WorkoutStatus, "workout_status"),
        nullable=False,
        default=WorkoutStatus.STARTED,
        server_default=WorkoutStatus.STARTED.value,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    band_thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
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
