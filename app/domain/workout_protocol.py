"""Canonical ExecutionProtocol v1 (Phase A1, issue #213) — discriminated union
definition-типов и их resolved-форм. Определяет, как блок выполняется
(повторения/время/интервалы/максимум), без привязки к конкретному упражнению.

Definition protocol — форма, которая хранится в БД (будет сериализоваться в
JSONB-колонку, волна A2, здесь только Pydantic-схема): source="static" несёт
конкретные числа (sets/reps/duration_seconds), source="progression" означает
"взять из progression_strategy" — пока не реализована ни одна progression для
time_sets/max_effort (Phase A1 не использует их), но схема допускает это как
будущее расширение.

Resolved protocol — НЕ те же классы: отдельные типы без полей
prescription/source (структурно невозможно выразить их в resolved-модели, см.
тесты). Это результат резолвинга definition через progression_strategy
(волна A2) — сервисный слой получает уже resolved-форму с конкретными
target_reps/target_seconds для каждого подхода, не абстрактное "progression".

Схема допускает добавление AMRAP/EMOM/circuit как будущих вариантов того же
discriminated union (отмечено в докстринге DefinitionProtocol, не
реализовано в Phase A1) — доказательство, что это extensible-контракт, не
жёсткая схема под единственную программу."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator


class ProtocolType(StrEnum):
    """Тип протокола выполнения блока — discriminator для union-типов
    DefinitionProtocol/ResolvedProtocol. Не путать с MetricType
    (app.domain.multi_program) — там единица измерения результата
    (reps/time/weight), здесь — способ выполнения блока (подходы с
    повторениями/время/интервалы/максимум)."""

    REPS_SETS = "reps_sets"
    TIME_SETS = "time_sets"
    MAX_EFFORT = "max_effort"
    INTERVAL = "interval"


class PrescriptionSource(StrEnum):
    """Источник конкретных значений prescription — static (числа заданы явно
    в definition-форме, см. StaticRepsSets/StaticTimeSets/StaticMaxEffort) или
    progression (берутся из progression_strategy при резолвинге, см.
    ProgressionRepsSets/ProgressionTimeSets — реальная progression для time_sets
    НЕ используется в Phase A1, но схема допускает её как будущее
    расширение)."""

    STATIC = "static"
    PROGRESSION = "progression"


# ============================================================================
# Definition protocol — 4 типа, discriminated union по type
# ============================================================================


class StaticRepsSets(BaseModel):
    """REPS_SETS static: фиксированное число подходов/повторений, заданное
    явно (не из progression). Пример: 3 подхода по 15 повторений, отдых 90
    сек между подходами.

    Validation: sets >= 1, reps >= 1, rest_seconds >= 0."""

    type: Literal[ProtocolType.REPS_SETS] = ProtocolType.REPS_SETS
    prescription: Annotated[
        "StaticRepsPrescription",
        Field(description="Конкретные значения sets/reps"),
    ]
    rest_seconds: Annotated[
        int,
        Field(ge=0, description="Отдых между подходами, секунд"),
    ]


class StaticRepsPrescription(BaseModel):
    """Конкретные значения для StaticRepsSets — source явно зафиксирован как
    STATIC, sets/reps обязательны."""

    source: Literal[PrescriptionSource.STATIC] = PrescriptionSource.STATIC
    sets: Annotated[int, Field(ge=1, description="Число подходов")]
    reps: Annotated[int, Field(ge=1, description="Повторений в подходе")]


class ProgressionRepsSets(BaseModel):
    """REPS_SETS progression: число подходов/повторений берётся из
    progression_strategy при резолвинге (волна A2), не задано явно в
    definition. Поля sets/reps структурно ОТСУТСТВУЮТ (не просто nullable) —
    это другая ветка union, не та же модель с опциональными полями.

    Validation: rest_seconds >= 0 (конкретных sets/reps нет в этой ветке)."""

    type: Literal[ProtocolType.REPS_SETS] = ProtocolType.REPS_SETS
    prescription: Annotated[
        "ProgressionRepsPrescription",
        Field(description="Source=progression, без конкретных sets/reps"),
    ]
    rest_seconds: Annotated[
        int,
        Field(ge=0, description="Отдых между подходами, секунд"),
    ]


class ProgressionRepsPrescription(BaseModel):
    """Prescription для ProgressionRepsSets — только source=PROGRESSION, без
    конкретных значений sets/reps (они появятся в resolved-форме после
    резолвинга через progression_strategy)."""

    source: Literal[PrescriptionSource.PROGRESSION] = PrescriptionSource.PROGRESSION


class StaticTimeSets(BaseModel):
    """TIME_SETS static: фиксированное число подходов по времени. Пример:
    3 подхода по 30 секунд (планка), отдых 60 сек.

    Validation: sets >= 1, duration_seconds > 0, rest_seconds >= 0."""

    type: Literal[ProtocolType.TIME_SETS] = ProtocolType.TIME_SETS
    prescription: Annotated[
        "StaticTimePrescription",
        Field(description="Конкретные значения sets/duration_seconds"),
    ]
    rest_seconds: Annotated[
        int,
        Field(ge=0, description="Отдых между подходами, секунд"),
    ]


class StaticTimePrescription(BaseModel):
    """Конкретные значения для StaticTimeSets."""

    source: Literal[PrescriptionSource.STATIC] = PrescriptionSource.STATIC
    sets: Annotated[int, Field(ge=1, description="Число подходов")]
    duration_seconds: Annotated[int, Field(gt=0, description="Длительность подхода, секунд")]


class ProgressionTimeSets(BaseModel):
    """TIME_SETS progression: допустимо на уровне схемы, но реальная
    progression для time_sets НЕ используется в Phase A1 (нет продуктового
    применения на этой волне). Оставлено как будущее расширение — доказательство,
    что схема не заточена только под reps/static."""

    type: Literal[ProtocolType.TIME_SETS] = ProtocolType.TIME_SETS
    prescription: Annotated[
        "ProgressionTimePrescription",
        Field(description="Source=progression для time_sets (не используется в A1)"),
    ]
    rest_seconds: Annotated[
        int,
        Field(ge=0, description="Отдых между подходами, секунд"),
    ]


class ProgressionTimePrescription(BaseModel):
    """Prescription для ProgressionTimeSets — только source=PROGRESSION."""

    source: Literal[PrescriptionSource.PROGRESSION] = PrescriptionSource.PROGRESSION


class StaticMaxEffort(BaseModel):
    """MAX_EFFORT: один или несколько попыток на максимум (all-out, до отказа).
    Пример: 1 попытка на максимальное число повторений.

    Validation: attempts >= 1. rest_seconds между попытками здесь не
    определено (отдых между попытками — продуктовое решение вне схемы
    протокола, пока не нужен)."""

    type: Literal[ProtocolType.MAX_EFFORT] = ProtocolType.MAX_EFFORT
    prescription: Annotated[
        "StaticMaxEffortPrescription",
        Field(description="Число попыток на максимум"),
    ]


class StaticMaxEffortPrescription(BaseModel):
    """Конкретные значения для StaticMaxEffort."""

    source: Literal[PrescriptionSource.STATIC] = PrescriptionSource.STATIC
    attempts: Annotated[int, Field(ge=1, description="Число попыток на максимум")]


class Interval(BaseModel):
    """INTERVAL: чередование work/rest по фиксированному таймеру. Пример:
    табата — 180 сек общей длительности, 10 сек работа, 20 сек отдых,
    старт с работы.

    Validation:
    - total_duration_seconds > 0
    - work_seconds > 0
    - rest_seconds >= 0
    - work_seconds + rest_seconds <= total_duration_seconds
    - starts_with пока только "work" (не расширять на "rest" в Phase A1)

    У Interval НЕТ поля prescription/source — это единственный протокол,
    который всегда static по построению (нет progression-формы для interval
    в Phase A1, и схема не предполагает её как будущее расширение — интервал
    определяется таймером, не progression_strategy)."""

    type: Literal[ProtocolType.INTERVAL] = ProtocolType.INTERVAL
    total_duration_seconds: Annotated[
        int,
        Field(gt=0, description="Общая длительность интервального блока, секунд"),
    ]
    work_seconds: Annotated[int, Field(gt=0, description="Длительность work-фазы, секунд")]
    rest_seconds: Annotated[int, Field(ge=0, description="Длительность rest-фазы, секунд")]
    starts_with: Annotated[
        Literal["work"],
        Field(description='Фаза старта — пока только "work" (Phase A1)'),
    ]

    @model_validator(mode="after")
    def validate_work_rest_fit_in_total(self) -> "Interval":
        """work_seconds + rest_seconds не должны превышать total_duration_seconds —
        иначе один цикл не влезает в общую длительность."""
        if self.work_seconds + self.rest_seconds > self.total_duration_seconds:
            raise ValueError(
                f"work_seconds ({self.work_seconds}) + rest_seconds ({self.rest_seconds}) "
                f"превышает total_duration_seconds ({self.total_duration_seconds})"
            )
        return self


# Discriminated union — все definition-типы в одном Annotated.
#
# Integration fix (Phase B1, issue #215) — исходный single-field
# Field(discriminator="type") был структурно сломан: StaticRepsSets и
# ProgressionRepsSets (аналогично StaticTimeSets/ProgressionTimeSets)
# несут ОДНО и то же значение type="reps_sets"/"time_sets", различаясь
# только вложенным prescription.source — Pydantic требует уникального
# значения дискриминатора на вариант, а не два класса на одно значение.
# Обнаружено только сейчас (не в Phase A1's собственных 34 тестах),
# потому что ни один из них не строил TypeAdapter(DefinitionProtocol)
# целиком — каждый класс проверялся по отдельности
# (StaticRepsSets.model_validate(...) и т.д.), сама сборка union
# никогда не вызывалась. Исправлено callable Discriminator, различающим
# reps_sets/time_sets по составному ключу "type_source"; max_effort и
# interval — по одному варианту на type, коллизии не было и нет.
def _protocol_discriminator(value: object) -> str:
    if isinstance(value, dict):
        protocol_type = value.get("type")
        prescription = value.get("prescription")
        source = prescription.get("source") if isinstance(prescription, dict) else None
    else:
        protocol_type = getattr(value, "type", None)
        prescription = getattr(value, "prescription", None)
        source = getattr(prescription, "source", None) if prescription is not None else None

    if protocol_type in (ProtocolType.REPS_SETS, ProtocolType.TIME_SETS, "reps_sets", "time_sets") and source is not None:
        return f"{protocol_type}_{source}"
    return protocol_type


DefinitionProtocol = Annotated[
    Annotated[StaticRepsSets, Tag("reps_sets_static")]
    | Annotated[ProgressionRepsSets, Tag("reps_sets_progression")]
    | Annotated[StaticTimeSets, Tag("time_sets_static")]
    | Annotated[ProgressionTimeSets, Tag("time_sets_progression")]
    | Annotated[StaticMaxEffort, Tag("max_effort")]
    | Annotated[Interval, Tag("interval")],
    Discriminator(_protocol_discriminator),
]


# ============================================================================
# Resolved protocol — отдельные типы, БЕЗ prescription/source
# ============================================================================


class ResolvedSetTarget(BaseModel):
    """Один подход resolved reps-протокола — конкретная цель в повторениях."""

    model_config = ConfigDict(extra="forbid")

    target_reps: Annotated[int, Field(ge=1, description="Целевое число повторений в подходе")]


class ResolvedRepsSets(BaseModel):
    """Resolved REPS_SETS: массив конкретных целей по повторениям для каждого
    подхода. Поля prescription/source структурно ОТСУТСТВУЮТ (не nullable) —
    это resolved-форма, не definition.

    Пример: [{"target_reps": 10}, {"target_reps": 10}, {"target_reps": 10}],
    rest_seconds=90."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ProtocolType.REPS_SETS] = ProtocolType.REPS_SETS
    sets: Annotated[
        list[ResolvedSetTarget],
        Field(min_length=1, description="Конкретные цели для каждого подхода"),
    ]
    rest_seconds: Annotated[int, Field(ge=0, description="Отдых между подходами, секунд")]


class ResolvedTimeSetTarget(BaseModel):
    """Один подход resolved time-протокола — конкретная длительность в секундах."""

    model_config = ConfigDict(extra="forbid")

    target_seconds: Annotated[int, Field(gt=0, description="Целевая длительность подхода, секунд")]


class ResolvedTimeSets(BaseModel):
    """Resolved TIME_SETS: массив конкретных длительностей для каждого подхода.
    Поля prescription/source отсутствуют."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ProtocolType.TIME_SETS] = ProtocolType.TIME_SETS
    sets: Annotated[
        list[ResolvedTimeSetTarget],
        Field(min_length=1, description="Конкретные длительности для каждого подхода"),
    ]
    rest_seconds: Annotated[int, Field(ge=0, description="Отдых между подходами, секунд")]


class ResolvedMaxEffortAttempt(BaseModel):
    """Одна попытка resolved max_effort-протокола. is_max=True означает
    "попытка на максимум" (all-out) — зарезервировано на будущее более
    сложное различие попыток (например, warm-up перед максимумом), пока
    всегда True."""

    model_config = ConfigDict(extra="forbid")

    is_max: Annotated[bool, Field(description="True = попытка на максимум (all-out)")]


class ResolvedMaxEffort(BaseModel):
    """Resolved MAX_EFFORT: массив попыток на максимум. Поля
    prescription/source отсутствуют."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ProtocolType.MAX_EFFORT] = ProtocolType.MAX_EFFORT
    attempts: Annotated[
        list[ResolvedMaxEffortAttempt],
        Field(min_length=1, description="Попытки на максимум"),
    ]


class ResolvedInterval(BaseModel):
    """Resolved INTERVAL: та же форма, что definition Interval — у interval
    нет source=progression в Phase A1, resolved-форма совпадает с definition.
    Это НЕ нарушение инварианта "resolved отличается от definition" —
    инвариант касается отсутствия полей prescription/source (которых у
    Interval никогда не было), не всей структуры целиком."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ProtocolType.INTERVAL] = ProtocolType.INTERVAL
    total_duration_seconds: Annotated[int, Field(gt=0, description="Общая длительность, секунд")]
    work_seconds: Annotated[int, Field(gt=0, description="Длительность work-фазы, секунд")]
    rest_seconds: Annotated[int, Field(ge=0, description="Длительность rest-фазы, секунд")]
    starts_with: Annotated[Literal["work"], Field(description='Фаза старта — пока только "work"')]

    @model_validator(mode="after")
    def validate_work_rest_fit_in_total(self) -> "ResolvedInterval":
        """Та же валидация, что у definition Interval."""
        if self.work_seconds + self.rest_seconds > self.total_duration_seconds:
            raise ValueError(
                f"work_seconds ({self.work_seconds}) + rest_seconds ({self.rest_seconds}) "
                f"превышает total_duration_seconds ({self.total_duration_seconds})"
            )
        return self


# Discriminated union — все resolved-типы в одном Annotated.
ResolvedProtocol = Annotated[
    ResolvedRepsSets | ResolvedTimeSets | ResolvedMaxEffort | ResolvedInterval,
    Field(discriminator="type"),
]


# Phase C3 (issue #188) — сужённый union БЕЗ progression-вариантов
# (ProgressionRepsSets/ProgressionTimeSets), для user-owned Workout
# Builder: обычный пользователь не должен уметь через сырой JSON
# протолкнуть prescription.source="progression" — этот режим относится
# только к program-authoring context, которого в Phase C Builder MVP нет
# вообще (см. issue #188, UX Contract v1, "REPS UX" — режим B недоступен
# для полностью самостоятельной пользовательской тренировки).
#
# Простой Field(discriminator="type") здесь корректен и достаточен (не
# нужен callable Discriminator+Tag, как у полного DefinitionProtocol) —
# без Progression-вариантов каждый оставшийся тип несёт УНИКАЛЬНОЕ
# значение type (reps_sets/time_sets/max_effort/interval, по одному
# варианту на значение), коллизии дискриминатора, из-за которой
# понадобился callable-обходной путь для DefinitionProtocol, здесь нет.
UserWorkoutProtocol = Annotated[
    StaticRepsSets | StaticTimeSets | StaticMaxEffort | Interval,
    Field(discriminator="type"),
]
