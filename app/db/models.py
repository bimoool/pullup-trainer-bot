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
    ROBOKASSA = "robokassa"


class PendingPaymentProvider(StrEnum):
    ROBOKASSA = "robokassa"


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


class ActiveTimerType(StrEnum):
    REST_BETWEEN_SETS = "rest_between_sets"
    BIG_BREAK = "big_break"


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
    # Персистентные настройки длительности таймера Mini App (issue #59,
    # волна 2) — NULL значит "не настраивал", дефолт (см.
    # app.domain.constants.DEFAULT_REST_SECONDS_BLOCK_A/B/BIG_BREAK_SECONDS)
    # резолвится на чтении, не записывается сюда при онбординге, чтобы
    # будущая правка дефолтных чисел в коде сразу подхватывалась всеми, кто
    # ничего не менял (тот же приём, что nullable timezone выше).
    rest_seconds_block_a: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rest_seconds_block_b: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    big_break_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Лидерборд (issue #67) — NULL значит "анонимно", единственное и
    # дефолтное состояние, пока пользователь явно не задал имя. Явный отказ
    # ("быть анонимным" после того, как имя уже было задано) — это то же
    # самое NULL, отдельного boolean-флага сознательно нет (см. план в
    # issue #67).
    leaderboard_display_name: Mapped[str | None] = mapped_column(String, nullable=True)
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
    # Иерархия роста блока на объём (ревизия формулы прогрессии) — число
    # рабочих подходов ДО/ПОСЛЕ этой тренировки растёт по правилу застоя/
    # потолка (см. app.domain.progression.recalculate_volume_block), в
    # отличие от силового блока больше не фиксировано константой. NULL для
    # блока B (там подходы всегда STRENGTH_BLOCK.work_sets, отдельно не
    # хранится) и для исторических записей до этой ревизии.
    work_sets_before: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    work_sets_after: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Почему выросли work_sets ЭТОЙ тренировки — "stall"/"ceiling" (issue
    # #79, app.domain.constants.VolumeGrowthReason) или NULL, если не
    # выросли. Простой String(10), не Postgres enum — значений всего два,
    # ALTER TYPE ради такого расширения не нужен (см. CLAUDE.md про выбор
    # между String и pg enum для похожего случая).
    work_sets_growth_reason: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Ежемесячная разгрузочная тренировка блока на объём — не участвует в
    # пересчёте прогрессии (target/work_sets/вес проходят без изменений),
    # только в статистике/объёме, как факультативы и свободные подтягивания.
    # Только для блока A, у блока B всегда False.
    is_deload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Итог за тренировку без раскладки по подходам (issue #88) — только для
    # бэкдейта блока Б, когда пользователь не помнит числа по подходам, но
    # знает сумму. NULL — обычная запись, volume считается как обычно из
    # working_reps/max_reps (см. app.domain.session.BlockLog.volume). Когда
    # задано — working_reps всегда [], max_reps — 0 (максимум не
    # зафиксирован) либо реально введённый лучший подход; volume берётся
    # ОТСЮДА, не из max_reps, иначе итог исказил бы "лучший подход"
    # (best_set/лидерборд MAX_REPS/MAX_WEIGHT) так же, как баг из issue #88.
    reported_volume: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
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
    """Заказ у асинхронного провайдера (сейчас — только Робокасса, Tribute
    удалён после отказа в верификации продавца), ожидающий подтверждения
    опросом (app/workers/robokassa_sync.py). started_at/ends_at периода
    подписки здесь намеренно нет — они считаются в момент подтверждения
    (SubscriptionService.extend), а не в момент создания заказа, чтобы
    «продление стекается поверх остатка» работало от актуального
    состояния, а не от состояния на момент нажатия кнопки."""

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
    achievements/baselines — у "workouts" их даже два, workouts и
    elective_workouts пишут в один лист, но каждый по своему курсору).
    Отдельная таблица, а
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
    last_baseline_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
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


class WeeklyDigest(Base):
    """Журнал фактически разосланных еженедельных дайджестов (Часть 12,
    app/workers/weekly_digest.py) — не только источник last_digest_sent_at
    (последняя строка по sent_at, для диапазона будущего автосбора
    "что раскатили"/"что в работе"), но и самостоятельный аудит: что
    именно и когда было разослано пользователям, тем же принципом, что
    subscriptions/workouts — история, а не единственная изменяемая
    строка-курсор. Отдельная таблица, не файл на диске — контейнер app
    пересоздаётся при каждом деплое (см. SheetsSyncState), персистентного
    диска у него нет.

    Пишется только при УСПЕШНОЙ рассылке (handle_weekly_digest_reply) —
    просроченный ответ (позже WEEKLY_DIGEST_REPLY_DEADLINE_HOURS) молча
    пропускается и строку сюда не добавляет, иначе last_digest_sent_at
    сдвигался бы неделя за неделей без единой реальной рассылки."""

    __tablename__ = "weekly_digests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    recipients_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ActiveTimer(Base):
    """Персистентный таймер живой тренировки Mini App (issue #59, волна 1)
    — время окончания хранится на сервере, не в localStorage браузера,
    чтобы пережить закрытие Telegram, очистку данных браузера, смену
    устройства: клиент только спрашивает "сколько осталось" по факту
    открытия (GET /api/timer/status), не ведёт свой независимый отсчёт.

    Один активный таймер на пользователя (unique user_id) — в один момент
    у пользователя идёт ровно один поток тренировки в одной вкладке (см.
    режим тренировки в реальном времени, Волна 2). Старт нового таймера
    заменяет предыдущий (см. ActiveTimerRepository.start) — история
    подходов таймер не хранит, она держится во фронтенд-состоянии до
    финального submit_workout (так и в issue).

    started_at выставляется сервером (datetime.now(UTC)) в момент
    POST /api/timer/start — клиентское значение не принимается, иначе
    рассинхрон часов устройства ломает весь смысл серверного источника
    правды. block_letter/set_number не влияют на расчёт оставшегося
    времени — только контекст для восстановления экрана при повторном
    открытии Mini App. Нет FK на blocks/workout_sets: в момент отдыха
    между подходами блок ещё не создан в БД (создаётся только при
    финальном submit_workout)."""

    __tablename__ = "active_timers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True,
    )
    timer_type: Mapped[ActiveTimerType] = mapped_column(
        _pg_enum(ActiveTimerType, "active_timer_type"), nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    block_letter: Mapped[str | None] = mapped_column(String(1), nullable=True)
    set_number: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkoutDraft(Base):
    """Черновик тренировки в реальном времени (issue #61) — накопленные
    результаты уже завершённых подходов на сервере, переживает закрытие
    Telegram посреди тренировки (в отличие от ActiveTimer, который знает
    только текущий отсчёт отдыха, см. докстринг выше). Один черновик на
    пользователя (unique user_id), тот же приём, что у ActiveTimer.

    Живёт отдельно от ActiveTimer, не как одно поле в той же таблице:
    во время шага ввода повторений никакой таймер не запущен, а строка
    ActiveTimer от прошлого шага отдыха может просто лежать "протухшей"
    (TimerScreen не удаляет её при обычном продолжении, только при явном
    пропуске) — совмещать в одной строке два независимых жизненных цикла
    было бы источником рассинхрона. Черновик и таймер ссылаются друг на
    друга только неявно, через user_id.

    Не хранит snapshot плана (target/work_sets/equipment) — при
    восстановлении план перезапрашивается тем же GET /api/workout/plan,
    что и при обычном старте: пока черновик не сдан через submit_workout,
    прогрессия не менялась, план детерминирован тем же состоянием БД.
    step_index — единственный источник позиции в потоке шагов, сами шаги
    пересобираются на фронтенде той же buildSteps(work_sets_a, work_sets_b).

    Нет FK на blocks/workout_sets — блок создаётся только в submit_workout,
    как и у ActiveTimer (в момент черновика тренировка ещё не записана)."""

    __tablename__ = "workout_drafts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_a_working_reps: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    block_a_max_reps: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    block_b_working_reps: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    block_b_max_reps: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    block_a_actual_weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    block_b_actual_weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    block_a_actual_band_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_b_actual_band_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
