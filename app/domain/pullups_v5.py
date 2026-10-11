"""Основная программа «Подтягивания» V5.6 — авторегуляция внутри фиксированной структуры (issue #305).

Источник истины — документ владельца «Подтягивания V5.6: авторегуляция внутри фиксированной
структуры» (11.10.2026), канонический контракт в репозитории — ``docs/domain/PULLUPS_V5_6.md``.
Модуль чистый: без aiogram/sqlalchemy, «сейчас» и масса тела приходят параметрами, вес — ``Decimal``.

Структура: две основные тренировки в неделю, A и B; в каждой — разминка, объёмный блок, 15 минут
отдыха, подводка к рабочему сопротивлению, силовой блок. Каждый блок прогрессирует по своему сигналу
(``BlockRole``): универсального «MAX двигает прогрессию» больше нет.

**Числа ниже — продуктовые параметры V5.6, а не научно установленные пороги.** Документ прямо помечает
их как тестируемые гипотезы продукта (§2, §4, §6, §8.2, §8.3, §8.5, §8.6, §8.7, §12): 70% для A,
стартовый потолок 20, запас +2, нижняя граница B в 10 подходов, 30 секунд, стоп после двух повторений,
пороги допуска 10 и 8, граница 15 для переходной недели, 75%/80% от 1RM, шаг 2% в пределах 0,5–2,5 кг,
три попытки до калибровки, лестница теста 1RM. Менять их — только новой версией программы.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

PROGRAM_VERSION = "pullups_v5_6"
LEGACY_PROGRAM_VERSION = "pullups_legacy_step"
STATE_SCHEMA_VERSION = 1

# --- Параметры продукта V5.6 (гипотезы продукта, не биологические пороги) ---------------------

# Расписание (§1 «Две тренировки в неделю»): ровно 2 основных занятия в неделю, A и B по
# последовательности. Действует ТОЛЬКО для инклюзий V5.6 — замораживается в их снимок при подключении
# (version-scoped), каталог программы и снимки устаревших инклюзий не меняются.
MAIN_SESSIONS_PER_WEEK = 2

# Разминка (§1 п. 1) и подводка к рабочему сопротивлению (§1 п. 4, §8.2, §8.4): в документе V5.6 только
# названы; содержание (упражнения, подходы, повторения, нагрузка, время, отдых) НЕ задано и не придумывается.
WARM_UP_SPEC = {
    "prescribed": False, "source": "V5.6 §1 п. 1 «разминка»",
    "missing": ["content", "duration_seconds", "sets_or_exercises", "rest_before_volume_seconds"],
}
STRENGTH_RAMP_UP_SPEC = {
    "prescribed": False, "counts_as_working_sets": False,
    "source": "V5.6 §1 п. 4 «подводка к рабочему сопротивлению»; §8.4 «короткая подводка, не входящая в пять "
              "рабочих подходов»; §8.2 «одно-два собственных повторения можно оставить в подводке»",
    "missing": ["sets", "reps", "load_or_assistance", "rest_seconds", "rest_before_first_work_set_seconds"],
}

# Время (§1, §10): A-объём 4 минуты, B-объём строго 30 секунд, объём → сила 15 минут, сила 3 минуты.
A_VOLUME_REST_SECONDS = 240
B_VOLUME_REST_SECONDS = 30
INTER_BLOCK_REST_SECONDS = 900
STRENGTH_REST_SECONDS = 180
ONE_RM_REST_SECONDS = 180

# A, длинный объём (§4): a = min(20, max(3, floor(0,70 × R))), 4 подхода, последний — технический AMRAP.
A_VOLUME_SETS = 4
A_START_COEFFICIENT = Decimal("0.70")
A_START_CAP = 20  # только стартовая доза; позже цели могут стать 21+ (§13)
A_START_FLOOR = 3
A_GREEN_MARGIN = 2  # зелёный результат: последний подход ≥ p4 + 2
A_RED_ROLLBACK_STREAK = 2  # два красных подряд — откат последнего добавленного повторения

# B, короткий объём (§5, §6).
B_DEFAULT_REPS = 5
B_START_MIN_SETS = 10
B_MAX_SETS = 20
B_LARGE_REFERENCE = 100  # V_ref ≥ 100: S = 20, q = floor(V_ref / 20) + 1
B_STOP_AT_OR_BELOW = 2  # подход с ≤ 2 повторениями записывается и завершает блок; 3 — продолжать

# Переходная неделя после допуска (§8.2): A 5/5/5/5+, B 10×3 → 10×4 → 10×5 → обычная лестница.
TRANSITION_A_TARGET = 5
TRANSITION_B_SETS = 10
TRANSITION_B_START_REPS = 3

# Допуск к уровню с весом (§8.2) и граница переходной недели.
QUALIFY_FRESH_MAX = 10
STANDARD_VOLUME_FROM_FRESH_MAX = 15

# Уровень 1, сила с помощью (§8.2): 5/5/5/5/5–8.
ASSISTED_STRENGTH_SETS = 5
ASSISTED_STRENGTH_TARGET = 5
ASSISTED_CONTROL_CAP = 8

# Уровень 2, сила с весом (§8.3–§8.6).
A_STRENGTH_SETS, A_STRENGTH_REPS = 5, 5
B_STRENGTH_SETS, B_STRENGTH_REPS = 5, 3
A_STRENGTH_PERCENT = Decimal("0.75")
B_STRENGTH_PERCENT = Decimal("0.80")
LOAD_DELTA_PERCENT = Decimal("0.02")
LOAD_DELTA_MIN = Decimal("0.5")
LOAD_DELTA_MAX = Decimal("2.5")
PLATEAU_NO_IMPROVEMENT_ATTEMPTS = 3
PLATEAU_DETERIORATIONS = 2

# Тест 1RM (§8.3): не более восьми подходов вместе с подводящими.
ONE_RM_MAX_SETS = 8
ONE_RM_MIN_HOURS_AFTER_HEAVY_PULLING = 48
ONE_RM_RAMP = ((Decimal(0), 5), (Decimal("0.10"), 3), (Decimal("0.20"), 1))


class V5StateError(ValueError):
    """Состояние/прескрипция не соответствует контракту V5.6."""


class ProgramLevel(StrEnum):
    ASSISTED = "assisted"  # уровень 1: до допуска к дополнительному весу
    TRANSITION = "transition"  # первая фаза объёма с массой тела после допуска (B идёт 10×3→10×4→10×5)
    WEIGHTED = "weighted"  # уровень 2: силовые блоки с дополнительным весом, обычные лестницы объёма


class WorkoutRole(StrEnum):
    A = "A"
    B = "B"

    @property
    def other(self) -> "WorkoutRole":
        return WorkoutRole.B if self is WorkoutRole.A else WorkoutRole.A


class BlockRole(StrEnum):
    """Тип блока = тип сигнала прогрессии. Результат прогрессии всегда типизирован этой ролью."""

    A_VOLUME = "a_volume"
    B_VOLUME = "b_volume"
    ASSISTED_STRENGTH = "assisted_strength"
    A_WEIGHTED_STRENGTH = "a_weighted_strength"
    B_WEIGHTED_STRENGTH = "b_weighted_strength"


class SetMarker(StrEnum):
    WORKING = "working"  # обязательная цель
    AMRAP = "amrap"  # последний подход A: технический AMRAP с минимальной целью p4
    CONTROL = "control"  # пятый подход силы с помощью: минимум 5, жёсткий потолок 8
    DYNAMIC = "dynamic"  # подход B: блок может закончиться раньше по стоп-правилу


class BVolumeStage(StrEnum):
    PENDING_REFERENCE = "pending_reference"  # ещё нет подтверждённого объёма (факта первой A)
    TRANSITION = "transition"  # 10×3 → 10×4 → 10×5
    STANDARD = "standard"  # S×q: +1 подход до 20, затем 20×(q+1)


class AssistanceIntent(StrEnum):
    DECREASE = "decrease_assistance"
    KEEP = "keep_assistance"
    INCREASE = "increase_assistance"


class PendingInput(StrEnum):
    """Входы, без которых часть прескрипции не считается. Ничего не угадывается: блок ждёт ввода."""

    FRESH_MAX = "fresh_max"  # M
    VOLUME_CAPACITY = "volume_capacity"  # R (уровень 1: способность с объёмной резиной ≈ 8–12)
    VOLUME_ASSISTANCE = "volume_assistance"  # объёмная резина уровня 1
    STRENGTH_ASSISTANCE = "strength_assistance"  # помощь в силовом блоке уровня 1 (или явно «без помощи»)
    BODY_MASS = "body_mass"  # BW
    ONE_REP_MAX = "one_rep_max"  # E1RM или подтверждённый 5×5 / 5×3
    LOAD_STEP = "load_step"  # доступный шаг дополнительного веса
    VOLUME_REFERENCE = "volume_reference"  # V_ref первой B: факт первой A или подтверждённый объём
    # Смена помощи ждёт подтверждения ПОЛНОЙ записи следующей резины пользователем (модель, цвет, крепление,
    # положение стопы/колена): порядок личного списка резин этого не подтверждает. Намерение сохраняется.
    ASSISTANCE_CONFIRMATION = "assistance_confirmation"
    RECOVERY_CHECK = "recovery_check"  # §9: два занятия подряд хуже по обоим блокам


# --- Помощь (резина) ----------------------------------------------------------------------------


BODYWEIGHT_KIND = "bodyweight"
BAND_KIND = "band"


@dataclass(frozen=True)
class AssistanceSetup:
    """Однозначная запись помощи (§8.2): модель/название, цвет, крепление, положение стопы или колена.
    ``kind = bodyweight`` — без помощи. Килограммы резине не приписываются (их нет в источнике)."""

    kind: str
    equipment_item_id: int | None = None
    name: str | None = None
    colour: str | None = None
    attachment: str | None = None
    body_position: str | None = None

    @property
    def is_bodyweight(self) -> bool:
        return self.kind == BODYWEIGHT_KIND

    @property
    def is_complete(self) -> bool:
        """Запись помощи готова к использованию: без помощи — всегда; резина — только если подтверждены
        модель/название, цвет, крепление и положение стопы или колена (§8.2). Неполная запись (например,
        резина, взятая по порядку из личного списка, где есть только название) готовой не считается."""
        if self.is_bodyweight:
            return True
        return all(bool((value or "").strip()) for value in (self.name, self.colour, self.attachment, self.body_position))

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "equipment_item_id": self.equipment_item_id, "name": self.name,
            "colour": self.colour, "attachment": self.attachment, "body_position": self.body_position,
        }

    @classmethod
    def from_dict(cls, data: Mapping | None) -> "AssistanceSetup | None":
        if data is None:
            return None
        kind = data.get("kind")
        if kind not in (BODYWEIGHT_KIND, BAND_KIND):
            raise V5StateError(f"unknown assistance kind {kind!r}")
        return cls(
            kind=kind, equipment_item_id=data.get("equipment_item_id"), name=data.get("name"),
            colour=data.get("colour"), attachment=data.get("attachment"), body_position=data.get("body_position"),
        )


BODYWEIGHT = AssistanceSetup(kind=BODYWEIGHT_KIND)


def _setup_dict(setup: AssistanceSetup | None) -> dict | None:
    return setup.to_dict() if setup is not None else None


# Блоки состояния, у которых есть помощь (ключи записей «ожидает подтверждения»).
VOLUME_A_BLOCK, VOLUME_B_BLOCK, STRENGTH_A_BLOCK, STRENGTH_B_BLOCK = "volume_a", "volume_b", "strength_a", "strength_b"
ASSISTANCE_BLOCKS = (VOLUME_A_BLOCK, VOLUME_B_BLOCK, STRENGTH_A_BLOCK, STRENGTH_B_BLOCK)


def _role_blocks(role: "WorkoutRole") -> tuple[str, str]:
    return (VOLUME_A_BLOCK, STRENGTH_A_BLOCK) if role is WorkoutRole.A else (VOLUME_B_BLOCK, STRENGTH_B_BLOCK)


@dataclass(frozen=True)
class AssistanceStep:
    """Итог шага помощи. ``setup`` — следующая помощь; ``selection_required`` — шаг нельзя выбрать без
    пользователя (нет упорядоченного списка резин или в нём нет следующей ступени): текущая помощь
    сохраняется как есть, а намерение записывается."""

    intent: AssistanceIntent
    setup: AssistanceSetup | None
    selection_required: bool


def step_assistance(
    current: AssistanceSetup | None, intent: AssistanceIntent, ladder: Sequence[AssistanceSetup],
) -> AssistanceStep:
    """Одна доступная ступень помощи по ЛИЧНОМУ упорядоченному списку резин пользователя
    (``EquipmentItem.position``: 0 — больше всего помощи). Универсального порядка резин нет и он не
    выдумывается: без списка или без следующей ступени — ``selection_required``.

    * уменьшить: следующая, более лёгкая резина; после самой лёгкой — масса тела (§8.2: «когда
      следующей ступенью становится масса тела, пользователь пробует тот же план без резины»);
    * увеличить: более тяжёлая резина; с массы тела — самая лёгкая резина списка.
    Новой резине известны только название/id из списка; крепление и положение стопы/колена
    пользователь подтверждает сам (их нет в справочнике)."""
    if intent is AssistanceIntent.KEEP or current is None:
        return AssistanceStep(intent, current, selection_required=current is None and intent is not AssistanceIntent.KEEP)
    ids = [item.equipment_item_id for item in ladder]
    if current.is_bodyweight:
        if intent is AssistanceIntent.DECREASE:
            return AssistanceStep(intent, current, selection_required=False)  # меньше помощи, чем ноль, нет
        if not ladder:
            return AssistanceStep(intent, current, selection_required=True)
        return AssistanceStep(intent, _from_ladder(ladder[-1]), selection_required=False)
    if current.equipment_item_id is None or current.equipment_item_id not in ids:
        return AssistanceStep(intent, current, selection_required=True)
    index = ids.index(current.equipment_item_id)
    if intent is AssistanceIntent.DECREASE:
        if index + 1 < len(ladder):
            return AssistanceStep(intent, _from_ladder(ladder[index + 1]), selection_required=False)
        return AssistanceStep(intent, BODYWEIGHT, selection_required=False)
    if index > 0:
        return AssistanceStep(intent, _from_ladder(ladder[index - 1]), selection_required=False)
    return AssistanceStep(intent, current, selection_required=True)


def _from_ladder(item: AssistanceSetup) -> AssistanceSetup:
    return AssistanceSetup(kind=BAND_KIND, equipment_item_id=item.equipment_item_id, name=item.name, colour=item.colour)


# --- Расписание -----------------------------------------------------------------------------------


def schedule_snapshot(snapshot: Mapping) -> dict:
    """Снимок инклюзии V5.6: main-слот — ``MAIN_SESSIONS_PER_WEEK`` занятий в неделю (§1). Прочие слоты
    и состав main-слота не трогаются; метка ``schedule`` фиксирует источник частоты. Идемпотентно."""
    slots = [
        {**slot, "sessions_per_week": MAIN_SESSIONS_PER_WEEK} if slot.get("key") == "main" else dict(slot)
        for slot in snapshot.get("slots") or []
    ]
    return {
        **snapshot, "slots": slots,
        "schedule": {"program_version": PROGRAM_VERSION, "main_sessions_per_week": MAIN_SESSIONS_PER_WEEK},
    }


# --- Вес -----------------------------------------------------------------------------------------


def _dec(value: object | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _dec_str(value: Decimal | None) -> str | None:
    return format(value.normalize(), "f") if value is not None else None


def round_down_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise V5StateError("load step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def initial_weighted_loads(*, body_mass: Decimal, e1rm: Decimal, load_step: Decimal) -> tuple[Decimal, Decimal]:
    """§8.3: T1RM = BW + E1RM; E5 = вниз до шага (0,75·T1RM − BW); E3 = вниз до шага (0,80·T1RM − BW).
    Нулевой или отрицательный внешний вес — масса тела (0). 75/80 — консервативная формула продукта."""
    total = body_mass + e1rm
    e5 = round_down_to_step(A_STRENGTH_PERCENT * total - body_mass, load_step)
    e3 = round_down_to_step(B_STRENGTH_PERCENT * total - body_mass, load_step)
    return max(e5, Decimal(0)), max(e3, Decimal(0))


def load_increment(*, body_mass: Decimal, working_load: Decimal, load_step: Decimal) -> Decimal | None:
    """§8.5: Δraw = 0,02 × (BW + Ework); Δ — ближайший ДОСТУПНЫЙ шаг (кратный ``load_step``) в пределах
    0,5–2,5 кг; при равном расстоянии — меньший. Нет ни одного доступного шага в этих пределах (шаг
    снаряда больше 2,5 кг) — ``None``: оборудование не даёт допустимой прибавки, нужен ввод."""
    raw = LOAD_DELTA_PERCENT * (body_mass + working_load)
    candidates: list[Decimal] = []
    multiple = load_step
    while multiple <= LOAD_DELTA_MAX:
        if multiple >= LOAD_DELTA_MIN:
            candidates.append(multiple)
        multiple += load_step
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: (abs(candidate - raw), candidate))


# --- Тест 1RM (§8.3) ------------------------------------------------------------------------------


class AttemptSpeed(StrEnum):
    FAST = "fast"  # явно быстрое повторение → +≈10% BW
    NORMAL = "normal"  # обычное чистое → +≈5% BW
    SLOW = "slow"  # медленное, но чистое → +≈2,5% BW


_SPEED_INCREMENT = {
    AttemptSpeed.FAST: Decimal("0.10"), AttemptSpeed.NORMAL: Decimal("0.05"), AttemptSpeed.SLOW: Decimal("0.025"),
}


@dataclass(frozen=True)
class OneRmAttempt:
    load_kg: Decimal
    reps: int
    success: bool
    speed: AttemptSpeed | None = None


@dataclass(frozen=True)
class OneRmNextSet:
    set_number: int
    load_kg: Decimal
    reps: int


@dataclass(frozen=True)
class OneRmResult:
    e1rm_kg: Decimal | None  # None — не выполнен даже первый подход; результата нет
    conservative: bool  # восьмой подход успешен и явно не предельный — консервативный максимум
    sets_used: int


def next_one_rm_set(attempts: Sequence[OneRmAttempt], *, body_mass: Decimal, load_step: Decimal) -> OneRmNextSet | None:
    """Следующий подход теста по лестнице V5.6 или ``None`` — тест окончен. Лестница — продуктовая
    стандартизация, а не валидированный протокол (§8.3):

    1. BW × 5; 2. +10% BW × 3; 3. +20% BW × 1; далее только одиночные: после явно быстрого
    +≈10% BW, после обычного чистого +≈5% BW, после медленного +≈2,5% BW; проценты — вниз до шага.
    Стоп после первой неудачной/недействительной попытки и после восьмого подхода (девятого нет).
    Если округление прибавки вниз даёт 0, берётся один доступный шаг (иначе следующая попытка повторяла бы
    тот же вес) — решение реализации, отмечено в контракте."""
    if any(not attempt.success for attempt in attempts) or len(attempts) >= ONE_RM_MAX_SETS:
        return None
    number = len(attempts) + 1
    if number <= len(ONE_RM_RAMP):
        percent, reps = ONE_RM_RAMP[number - 1]
        return OneRmNextSet(number, round_down_to_step(percent * body_mass, load_step), reps)
    last = attempts[-1]
    increment = round_down_to_step(_SPEED_INCREMENT[last.speed or AttemptSpeed.SLOW] * body_mass, load_step)
    return OneRmNextSet(number, last.load_kg + max(increment, load_step), 1)


def one_rm_result(attempts: Sequence[OneRmAttempt]) -> OneRmResult:
    """Результат — последний успешно поднятый ДОПОЛНИТЕЛЬНЫЙ вес. Восьмой успешный и не медленный
    подход помечается консервативным (точный 1RM — в другой день)."""
    successful = [attempt for attempt in attempts if attempt.success]
    if not successful:
        return OneRmResult(None, False, len(attempts))
    last = successful[-1]
    conservative = len(attempts) >= ONE_RM_MAX_SETS and attempts[-1].success and last.speed is not AttemptSpeed.SLOW
    return OneRmResult(last.load_kg, conservative, len(attempts))


def one_rm_rest_ok(*, hours_since_heavy_pulling: float | None) -> bool:
    """Тест — в отдельный свежий день, не раньше чем через 48 ч после тяжёлой тяговой работы."""
    return hours_since_heavy_pulling is None or hours_since_heavy_pulling >= ONE_RM_MIN_HOURS_AFTER_HEAVY_PULLING


# --- Стартовые формулы ----------------------------------------------------------------------------


def a_start_target(volume_capacity: int) -> int:
    """§4: a = min(20, max(3, floor(0,70 × R))). Потолок 20 — только стартовая доза."""
    raw = int((A_START_COEFFICIENT * volume_capacity).to_integral_value(rounding=ROUND_FLOOR))
    return min(A_START_CAP, max(A_START_FLOOR, raw))


def b_start(reference_volume: int) -> tuple[int, int]:
    """§5: S_raw = floor(V_ref/5)+1, S = min(20, max(10, S_raw)), q = 5; при V_ref ≥ 100 — S = 20,
    q = floor(V_ref/20)+1. Возвращает (S, q)."""
    if reference_volume >= B_LARGE_REFERENCE:
        return B_MAX_SETS, reference_volume // B_MAX_SETS + 1
    raw = reference_volume // B_DEFAULT_REPS + 1
    return min(B_MAX_SETS, max(B_START_MIN_SETS, raw)), B_DEFAULT_REPS


def add_one_mandatory_rep(targets: Sequence[int]) -> tuple[tuple[int, ...], int]:
    """§4: +1 обязательное повторение ВСЕГО — в подход с наименьшей целью, при равенстве — в самый ранний.
    Возвращает (новые цели, индекс подхода)."""
    index = min(range(len(targets)), key=lambda i: (targets[i], i))
    new = list(targets)
    new[index] += 1
    return tuple(new), index


# --- Состояние ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class AVolumeState:
    targets: tuple[int, ...] | None  # None — нет R (ожидает ввода)
    additions: tuple[int, ...] = ()  # индексы подходов, получивших +1 (стек для детерминированного отката)
    red_streak: int = 0
    assistance: AssistanceSetup | None = None
    last_fact: tuple[int, ...] | None = None
    last_volume: int | None = None
    last_plan: tuple[int, ...] | None = None

    def to_dict(self) -> dict:
        return {
            "targets": list(self.targets) if self.targets is not None else None, "additions": list(self.additions),
            "red_streak": self.red_streak, "assistance": _setup_dict(self.assistance),
            "last_fact": list(self.last_fact) if self.last_fact is not None else None,
            "last_volume": self.last_volume,
            "last_plan": list(self.last_plan) if self.last_plan is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "AVolumeState":
        return cls(
            targets=tuple(data["targets"]) if data.get("targets") is not None else None,
            additions=tuple(data.get("additions") or ()), red_streak=int(data.get("red_streak") or 0),
            assistance=AssistanceSetup.from_dict(data.get("assistance")),
            last_fact=tuple(data["last_fact"]) if data.get("last_fact") is not None else None,
            last_volume=data.get("last_volume"),
            last_plan=tuple(data["last_plan"]) if data.get("last_plan") is not None else None,
        )


@dataclass(frozen=True)
class BVolumeState:
    stage: BVolumeStage
    sets: int | None = None
    reps: int | None = None
    assistance: AssistanceSetup | None = None
    reference_volume: int | None = None
    last_fact: tuple[int, ...] | None = None
    last_volume: int | None = None
    last_plan: tuple[int, int] | None = None
    last_stop_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "stage": self.stage.value, "sets": self.sets, "reps": self.reps,
            "assistance": _setup_dict(self.assistance), "reference_volume": self.reference_volume,
            "last_fact": list(self.last_fact) if self.last_fact is not None else None,
            "last_volume": self.last_volume,
            "last_plan": list(self.last_plan) if self.last_plan is not None else None,
            "last_stop_reason": self.last_stop_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "BVolumeState":
        return cls(
            stage=BVolumeStage(data["stage"]), sets=data.get("sets"), reps=data.get("reps"),
            assistance=AssistanceSetup.from_dict(data.get("assistance")), reference_volume=data.get("reference_volume"),
            last_fact=tuple(data["last_fact"]) if data.get("last_fact") is not None else None,
            last_volume=data.get("last_volume"),
            last_plan=tuple(data["last_plan"]) if data.get("last_plan") is not None else None,
            last_stop_reason=data.get("last_stop_reason"),
        )


ASSISTED_MODE = "assisted"
WEIGHTED_MODE = "weighted"


@dataclass(frozen=True)
class StrengthState:
    """Силовой блок одной тренировки (A или B) — свой вес/помощь и своя история (§8.4).

    ``mode = assisted``: 5/5/5/5/5–8 с помощью ``assistance`` (``BODYWEIGHT`` — без помощи).
    ``mode = weighted``: 5×5 (A) или 5×3 (B) с дополнительным весом ``load_kg`` (0 — масса тела;
    ``None`` — ещё нет 1RM/подтверждённого результата). Плато (§8.6) — по суммам повторений
    неполных попыток при одном весе."""

    mode: str
    assistance: AssistanceSetup | None = None
    load_kg: Decimal | None = None
    last_increase_kg: Decimal | None = None
    best_total: int | None = None
    last_total: int | None = None
    no_improvement: int = 0
    deteriorations: int = 0
    calibration_stage: int = 0
    recalibration_offered: bool = False
    last_plan_key: str | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "assistance": _setup_dict(self.assistance), "load_kg": _dec_str(self.load_kg),
            "last_increase_kg": _dec_str(self.last_increase_kg), "best_total": self.best_total,
            "last_total": self.last_total, "no_improvement": self.no_improvement,
            "deteriorations": self.deteriorations, "calibration_stage": self.calibration_stage,
            "recalibration_offered": self.recalibration_offered, "last_plan_key": self.last_plan_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "StrengthState":
        mode = data.get("mode")
        if mode not in (ASSISTED_MODE, WEIGHTED_MODE):
            raise V5StateError(f"unknown strength mode {mode!r}")
        return cls(
            mode=mode, assistance=AssistanceSetup.from_dict(data.get("assistance")), load_kg=_dec(data.get("load_kg")),
            last_increase_kg=_dec(data.get("last_increase_kg")), best_total=data.get("best_total"),
            last_total=data.get("last_total"), no_improvement=int(data.get("no_improvement") or 0),
            deteriorations=int(data.get("deteriorations") or 0),
            calibration_stage=int(data.get("calibration_stage") or 0),
            recalibration_offered=bool(data.get("recalibration_offered")), last_plan_key=data.get("last_plan_key"),
        )


def _weighted_strength(load: Decimal | None) -> StrengthState:
    return StrengthState(mode=WEIGHTED_MODE, load_kg=load)


@dataclass(frozen=True)
class EntryInputs:
    """Входные показатели V5.6 (§3). Все опциональны: недостающий вход не угадывается, а попадает в
    ``pending_inputs`` соответствующего блока.

    * ``fresh_max`` — M, свежий максимум строгих подтягиваний без веса;
    * ``volume_capacity`` — R, расчётный максимум в ТЕКУЩЕМ варианте объёмного движения (уровень 1 —
      с объёмной резиной, калибровка на ≈8–12 строгих повторений; это правило калибровки продукта);
    * ``body_mass_kg`` — BW (берётся из профиля, обновляется раз в неделю);
    * ``e1rm_kg`` — максимальный ДОПОЛНИТЕЛЬНЫЙ вес на одно строгое повторение (не выводится из M);
    * ``load_step_kg`` — доступный шаг дополнительного веса (ввод пользователя/оборудования);
    * ``known_a_targets`` — подтверждённый переносимый длинный блок A (заменяет стартовую формулу);
    * ``known_volume`` — подтверждённый сопоставимый объём (V_ref первой B вместо факта первой A);
    * ``known_strength_a_kg`` / ``known_strength_b_kg`` — недавно закрытые 5×5 / 5×3 в том же стандарте;
    * ``volume_assistance`` / ``strength_assistance`` — помощь уровня 1 (силовая — может быть
      ``BODYWEIGHT``)."""

    fresh_max: int | None = None
    volume_capacity: int | None = None
    body_mass_kg: Decimal | None = None
    e1rm_kg: Decimal | None = None
    load_step_kg: Decimal | None = None
    known_a_targets: tuple[int, ...] | None = None
    known_volume: int | None = None
    known_strength_a_kg: Decimal | None = None
    known_strength_b_kg: Decimal | None = None
    volume_assistance: AssistanceSetup | None = None
    strength_assistance: AssistanceSetup | None = None

    def to_dict(self) -> dict:
        return {
            "fresh_max": self.fresh_max, "volume_capacity": self.volume_capacity,
            "body_mass_kg": _dec_str(self.body_mass_kg), "e1rm_kg": _dec_str(self.e1rm_kg),
            "load_step_kg": _dec_str(self.load_step_kg),
            "known_a_targets": list(self.known_a_targets) if self.known_a_targets is not None else None,
            "known_volume": self.known_volume, "known_strength_a_kg": _dec_str(self.known_strength_a_kg),
            "known_strength_b_kg": _dec_str(self.known_strength_b_kg),
            "volume_assistance": _setup_dict(self.volume_assistance),
            "strength_assistance": _setup_dict(self.strength_assistance),
        }

    @classmethod
    def from_dict(cls, data: Mapping | None) -> "EntryInputs":
        data = data or {}
        return cls(
            fresh_max=data.get("fresh_max"), volume_capacity=data.get("volume_capacity"),
            body_mass_kg=_dec(data.get("body_mass_kg")), e1rm_kg=_dec(data.get("e1rm_kg")),
            load_step_kg=_dec(data.get("load_step_kg")),
            known_a_targets=tuple(data["known_a_targets"]) if data.get("known_a_targets") is not None else None,
            known_volume=data.get("known_volume"), known_strength_a_kg=_dec(data.get("known_strength_a_kg")),
            known_strength_b_kg=_dec(data.get("known_strength_b_kg")),
            volume_assistance=AssistanceSetup.from_dict(data.get("volume_assistance")),
            strength_assistance=AssistanceSetup.from_dict(data.get("strength_assistance")),
        )


@dataclass(frozen=True)
class V5State:
    level: ProgramLevel | None  # None — нет M: уровень не классифицирован
    next_role: WorkoutRole
    volume_a: AVolumeState
    volume_b: BVolumeState
    strength_a: StrengthState | None  # None — уровень не классифицирован
    strength_b: StrengthState | None
    inputs: EntryInputs
    qualification: dict | None = None  # {"signal": "fresh_max" | "in_program", ...}
    sessions_completed: int = 0
    both_deteriorated_streak: int = 0
    recovery_check_required: bool = False
    # Записи «смена помощи ждёт подтверждения»: {"block", "intent", "proposed" (резина по порядку списка или
    # None — следующую ступень выбирает пользователь)}. Пока запись есть, занятие этой роли не стартует, а
    # блок продолжает хранить прежнюю ПОДТВЕРЖДЁННУЮ помощь.
    assistance_pending: tuple[dict, ...] = ()
    one_rm_tests: tuple[dict, ...] = ()  # история тестов 1RM (append-only факты)

    def to_dict(self) -> dict:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "strategy_type": "step",
            "program_version": PROGRAM_VERSION,
            "level": self.level.value if self.level is not None else None,
            "next_role": self.next_role.value,
            "volume_a": self.volume_a.to_dict(),
            "volume_b": self.volume_b.to_dict(),
            "strength_a": self.strength_a.to_dict() if self.strength_a is not None else None,
            "strength_b": self.strength_b.to_dict() if self.strength_b is not None else None,
            "inputs": self.inputs.to_dict(),
            "qualification": self.qualification,
            "sessions_completed": self.sessions_completed,
            "both_deteriorated_streak": self.both_deteriorated_streak,
            "recovery_check_required": self.recovery_check_required,
            "assistance_pending": list(self.assistance_pending),
            "one_rm_tests": list(self.one_rm_tests),
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "V5State":
        if not is_v5_state(data):
            raise V5StateError("not a pullups_v5_6 progression state")
        return cls(
            level=ProgramLevel(data["level"]) if data.get("level") is not None else None,
            next_role=WorkoutRole(data["next_role"]),
            volume_a=AVolumeState.from_dict(data["volume_a"]),
            volume_b=BVolumeState.from_dict(data["volume_b"]),
            strength_a=StrengthState.from_dict(data["strength_a"]) if data.get("strength_a") is not None else None,
            strength_b=StrengthState.from_dict(data["strength_b"]) if data.get("strength_b") is not None else None,
            inputs=EntryInputs.from_dict(data.get("inputs")),
            qualification=data.get("qualification"),
            sessions_completed=int(data.get("sessions_completed") or 0),
            both_deteriorated_streak=int(data.get("both_deteriorated_streak") or 0),
            recovery_check_required=bool(data.get("recovery_check_required")),
            assistance_pending=tuple(data.get("assistance_pending") or ()),
            one_rm_tests=tuple(data.get("one_rm_tests") or ()),
        )

    def strength(self, role: WorkoutRole) -> StrengthState | None:
        return self.strength_a if role is WorkoutRole.A else self.strength_b


def is_v5_state(progression_state: Mapping | None) -> bool:
    return bool(progression_state) and progression_state.get("program_version") == PROGRAM_VERSION


def program_version_of(progression_state: Mapping | None) -> str:
    """Версия программы инклюзии. Состояние без ``program_version`` — устаревшая STEP-программа
    (бот-эпоха / Mini App до V5.6), она читается и исполняется прежним кодом и в V5.6 не переводится."""
    if is_v5_state(progression_state):
        return PROGRAM_VERSION
    return LEGACY_PROGRAM_VERSION


# --- Стартовое состояние --------------------------------------------------------------------------


def _transition_volume() -> tuple[AVolumeState, BVolumeState]:
    return (
        AVolumeState(targets=(TRANSITION_A_TARGET,) * A_VOLUME_SETS, assistance=BODYWEIGHT),
        BVolumeState(stage=BVolumeStage.TRANSITION, sets=TRANSITION_B_SETS, reps=TRANSITION_B_START_REPS, assistance=BODYWEIGHT),
    )


def _weighted_start(inputs: EntryInputs, role: WorkoutRole) -> StrengthState:
    """Приоритет входа силы (§8): 1) недавний подтверждённый 5×5/5×3; 2) 1RM; иначе — ждём ввода."""
    known = inputs.known_strength_a_kg if role is WorkoutRole.A else inputs.known_strength_b_kg
    if known is not None:
        return _weighted_strength(known)
    if inputs.e1rm_kg is not None and inputs.body_mass_kg is not None and inputs.load_step_kg is not None:
        e5, e3 = initial_weighted_loads(
            body_mass=inputs.body_mass_kg, e1rm=inputs.e1rm_kg, load_step=inputs.load_step_kg,
        )
        return _weighted_strength(e5 if role is WorkoutRole.A else e3)
    return _weighted_strength(None)


def _b_from_known(inputs: EntryInputs, assistance: AssistanceSetup | None) -> BVolumeState:
    if inputs.known_volume is not None:
        sets, reps = b_start(inputs.known_volume)
        return BVolumeState(
            stage=BVolumeStage.STANDARD, sets=sets, reps=reps, assistance=assistance, reference_volume=inputs.known_volume,
        )
    return BVolumeState(stage=BVolumeStage.PENDING_REFERENCE, assistance=assistance)


def initial_state(inputs: EntryInputs) -> V5State:
    """Стартовое состояние V5.6 по входам (§3, §4, §5, §8.2). Классификация уровня — только по M:

    * M ≥ 15 — уровень 2 сразу, объём по стандартным формулам (R = M: текущий вариант — масса тела);
    * 10 ≤ M ≤ 14 — допуск по свежему M, переходная неделя: A 5/5/5/5+, B 10×3;
    * M < 10 — уровень 1: объём с резиной (R — способность с объёмной резиной), сила 5/5/5/5/5–8;
    * M неизвестен — уровень не классифицирован, всё ждёт ``fresh_max``.
    Подтверждённая история (``known_*``) сильнее формулы."""
    if inputs.fresh_max is None:
        return V5State(
            level=None, next_role=WorkoutRole.A, volume_a=AVolumeState(targets=None),
            volume_b=BVolumeState(stage=BVolumeStage.PENDING_REFERENCE), strength_a=None, strength_b=None,
            inputs=inputs,
        )
    m = inputs.fresh_max
    if m >= STANDARD_VOLUME_FROM_FRESH_MAX:
        targets = inputs.known_a_targets or (a_start_target(m),) * A_VOLUME_SETS
        return V5State(
            level=ProgramLevel.WEIGHTED, next_role=WorkoutRole.A,
            volume_a=AVolumeState(targets=tuple(targets), assistance=BODYWEIGHT),
            volume_b=_b_from_known(inputs, BODYWEIGHT),
            strength_a=_weighted_start(inputs, WorkoutRole.A), strength_b=_weighted_start(inputs, WorkoutRole.B),
            inputs=inputs, qualification={"signal": "fresh_max", "fresh_max": m},
        )
    if m >= QUALIFY_FRESH_MAX:
        volume_a, volume_b = _transition_volume()
        return V5State(
            level=ProgramLevel.TRANSITION, next_role=WorkoutRole.A, volume_a=volume_a, volume_b=volume_b,
            strength_a=_weighted_start(inputs, WorkoutRole.A), strength_b=_weighted_start(inputs, WorkoutRole.B),
            inputs=inputs, qualification={"signal": "fresh_max", "fresh_max": m},
        )
    if inputs.known_a_targets is not None:
        targets: tuple[int, ...] | None = tuple(inputs.known_a_targets)
    elif inputs.volume_capacity is not None:
        targets = (a_start_target(inputs.volume_capacity),) * A_VOLUME_SETS
    else:
        targets = None
    assisted = StrengthState(mode=ASSISTED_MODE, assistance=inputs.strength_assistance)
    return V5State(
        level=ProgramLevel.ASSISTED, next_role=WorkoutRole.A,
        volume_a=AVolumeState(targets=targets, assistance=inputs.volume_assistance),
        volume_b=_b_from_known(inputs, inputs.volume_assistance),
        strength_a=assisted, strength_b=assisted, inputs=inputs,
    )


def apply_inputs(state: V5State, update: EntryInputs) -> V5State:
    """Дописывает входы в состояние ТОЛЬКО вперёд и только там, где блок их ждёт (выданные рецепты
    живут в снимках сессий и не меняются). До первой завершённой сессии — пересчёт стартового
    состояния с объединёнными входами; после — заполнение ожидающих слотов (вес силы после 1RM,
    помощь, выбор следующей резины)."""
    merged = _merge_inputs(state.inputs, update)
    if state.sessions_completed == 0:
        return replace(initial_state(merged), one_rm_tests=state.one_rm_tests)
    new = replace(state, inputs=merged)
    for role in WorkoutRole:
        strength = new.strength(role)
        if strength is None or strength.mode != WEIGHTED_MODE:
            continue
        if strength.load_kg is None:
            new = _with_strength(new, role, replace(strength, load_kg=_weighted_start(merged, role).load_kg))
        elif strength.recalibration_offered and update.e1rm_kg is not None:
            # §8.6: после калибровки и трёх попыток без прогресса предложен свежий 1RM — пользователь его
            # прошёл: рабочий вес пересчитывается из нового 1RM (вперёд), история плато сбрасывается.
            fresh = replace(merged, known_strength_a_kg=None, known_strength_b_kg=None)
            load = _weighted_start(fresh, role).load_kg
            if load is not None:
                new = _with_strength(new, role, StrengthState(mode=WEIGHTED_MODE, load_kg=load))
    # Стартовые записи помощи уровня 1 (после первой сессии — только там, где смена не ждёт подтверждения;
    # ожидающая смена подтверждается confirm_assistance, а не общим вводом).
    pending_blocks = {entry["block"] for entry in new.assistance_pending}
    if update.volume_assistance is not None and new.level is ProgramLevel.ASSISTED:
        if VOLUME_A_BLOCK not in pending_blocks:
            new = replace(new, volume_a=replace(new.volume_a, assistance=update.volume_assistance))
        if VOLUME_B_BLOCK not in pending_blocks:
            new = replace(new, volume_b=replace(new.volume_b, assistance=update.volume_assistance))
    if update.strength_assistance is not None:
        for role, block in ((WorkoutRole.A, STRENGTH_A_BLOCK), (WorkoutRole.B, STRENGTH_B_BLOCK)):
            strength = new.strength(role)
            if strength is not None and strength.mode == ASSISTED_MODE and block not in pending_blocks:
                new = _with_strength(new, role, replace(strength, assistance=update.strength_assistance))
    return new


def confirm_assistance(state: V5State, block: str, setup: AssistanceSetup) -> V5State:
    """Пользователь подтвердил ПОЛНУЮ запись помощи блока (модель, цвет, крепление, положение — или «без
    помощи»). Снимает ожидание этого блока; следующая одноимённая тренировка идёт с этой помощью.
    Неполная запись не принимается — готовой к использованию она не считается."""
    if block not in ASSISTANCE_BLOCKS:
        raise V5StateError(f"unknown assistance block {block!r}")
    if not setup.is_complete:
        raise V5StateError("assistance setup is incomplete: model, colour, attachment and foot/knee position are required")
    if block == VOLUME_A_BLOCK:
        new = replace(state, volume_a=replace(state.volume_a, assistance=setup))
    elif block == VOLUME_B_BLOCK:
        new = replace(state, volume_b=replace(state.volume_b, assistance=setup))
    else:
        role = WorkoutRole.A if block == STRENGTH_A_BLOCK else WorkoutRole.B
        strength = state.strength(role)
        if strength is None or strength.mode != ASSISTED_MODE:
            raise V5StateError(f"{block} has no assistance in its current mode")
        new = _with_strength(state, role, replace(strength, assistance=setup))
    return replace(new, assistance_pending=tuple(e for e in new.assistance_pending if e["block"] != block))


def _assistance_change(
    block: str, current: AssistanceSetup | None, step: AssistanceStep,
) -> tuple[AssistanceSetup | None, dict | None]:
    """Применить шаг помощи или сохранить НАМЕРЕНИЕ до подтверждения. Готовая запись (масса тела или
    полностью подтверждённая резина) применяется сразу; иначе блок сохраняет прежнюю подтверждённую
    помощь, а запись ожидания хранит намерение и предложенную по порядку резину (или None)."""
    if step.intent is AssistanceIntent.KEEP or step.setup == current and not step.selection_required:
        return current, None
    if not step.selection_required and step.setup is not None and step.setup.is_complete:
        return step.setup, None
    proposed = None if step.selection_required else step.setup
    return current, {"block": block, "intent": step.intent.value, "proposed": _setup_dict(proposed)}


def record_one_rm_test(state: V5State, attempts: Sequence[OneRmAttempt], *, performed_at: str) -> tuple[V5State, OneRmResult]:
    """Тест 1RM — отдельный факт (append-only); результат становится E1RM и заполняет ожидающие веса
    силы (выданные рецепты не меняются). Тест без успешного подхода результата не даёт."""
    result = one_rm_result(attempts)
    record = {
        "performed_at": performed_at,
        "attempts": [
            {"load_kg": _dec_str(a.load_kg), "reps": a.reps, "success": a.success,
             "speed": a.speed.value if a.speed is not None else None}
            for a in attempts
        ],
        "e1rm_kg": _dec_str(result.e1rm_kg), "conservative": result.conservative,
    }
    new = replace(state, one_rm_tests=(*state.one_rm_tests, record))
    if result.e1rm_kg is not None:
        new = apply_inputs(new, EntryInputs(e1rm_kg=result.e1rm_kg))
    return new, result


def clear_recovery_check(state: V5State) -> V5State:
    """§9: после проверки восстановления и внешней тяговой нагрузки прибавки снова назначаются."""
    return replace(state, recovery_check_required=False, both_deteriorated_streak=0)


def _merge_inputs(base: EntryInputs, update: EntryInputs) -> EntryInputs:
    values = {}
    for name in EntryInputs.__dataclass_fields__:
        new_value = getattr(update, name)
        values[name] = new_value if new_value is not None else getattr(base, name)
    return EntryInputs(**values)


def _with_strength(state: V5State, role: WorkoutRole, strength: StrengthState) -> V5State:
    return replace(state, strength_a=strength) if role is WorkoutRole.A else replace(state, strength_b=strength)


# --- Прескрипция занятия --------------------------------------------------------------------------


@dataclass(frozen=True)
class SetPrescription:
    set_number: int
    target_reps: int  # обязательная (минимальная) цель
    marker: SetMarker
    rest_after_seconds: int | None  # None — последний подход блока
    cap_reps: int | None = None  # жёсткий потолок (контрольный подход 5–8)

    def to_dict(self) -> dict:
        return {
            "set_number": self.set_number, "target_reps": self.target_reps, "marker": self.marker.value,
            "rest_after_seconds": self.rest_after_seconds, "cap_reps": self.cap_reps,
        }


@dataclass(frozen=True)
class BlockPrescription:
    block_role: BlockRole
    sets: tuple[SetPrescription, ...]
    rest_seconds: int
    assistance: AssistanceSetup | None
    external_load_kg: Decimal | None  # None у объёма и у силы с помощью; 0 — масса тела
    stop_rule: dict | None = None  # B: {"stop_at_or_below": 2, "continue_at": 3}
    intermediate_goal: int | None = None  # B: прошлый факт + 1, только отображение
    stage: str | None = None  # B: transition / standard
    display: str = ""

    def to_dict(self) -> dict:
        return {
            "block_role": self.block_role.value, "sets": [s.to_dict() for s in self.sets],
            "rest_seconds": self.rest_seconds, "assistance": _setup_dict(self.assistance),
            "external_load_kg": _dec_str(self.external_load_kg), "stop_rule": self.stop_rule,
            "intermediate_goal": self.intermediate_goal, "stage": self.stage, "display": self.display,
        }


@dataclass(frozen=True)
class SessionPrescription:
    role: WorkoutRole
    level: ProgramLevel
    volume: BlockPrescription
    strength: BlockPrescription
    inter_block_rest_seconds: int
    source_inputs: dict

    def to_dict(self) -> dict:
        return {
            "program_version": PROGRAM_VERSION,
            "workout_role": self.role.value,
            "level": self.level.value,
            "structure": ["warm_up", "volume", "inter_block_rest", "strength_ramp_up", "strength"],
            # Разминка и подводка названы в документе V5.6 (§1 п. 1 и п. 4), но их содержание не задано —
            # здесь они явно «не предписаны», а не придуманы. Подводка не входит в рабочие подходы (§8.4).
            "warm_up": dict(WARM_UP_SPEC),
            "strength_ramp_up": dict(STRENGTH_RAMP_UP_SPEC),
            "blocks": [self.volume.to_dict(), self.strength.to_dict()],
            "inter_block_rest_seconds": self.inter_block_rest_seconds,
            "source_inputs": self.source_inputs,
        }


@dataclass(frozen=True)
class PrescriptionPending:
    """Прескрипция невозможна без ввода — какие входы нужны. Ничего не подставляется молча."""

    role: WorkoutRole
    missing: tuple[PendingInput, ...]


def pending_inputs(state: V5State, role: WorkoutRole | None = None) -> tuple[PendingInput, ...]:
    """Чего не хватает для прескрипции занятия ``role`` (по умолчанию — следующего)."""
    role = role or state.next_role
    missing: list[PendingInput] = []
    if state.level is None:
        return (PendingInput.FRESH_MAX,)
    if state.recovery_check_required:
        missing.append(PendingInput.RECOVERY_CHECK)
    if any(entry["block"] in _role_blocks(role) for entry in state.assistance_pending):
        missing.append(PendingInput.ASSISTANCE_CONFIRMATION)
    volume_assistance = state.volume_a.assistance if role is WorkoutRole.A else state.volume_b.assistance
    if role is WorkoutRole.A:
        if state.volume_a.targets is None:
            missing.append(PendingInput.VOLUME_CAPACITY)
    elif state.volume_b.stage is BVolumeStage.PENDING_REFERENCE:
        # Первая B — от факта первой A или от подтверждённого объёма (known_volume).
        missing.append(PendingInput.VOLUME_REFERENCE)
    if volume_assistance is None or not volume_assistance.is_complete:
        missing.append(PendingInput.VOLUME_ASSISTANCE)
    strength = state.strength(role)
    if strength is not None and strength.mode == ASSISTED_MODE and (
        strength.assistance is None or not strength.assistance.is_complete
    ):
        missing.append(PendingInput.STRENGTH_ASSISTANCE)
    if strength is not None and strength.mode == WEIGHTED_MODE and strength.load_kg is None:
        if state.inputs.e1rm_kg is None:
            missing.append(PendingInput.ONE_REP_MAX)
        if state.inputs.body_mass_kg is None:
            missing.append(PendingInput.BODY_MASS)
        if state.inputs.load_step_kg is None:
            missing.append(PendingInput.LOAD_STEP)
    return tuple(dict.fromkeys(missing))


def _a_volume_block(state: V5State) -> BlockPrescription:
    targets = state.volume_a.targets
    sets = tuple(
        SetPrescription(
            set_number=i + 1, target_reps=target,
            marker=SetMarker.AMRAP if i == len(targets) - 1 else SetMarker.WORKING,
            rest_after_seconds=A_VOLUME_REST_SECONDS if i < len(targets) - 1 else None,
        )
        for i, target in enumerate(targets)
    )
    return BlockPrescription(
        block_role=BlockRole.A_VOLUME, sets=sets, rest_seconds=A_VOLUME_REST_SECONDS,
        assistance=state.volume_a.assistance, external_load_kg=None,
        display="/".join(str(t) for t in targets) + "+",
    )


def _b_volume_block(state: V5State) -> BlockPrescription:
    volume = state.volume_b
    sets = tuple(
        SetPrescription(
            set_number=i + 1, target_reps=volume.reps, marker=SetMarker.DYNAMIC,
            rest_after_seconds=B_VOLUME_REST_SECONDS if i < volume.sets - 1 else None,
        )
        for i in range(volume.sets)
    )
    previous_plan = (volume.sets, volume.reps)
    intermediate = (
        volume.last_volume + 1
        if volume.last_volume is not None and volume.last_plan == previous_plan
        and volume.last_volume < volume.sets * volume.reps else None
    )
    return BlockPrescription(
        block_role=BlockRole.B_VOLUME, sets=sets, rest_seconds=B_VOLUME_REST_SECONDS,
        assistance=volume.assistance, external_load_kg=None,
        stop_rule={"stop_at_or_below": B_STOP_AT_OR_BELOW, "continue_at": B_STOP_AT_OR_BELOW + 1, "stop_on_invalid_technique": True},
        intermediate_goal=intermediate, stage=volume.stage.value, display=f"{volume.sets}×{volume.reps}",
    )


def _strength_block(strength: StrengthState, role: WorkoutRole) -> BlockPrescription:
    if strength.mode == ASSISTED_MODE:
        sets = tuple(
            SetPrescription(
                set_number=i + 1, target_reps=ASSISTED_STRENGTH_TARGET,
                marker=SetMarker.CONTROL if i == ASSISTED_STRENGTH_SETS - 1 else SetMarker.WORKING,
                rest_after_seconds=STRENGTH_REST_SECONDS if i < ASSISTED_STRENGTH_SETS - 1 else None,
                cap_reps=ASSISTED_CONTROL_CAP if i == ASSISTED_STRENGTH_SETS - 1 else None,
            )
            for i in range(ASSISTED_STRENGTH_SETS)
        )
        return BlockPrescription(
            block_role=BlockRole.ASSISTED_STRENGTH, sets=sets, rest_seconds=STRENGTH_REST_SECONDS,
            assistance=strength.assistance, external_load_kg=None, display="5/5/5/5/5–8",
        )
    count, reps = (A_STRENGTH_SETS, A_STRENGTH_REPS) if role is WorkoutRole.A else (B_STRENGTH_SETS, B_STRENGTH_REPS)
    sets = tuple(
        SetPrescription(
            set_number=i + 1, target_reps=reps, marker=SetMarker.WORKING,
            rest_after_seconds=STRENGTH_REST_SECONDS if i < count - 1 else None,
        )
        for i in range(count)
    )
    load = strength.load_kg
    load_text = "масса тела" if load == 0 else f"+{_dec_str(load)} кг"
    return BlockPrescription(
        block_role=BlockRole.A_WEIGHTED_STRENGTH if role is WorkoutRole.A else BlockRole.B_WEIGHTED_STRENGTH,
        sets=sets, rest_seconds=STRENGTH_REST_SECONDS, assistance=BODYWEIGHT, external_load_kg=load,
        display=f"{count}×{reps} {load_text}",
    )


def prescribe_session(state: V5State, role: WorkoutRole | None = None) -> SessionPrescription | PrescriptionPending:
    """Рецепт занятия A или B (по умолчанию — следующего по последовательности). Без нужных входов —
    ``PrescriptionPending``: старт занятия блокируется, а не подставляется догадка."""
    role = role or state.next_role
    missing = pending_inputs(state, role)
    if missing:
        return PrescriptionPending(role=role, missing=missing)
    volume = _a_volume_block(state) if role is WorkoutRole.A else _b_volume_block(state)
    strength = _strength_block(state.strength(role), role)
    return SessionPrescription(
        role=role, level=state.level, volume=volume, strength=strength,
        inter_block_rest_seconds=INTER_BLOCK_REST_SECONDS,
        source_inputs={
            **state.inputs.to_dict(),
            "b_reference_volume": state.volume_b.reference_volume if role is WorkoutRole.B else None,
            "qualification": state.qualification,
        },
    )


# --- Результат занятия ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockResult:
    """Факт блока: повторения ПЛАНОВЫХ подходов по порядку (``None`` — подход не выполнен), и явные
    подтверждения пользователя. ``technique_valid`` / ``rest_within_limit`` = ``None`` — неизвестно:
    правило, требующее валидной техники/отдыха, неизвестное значение валидным НЕ считает."""

    reps: tuple[int | None, ...]
    technique_valid: bool | None = None
    rest_within_limit: bool | None = None


@dataclass(frozen=True)
class SessionResult:
    volume: BlockResult
    strength: BlockResult


@dataclass(frozen=True)
class BlockOutcome:
    """Типизированный итог прогрессии одного блока: роль блока, решение и причина."""

    block_role: BlockRole
    decision: str
    reason: str | None = None
    fact_volume: int | None = None
    assistance_intent: AssistanceIntent | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "block_role": self.block_role.value, "decision": self.decision, "reason": self.reason,
            "fact_volume": self.fact_volume,
            "assistance_intent": self.assistance_intent.value if self.assistance_intent is not None else None,
            "details": self.details,
        }


@dataclass(frozen=True)
class SessionAdvance:
    state: V5State
    volume: BlockOutcome
    strength: BlockOutcome
    qualified: bool


def _prescribed_targets(block: Mapping) -> tuple[int, ...]:
    return tuple(int(s["target_reps"]) for s in block["sets"])


def _performed(reps: Sequence[int | None]) -> list[int]:
    return [r for r in reps if r is not None]


class AOutcome(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNCONFIRMED = "unconfirmed"  # запас +2 есть, но техника не подтверждена — как жёлтый (повтор плана)


def classify_a_volume(targets: Sequence[int], result: BlockResult) -> AOutcome:
    """§4: зелёный — первые три закрыты, последний ≥ p4+2 и техника сохранена; жёлтый — первые три
    закрыты, последний p4 или p4+1; красный — не закрыта цель любого из четырёх подходов."""
    reps = list(result.reps) + [None] * (len(targets) - len(result.reps))
    if any(actual is None or actual < target for actual, target in zip(reps, targets, strict=False)):
        return AOutcome.RED
    if reps[-1] >= targets[-1] + A_GREEN_MARGIN:
        return AOutcome.GREEN if result.technique_valid is True else AOutcome.UNCONFIRMED
    return AOutcome.YELLOW


def _advance_a_volume(state: V5State, block: Mapping, result: BlockResult, *, increases_paused: bool, ladder):
    volume = state.volume_a
    targets = _prescribed_targets(block)
    outcome = classify_a_volume(targets, result)
    fact = tuple(_performed(result.reps))
    fact_volume = sum(fact)
    new = replace(volume, last_fact=fact, last_volume=fact_volume, last_plan=targets)
    decision, reason, intent, details = "repeat", outcome.value, None, {"outcome": outcome.value}
    if outcome is AOutcome.GREEN and volume.targets == targets:
        if increases_paused:
            reason = "recovery_check_required"
            new = replace(new, red_streak=0)
        else:
            new_targets, index = add_one_mandatory_rep(targets)
            new = replace(new, targets=new_targets, additions=(*volume.additions, index), red_streak=0)
            decision, details = "add_mandatory_rep", {**details, "set_index": index, "targets_after": list(new_targets)}
    elif outcome is AOutcome.RED:
        streak = volume.red_streak + 1
        new = replace(new, red_streak=streak)
        if streak >= A_RED_ROLLBACK_STREAK:
            if volume.additions:
                index = volume.additions[-1]
                rolled = list(new.targets)
                rolled[index] -= 1
                new = replace(new, targets=tuple(rolled), additions=volume.additions[:-1], red_streak=0)
                decision, details = "rollback_last_addition", {**details, "set_index": index, "targets_after": rolled}
            else:
                # Откатывать нечего (план стартовый): по §4 — «или усиливается помощь». Конкретную резину
                # программа не угадывает: шаг по личному списку или выбор пользователя.
                step = step_assistance(volume.assistance, AssistanceIntent.INCREASE, ladder)
                applied, pending = _assistance_change(VOLUME_A_BLOCK, volume.assistance, step)
                new = replace(new, assistance=applied, red_streak=0)
                decision, intent = "increase_assistance", AssistanceIntent.INCREASE
                details = {**details, "assistance_after": _setup_dict(applied), "pending_assistance": pending}
                if pending is not None:
                    reason = "assistance_confirmation_required"
    else:
        new = replace(new, red_streak=0)
    return new, BlockOutcome(BlockRole.A_VOLUME, decision, reason, fact_volume, intent, details)


class BStopReason(StrEnum):
    PLANNED_SETS_DONE = "planned_sets_done"
    LOW_REPS = "low_reps"  # подход с ≤ 2 повторениями — записан, блок завершён
    TECHNIQUE = "technique"
    ENDED_EARLY = "ended_early"  # подход не выполнен (движок v1 не знает стоп-правила, см. LIVE seam)


def b_volume_fact(planned_sets: int, result: BlockResult) -> tuple[tuple[int, ...], BStopReason]:
    """§5–§6: факт B по стоп-правилу. 3 повторения — продолжать; ≤ 2 — подход записывается (входит в
    VB_fact) и блок завершается; подходы после остановки не учитываются. Нарушение техники тоже
    завершает блок."""
    counted: list[int] = []
    # Подходы оборвались, а техника блока нарушена — это остановка по технике (движок #306 завершает блок
    # по «техника нарушена»), а не досрочный выход.
    cut_short = BStopReason.TECHNIQUE if result.technique_valid is False else BStopReason.ENDED_EARLY
    for actual in result.reps[:planned_sets]:
        if actual is None:
            return tuple(counted), cut_short
        counted.append(actual)
        if actual <= B_STOP_AT_OR_BELOW:
            return tuple(counted), BStopReason.LOW_REPS
    if len(counted) < planned_sets:
        return tuple(counted), cut_short
    if result.technique_valid is False:
        return tuple(counted), BStopReason.TECHNIQUE
    return tuple(counted), BStopReason.PLANNED_SETS_DONE


def _advance_b_volume(state: V5State, block: Mapping, result: BlockResult, *, increases_paused: bool):
    volume = state.volume_b
    planned_sets = len(block["sets"])
    q = int(block["sets"][0]["target_reps"])
    fact, stop = b_volume_fact(planned_sets, result)
    fact_volume = sum(fact)
    closed = stop is BStopReason.PLANNED_SETS_DONE and all(r >= q for r in fact)
    new = replace(volume, last_fact=fact, last_volume=fact_volume, last_plan=(planned_sets, q), last_stop_reason=stop.value)
    details = {"stop_reason": stop.value, "plan": [planned_sets, q]}
    plan_is_current = (volume.sets, volume.reps) == (planned_sets, q)
    if not closed or not plan_is_current:
        return new, BlockOutcome(
            BlockRole.B_VOLUME, "hold", "plan_not_closed", fact_volume, None,
            {**details, "intermediate_goal": fact_volume + 1},
        ), False
    if result.technique_valid is not True or result.rest_within_limit is not True:
        return new, BlockOutcome(BlockRole.B_VOLUME, "hold", "standard_unconfirmed", fact_volume, None, details), False
    if increases_paused:
        return new, BlockOutcome(BlockRole.B_VOLUME, "hold", "recovery_check_required", fact_volume, None, details), False
    left_transition = False
    if volume.stage is BVolumeStage.TRANSITION:
        if q < B_DEFAULT_REPS:
            new = replace(new, reps=q + 1)
        else:
            new = replace(new, stage=BVolumeStage.STANDARD, sets=planned_sets + 1)
            left_transition = True
    elif planned_sets < B_MAX_SETS:
        new = replace(new, sets=planned_sets + 1)
    else:
        new = replace(new, reps=q + 1)
    details = {**details, "plan_after": [new.sets, new.reps]}
    return new, BlockOutcome(BlockRole.B_VOLUME, "advance", None, fact_volume, None, details), left_transition


def _assisted_strength_decision(result: BlockResult) -> tuple[AssistanceIntent, str | None, bool]:
    """§8.2: первые четыре закрыты и пятый = 8 → уменьшить помощь; пятый 5–7 → та же помощь; недобор
    в первых четырёх или пятый < 5 → увеличить помощь. Возвращает (намерение, причина, «8 из 8»)."""
    reps = list(result.reps) + [None] * (ASSISTED_STRENGTH_SETS - len(result.reps))
    first_four, control = reps[: ASSISTED_STRENGTH_SETS - 1], reps[ASSISTED_STRENGTH_SETS - 1]
    if any(r is None or r < ASSISTED_STRENGTH_TARGET for r in first_four) or control is None or control < ASSISTED_STRENGTH_TARGET:
        return AssistanceIntent.INCREASE, None, False
    if min(control, ASSISTED_CONTROL_CAP) >= ASSISTED_CONTROL_CAP:
        if result.technique_valid is not True:
            return AssistanceIntent.KEEP, "technique_unconfirmed", True
        return AssistanceIntent.DECREASE, None, True
    return AssistanceIntent.KEEP, None, False


def _advance_assisted_strength(state: V5State, role: WorkoutRole, result: BlockResult, *, increases_paused: bool, ladder):
    strength = state.strength(role)
    intent, reason, reached_cap = _assisted_strength_decision(result)
    capped = [min(r, ASSISTED_CONTROL_CAP) for r in _performed(result.reps[:ASSISTED_STRENGTH_SETS])]
    details = {
        "workout_role": role.value, "assistance_before": _setup_dict(strength.assistance), "total": sum(capped),
    }
    if reached_cap and intent is AssistanceIntent.DECREASE and strength.assistance is not None and strength.assistance.is_bodyweight:
        if result.rest_within_limit is not True:
            return strength, BlockOutcome(
                BlockRole.ASSISTED_STRENGTH, "keep", "rest_unconfirmed", None, AssistanceIntent.KEEP, details,
            ), False
        return strength, BlockOutcome(BlockRole.ASSISTED_STRENGTH, "qualify", None, None, None, details), True
    if intent is AssistanceIntent.DECREASE and increases_paused:
        intent, reason = AssistanceIntent.KEEP, "recovery_check_required"
    step = step_assistance(strength.assistance, intent, ladder)
    block = STRENGTH_A_BLOCK if role is WorkoutRole.A else STRENGTH_B_BLOCK
    applied, pending = _assistance_change(block, strength.assistance, step)
    new = replace(strength, assistance=applied)
    details = {**details, "assistance_after": _setup_dict(applied), "pending_assistance": pending}
    if pending is not None:
        reason = "assistance_confirmation_required"
    return new, BlockOutcome(BlockRole.ASSISTED_STRENGTH, intent.value, reason, None, intent, details), False


def _weighted_targets(role: WorkoutRole) -> tuple[int, int]:
    return (A_STRENGTH_SETS, A_STRENGTH_REPS) if role is WorkoutRole.A else (B_STRENGTH_SETS, B_STRENGTH_REPS)


def _advance_weighted_strength(
    state: V5State, role: WorkoutRole, block: Mapping, result: BlockResult, *, body_mass: Decimal | None,
    increases_paused: bool,
):
    strength = state.strength(role)
    block_role = BlockRole.A_WEIGHTED_STRENGTH if role is WorkoutRole.A else BlockRole.B_WEIGHTED_STRENGTH
    count, reps_target = _weighted_targets(role)
    prescribed_load = _dec(block.get("external_load_kg"))
    reps = list(result.reps) + [None] * (count - len(result.reps))
    # Лишние случайные повторения не ускоряют прогрессию: в расчёт идёт не больше цели (§8.5).
    capped = [min(r, reps_target) if r is not None else 0 for r in reps[:count]]
    total = sum(capped)
    complete = all(r is not None and r >= reps_target for r in reps[:count])
    details = {"workout_role": role.value, "load_kg": _dec_str(prescribed_load), "total": total}
    if prescribed_load != strength.load_kg:
        # Вес уже изменился вперёд (например, ввод 1RM после выдачи рецепта) — этот факт к новому весу не относится.
        return strength, BlockOutcome(block_role, "hold", "load_changed_since_prescription", None, None, details)
    if complete:
        if result.technique_valid is not True or result.rest_within_limit is not True:
            return strength, BlockOutcome(block_role, "hold", "standard_unconfirmed", None, None, details)
        if increases_paused:
            return strength, BlockOutcome(block_role, "hold", "recovery_check_required", None, None, details)
        step = state.inputs.load_step_kg
        delta = (
            load_increment(body_mass=body_mass, working_load=strength.load_kg, load_step=step)
            if body_mass is not None and step is not None else None
        )
        if delta is None:
            return strength, BlockOutcome(block_role, "hold", "load_increment_unavailable", None, None, details)
        new = replace(
            strength, load_kg=strength.load_kg + delta, last_increase_kg=delta, best_total=None, last_total=None,
            no_improvement=0, deteriorations=0, calibration_stage=0, recalibration_offered=False,
        )
        return new, BlockOutcome(
            block_role, "increase_load", None, None, None,
            {**details, "delta_kg": _dec_str(delta), "load_after_kg": _dec_str(new.load_kg), "body_mass_kg": _dec_str(body_mass)},
        )
    # Неполное выполнение: тот же вес и план; плато — §8.6.
    if strength.last_total is None:
        no_improvement, deteriorations, best = 1, 0, total
    else:
        improved = strength.best_total is None or total > strength.best_total
        no_improvement = 1 if improved else strength.no_improvement + 1
        deteriorations = strength.deteriorations + 1 if total < strength.last_total else 0
        best = max(total, strength.best_total or 0)
    new = replace(strength, best_total=best, last_total=total, no_improvement=no_improvement, deteriorations=deteriorations)
    details = {**details, "no_improvement": no_improvement, "deteriorations": deteriorations}
    triggered = no_improvement >= PLATEAU_NO_IMPROVEMENT_ATTEMPTS or deteriorations >= PLATEAU_DETERIORATIONS
    if not triggered:
        return new, BlockOutcome(block_role, "hold", "incomplete", None, None, details)
    trigger = "no_improvement" if no_improvement >= PLATEAU_NO_IMPROVEMENT_ATTEMPTS else "deteriorations"
    reset = replace(new, best_total=None, last_total=None, no_improvement=0, deteriorations=0)
    if strength.calibration_stage == 0 and strength.last_increase_kg is not None:
        calibrated = replace(
            reset, load_kg=strength.load_kg - strength.last_increase_kg, last_increase_kg=None, calibration_stage=1,
        )
        return calibrated, BlockOutcome(
            block_role, "calibrate_undo_last_increase", trigger, None, None,
            {**details, "load_after_kg": _dec_str(calibrated.load_kg), "undone_kg": _dec_str(strength.last_increase_kg)},
        )
    # Отменять нечего (или калибровка уже была): новый 1RM — только предложение, не обязательство.
    offered = replace(reset, recalibration_offered=True)
    return offered, BlockOutcome(block_role, "offer_fresh_1rm_or_recalibrate", trigger, None, None, details)


def _qualify(state: V5State, signal_details: dict) -> V5State:
    """Допуск внутри программы (§8.2): резина убирается из объёма, переходная неделя, силовые блоки —
    5×5 / 5×3 с весом из 1RM (тест — в отдельный свежий день; до него сила ждёт ввода)."""
    volume_a, volume_b = _transition_volume()
    return replace(
        state, level=ProgramLevel.TRANSITION, volume_a=volume_a, volume_b=volume_b,
        strength_a=_weighted_start(state.inputs, WorkoutRole.A), strength_b=_weighted_start(state.inputs, WorkoutRole.B),
        qualification={"signal": "in_program", **signal_details},
        assistance_pending=(),  # резина убирается из объёма, сила — с весом: ожидающих смен помощи нет
    )


def _deteriorated(previous_volume: int | None, previous_plan, fact_volume: int | None, plan) -> bool:
    return previous_volume is not None and fact_volume is not None and previous_plan == plan and fact_volume < previous_volume


def advance_session(
    state: V5State, prescription: Mapping, result: SessionResult, *, body_mass: Decimal | None,
    ladder: Sequence[AssistanceSetup] = (),
) -> SessionAdvance:
    """Шаг прогрессии по ОДНОМУ завершённому основному занятию. Только вперёд: вход — текущее состояние,
    рецепт ЭТОГО занятия (из его снимка) и его факт; прошлые занятия и их рецепты не пересчитываются.

    Объём и сила — независимые критерии (§9). Роль занятия берётся из рецепта, а не из состояния."""
    if prescription.get("program_version") != PROGRAM_VERSION:
        raise V5StateError("prescription is not pullups_v5_6")
    role = WorkoutRole(prescription["workout_role"])
    volume_block, strength_block = prescription["blocks"]
    paused = state.recovery_check_required

    previous_a, previous_b = state.volume_a, state.volume_b
    previous_strength = state.strength(role)

    if role is WorkoutRole.A:
        volume_a, volume_outcome = _advance_a_volume(state, volume_block, result.volume, increases_paused=paused, ladder=ladder)
        new = replace(state, volume_a=volume_a)
        if new.volume_b.stage is BVolumeStage.PENDING_REFERENCE:
            # Первая B без истории — от факта первой A (§5).
            sets, reps = b_start(volume_outcome.fact_volume)
            new = replace(new, volume_b=replace(
                new.volume_b, stage=BVolumeStage.STANDARD, sets=sets, reps=reps, reference_volume=volume_outcome.fact_volume,
            ))
        left_transition = False
        volume_deteriorated = _deteriorated(previous_a.last_volume, previous_a.last_plan, volume_outcome.fact_volume, tuple(_prescribed_targets(volume_block)))
    else:
        volume_b, volume_outcome, left_transition = _advance_b_volume(state, volume_block, result.volume, increases_paused=paused)
        new = replace(state, volume_b=volume_b)
        plan = (len(volume_block["sets"]), int(volume_block["sets"][0]["target_reps"]))
        volume_deteriorated = _deteriorated(previous_b.last_volume, previous_b.last_plan, volume_outcome.fact_volume, plan)
    if left_transition and new.level is ProgramLevel.TRANSITION:
        new = replace(new, level=ProgramLevel.WEIGHTED)

    qualified = False
    strength_role = BlockRole(strength_block["block_role"])
    if strength_role is BlockRole.ASSISTED_STRENGTH:
        strength, strength_outcome, qualified = _advance_assisted_strength(new, role, result.strength, increases_paused=paused, ladder=ladder)
        new = _with_strength(new, role, strength)
    else:
        strength, strength_outcome = _advance_weighted_strength(new, role, strength_block, result.strength, body_mass=body_mass, increases_paused=paused)
        new = _with_strength(new, role, strength)

    # §9: два занятия подряд с одновременным ухудшением обоих блоков — новые прибавки не назначаются до
    # проверки восстановления и внешней тяговой нагрузки. Ухудшение — только при том же плане (сопоставимо).
    strength_total = strength_outcome.details.get("total")
    strength_plan_key = f"{strength_block['block_role']}:{strength_block.get('external_load_kg')}:{_setup_key(strength_block.get('assistance'))}"
    strength_deteriorated = (
        previous_strength is not None and strength_total is not None and previous_strength.last_plan_key == strength_plan_key
        and previous_strength.last_total is not None and strength_total < previous_strength.last_total
    )
    current_strength = new.strength(role)
    if current_strength is not None:
        # У силы с помощью last_total — только для сравнения §9; у силы с весом его ведёт расчёт плато.
        last_total = strength_total if current_strength.mode == ASSISTED_MODE else current_strength.last_total
        new = _with_strength(new, role, replace(current_strength, last_plan_key=strength_plan_key, last_total=last_total))
    both = volume_deteriorated and strength_deteriorated
    streak = state.both_deteriorated_streak + 1 if both else 0
    new = replace(new, both_deteriorated_streak=streak, recovery_check_required=state.recovery_check_required or streak >= 2)

    # Смены помощи, ждущие подтверждения полной записи резины: намерение сохраняется до подтверждения.
    pending = [entry for entry in new.assistance_pending]
    for outcome in (volume_outcome, strength_outcome):
        entry = outcome.details.get("pending_assistance")
        if entry is not None:
            pending = [e for e in pending if e["block"] != entry["block"]] + [entry]
    new = replace(new, assistance_pending=tuple(pending))

    if qualified:
        new = _qualify(new, {"workout_role": role.value, "result": [r for r in result.strength.reps]})
    new = replace(new, next_role=role.other, sessions_completed=state.sessions_completed + 1)
    return SessionAdvance(state=new, volume=volume_outcome, strength=strength_outcome, qualified=qualified)


def _setup_key(setup: Mapping | None) -> str:
    if not setup:
        return "none"
    return f"{setup.get('kind')}:{setup.get('equipment_item_id')}:{setup.get('name')}"
