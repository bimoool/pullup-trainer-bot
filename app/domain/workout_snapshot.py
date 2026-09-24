"""Workout snapshot builder (Phase A1, Worker C, issue #188) — переводит
Workout definition (технически Complex/ComplexItem, Worker B, issue #214) в
immutable resolved WorkoutSnapshot, используя ExecutionProtocol v1 (Worker A,
issue #213). Чистый domain-слой: не знает о SQLAlchemy/сессии БД напрямую —
принимает уже загруженные объекты, не делает собственных запросов (это
работа вызывающего слоя, будущая интеграция с start_session — НЕ в Phase
A1, см. докстрайн модуля CLAUDE.md "не пиши второй, отдельный путь").

Главный архитектурный принцип этого файла (issue #188, design contract,
раздел "PROGRESSION RESOLUTION BOUNDARY"): builder никогда не импортирует
и не знает о:
  - StepProgressionStrategy / ProgressionStrategyType
  - block_a / block_b / subcategory-конвенции
  - ProgramInclusion.progression_state

Вместо этого builder получает `ProgressionResolver` — простую функцию
`exercise_id -> list[int]` (список target_reps по подходам). Она передаётся
вызывающим кодом (будущая интеграция знает про STEP, builder — нет). Это
доказывается тестом test_builder_does_not_import_progression_internals
ниже."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.domain.workout_protocol import (
    DefinitionProtocol,
    Interval,
    ProgressionRepsSets,
    ProgressionTimeSets,
    ResolvedInterval,
    ResolvedMaxEffort,
    ResolvedMaxEffortAttempt,
    ResolvedProtocol,
    ResolvedRepsSets,
    ResolvedSetTarget,
    ResolvedTimeSets,
    ResolvedTimeSetTarget,
    StaticMaxEffort,
    StaticRepsSets,
    StaticTimeSets,
)

if TYPE_CHECKING:
    from app.db.models_program import Complex, ComplexItem, Exercise


class WorkoutItemSnapshot(BaseModel):
    """Один пункт resolved-снимка тренировки — конкретное упражнение с уже
    разрешённым протоколом (см. app.domain.workout_protocol.ResolvedProtocol
    — структурно не может содержать prescription/source)."""

    exercise_id: int
    exercise_name: str = Field(description="Снята копия на момент резолвинга — переживает переименование Exercise")
    order: int
    protocol: ResolvedProtocol


class WorkoutSnapshot(BaseModel):
    """Immutable снимок Workout definition на момент резолвинга — то, что
    видит Session engine (issue #188, "SESSION ENGINE INPUT"). workout_id —
    ссылка для UI, не источник правды после создания снимка."""

    workout_id: int
    title: str
    items: list[WorkoutItemSnapshot]


# exercise_id -> список target_reps по подходам (один элемент на подход).
# Единственная форма, реально нужная в Phase A1 (только reps_sets/progression
# используется продуктово — см. app.domain.workout_protocol докстринг
# ProgressionTimeSets: "схема допускает, но не используется"). Расширение на
# time_sets/max_effort progression — отдельное решение будущей волны, не
# домысливается здесь молча.
ProgressionResolver = Callable[[int], list[int]]


class UnresolvedProgressionError(ValueError):
    """WorkoutItem.protocol.prescription.source == "progression", но builder
    вызван без progression_resolver — нет пути получить конкретные targets.
    Отдельный тип исключения, не голый ValueError — вызывающий код должен
    уметь отличить эту ошибку от невалидных входных данных."""


def _resolve_protocol(protocol: DefinitionProtocol, exercise_id: int, resolver: ProgressionResolver | None) -> ResolvedProtocol:
    """Definition -> Resolved для одного протокола. Единственное место в
    модуле, ветвящееся по типу протокола — если позже появится AMRAP/EMOM/
    circuit, новая ветка добавляется здесь, не меняя сигнатуру функции."""
    if isinstance(protocol, StaticRepsSets):
        target = ResolvedSetTarget(target_reps=protocol.prescription.reps)
        return ResolvedRepsSets(sets=[target] * protocol.prescription.sets, rest_seconds=protocol.rest_seconds)

    if isinstance(protocol, ProgressionRepsSets):
        if resolver is None:
            raise UnresolvedProgressionError(
                f"exercise_id={exercise_id}: protocol.prescription.source='progression', "
                "но progression_resolver не передан builder'у",
            )
        reps_per_set = resolver(exercise_id)
        return ResolvedRepsSets(
            sets=[ResolvedSetTarget(target_reps=reps) for reps in reps_per_set],
            rest_seconds=protocol.rest_seconds,
        )

    if isinstance(protocol, StaticTimeSets):
        target = ResolvedTimeSetTarget(target_seconds=protocol.prescription.duration_seconds)
        return ResolvedTimeSets(sets=[target] * protocol.prescription.sets, rest_seconds=protocol.rest_seconds)

    if isinstance(protocol, ProgressionTimeSets):
        # Схема допускает (issue #213, Worker A докстринг), но реальный
        # резолвер для time_sets/progression не определён в Phase A1 —
        # честная ошибка, не молчаливая придумка значения.
        raise UnresolvedProgressionError(
            f"exercise_id={exercise_id}: time_sets/progression не поддерживается в Phase A1",
        )

    if isinstance(protocol, StaticMaxEffort):
        attempts = [ResolvedMaxEffortAttempt(is_max=True) for _ in range(protocol.prescription.attempts)]
        return ResolvedMaxEffort(attempts=attempts, rest_seconds=protocol.rest_seconds)

    if isinstance(protocol, Interval):
        # У Interval нет source=progression (issue #213 докстринг) —
        # resolved-форма всегда совпадает с definition один в один.
        return ResolvedInterval(
            total_duration_seconds=protocol.total_duration_seconds,
            work_seconds=protocol.work_seconds,
            rest_seconds=protocol.rest_seconds,
            starts_with=protocol.starts_with,
        )

    # Discriminated union исчерпан — недостижимо при корректной типизации,
    # но explicit, не молчаливое None.
    raise ValueError(f"неизвестный тип протокола: {protocol.type}")  # pragma: no cover


def build_workout_snapshot(
    workout: "Complex",
    items: "list[ComplexItem]",
    exercises: "dict[int, Exercise]",
    protocols: dict[int, DefinitionProtocol],
    progression_resolver: ProgressionResolver | None = None,
) -> WorkoutSnapshot:
    """Definition Workout -> immutable resolved WorkoutSnapshot.

    Параметры — уже загруженные объекты, не ID для запроса (builder не
    делает собственных запросов к БД, issue #188 "чистый domain-слой").

    protocols: {complex_item.id: DefinitionProtocol} — распарсенный Pydantic
    из ComplexItem.protocol (JSONB), распарсивание — ответственность
    вызывающего кода (builder работает с типизированными объектами, не
    сырым JSON — двойная ответственность в одном месте нежелательна).

    progression_resolver: опционален — обязателен только если среди items
    реально есть хотя бы один protocol с source="progression"; иначе
    UnresolvedProgressionError."""
    item_snapshots = [
        WorkoutItemSnapshot(
            exercise_id=item.exercise_id,
            exercise_name=exercises[item.exercise_id].name,
            order=item.order_index,
            protocol=_resolve_protocol(protocols[item.id], item.exercise_id, progression_resolver),
        )
        for item in sorted(items, key=lambda i: i.order_index)
    ]
    return WorkoutSnapshot(workout_id=workout.id, title=workout.name, items=item_snapshots)
