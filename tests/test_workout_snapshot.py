"""Тесты app.domain.workout_snapshot (Phase A1, Worker C, issue #188) —
только сам builder, без БД/сессии (Complex/ComplexItem/Exercise
конструируются напрямую, не через репозиторий/фикстуру session)."""

import ast
import inspect

import pytest

from app.db.models_program import Complex, ComplexItem, Exercise
from app.domain.multi_program import MetricType
from app.domain.workout_protocol import (
    Interval,
    ProgressionRepsPrescription,
    ProgressionRepsSets,
    ResolvedInterval,
    ResolvedMaxEffort,
    ResolvedRepsSets,
    ResolvedTimeSets,
    StaticMaxEffort,
    StaticMaxEffortPrescription,
    StaticRepsPrescription,
    StaticRepsSets,
    StaticTimePrescription,
    StaticTimeSets,
)
from app.domain.workout_snapshot import UnresolvedProgressionError, build_workout_snapshot


def _exercise(id_: int, name: str, metric_type: MetricType = MetricType.REPS) -> Exercise:
    ex = Exercise(name=name, metric_type=metric_type, category="test")
    ex.id = id_
    return ex


def _complex(id_: int, name: str) -> Complex:
    c = Complex(name=name)
    c.id = id_
    return c


def _item(id_: int, exercise_id: int, order_index: int) -> ComplexItem:
    ci = ComplexItem(exercise_id=exercise_id, order_index=order_index, sets=1)
    ci.id = id_
    return ci


def test_static_reps_sets_snapshot():
    """Отжимания: 3 × 15, rest 90 — resolved snapshot с тремя одинаковыми target_reps."""
    workout = _complex(1, "Отжимания")
    item = _item(1, exercise_id=10, order_index=0)
    exercises = {10: _exercise(10, "Отжимания")}
    protocol = StaticRepsSets(prescription=StaticRepsPrescription(sets=3, reps=15), rest_seconds=90)

    snapshot = build_workout_snapshot(workout, [item], exercises, {1: protocol})

    assert snapshot.workout_id == 1
    assert snapshot.title == "Отжимания"
    assert len(snapshot.items) == 1
    resolved = snapshot.items[0].protocol
    assert isinstance(resolved, ResolvedRepsSets)
    assert [s.target_reps for s in resolved.sets] == [15, 15, 15]
    assert resolved.rest_seconds == 90
    assert snapshot.items[0].exercise_name == "Отжимания"


def test_static_time_sets_snapshot():
    """Планка: 3 × 30 сек, rest 60 — resolved snapshot с target_seconds, не target_reps."""
    workout = _complex(2, "Планка")
    item = _item(2, exercise_id=11, order_index=0)
    exercises = {11: _exercise(11, "Планка", MetricType.TIME)}
    protocol = StaticTimeSets(prescription=StaticTimePrescription(sets=3, duration_seconds=30), rest_seconds=60)

    snapshot = build_workout_snapshot(workout, [item], exercises, {2: protocol})

    resolved = snapshot.items[0].protocol
    assert isinstance(resolved, ResolvedTimeSets)
    assert [s.target_seconds for s in resolved.sets] == [30, 30, 30]
    assert resolved.rest_seconds == 60


def test_max_effort_snapshot():
    workout = _complex(3, "Подтягивания на максимум")
    item = _item(3, exercise_id=12, order_index=0)
    exercises = {12: _exercise(12, "Подтягивания")}
    protocol = StaticMaxEffort(prescription=StaticMaxEffortPrescription(attempts=1))

    snapshot = build_workout_snapshot(workout, [item], exercises, {3: protocol})

    resolved = snapshot.items[0].protocol
    assert isinstance(resolved, ResolvedMaxEffort)
    assert len(resolved.attempts) == 1
    assert resolved.attempts[0].is_max is True


def test_interval_snapshot_unchanged_from_definition():
    """У interval нет source=progression — resolved совпадает с definition один в один."""
    workout = _complex(4, "3 минуты подтягиваний")
    item = _item(4, exercise_id=13, order_index=0)
    exercises = {13: _exercise(13, "Подтягивания")}
    protocol = Interval(total_duration_seconds=180, work_seconds=10, rest_seconds=20, starts_with="work")

    snapshot = build_workout_snapshot(workout, [item], exercises, {4: protocol})

    resolved = snapshot.items[0].protocol
    assert isinstance(resolved, ResolvedInterval)
    assert resolved.total_duration_seconds == 180
    assert resolved.work_seconds == 10
    assert resolved.rest_seconds == 20
    assert resolved.starts_with == "work"


def test_progression_boundary_via_fake_resolver():
    """Definition source=progression -> fake resolver возвращает [10, 10, 10] ->
    snapshot содержит три конкретных target_reps=10. Builder не знает, что
    resolver внутри сделал (мог быть STEP, мог быть что угодно ещё)."""
    workout = _complex(5, "Подтягивания")
    item = _item(5, exercise_id=14, order_index=0)
    exercises = {14: _exercise(14, "Блок A")}
    protocol = ProgressionRepsSets(prescription=ProgressionRepsPrescription(), rest_seconds=90)

    def fake_resolver(exercise_id: int) -> list[int]:
        assert exercise_id == 14
        return [10, 10, 10]

    snapshot = build_workout_snapshot(workout, [item], exercises, {5: protocol}, progression_resolver=fake_resolver)

    resolved = snapshot.items[0].protocol
    assert isinstance(resolved, ResolvedRepsSets)
    assert [s.target_reps for s in resolved.sets] == [10, 10, 10]


def test_progression_without_resolver_raises_unresolved_error():
    workout = _complex(6, "Подтягивания")
    item = _item(6, exercise_id=15, order_index=0)
    exercises = {15: _exercise(15, "Блок A")}
    protocol = ProgressionRepsSets(prescription=ProgressionRepsPrescription(), rest_seconds=90)

    with pytest.raises(UnresolvedProgressionError):
        build_workout_snapshot(workout, [item], exercises, {6: protocol})


def test_multi_item_ordering_preserved_even_if_input_unordered():
    """Планка + Отжимания — order сохраняется по order_index, не по порядку
    в списке items на входе (намеренно передаём в обратном порядке)."""
    workout = _complex(7, "Планка + Отжимания")
    plank_item = _item(71, exercise_id=20, order_index=0)
    pushups_item = _item(72, exercise_id=21, order_index=1)
    exercises = {20: _exercise(20, "Планка", MetricType.TIME), 21: _exercise(21, "Отжимания")}
    protocols = {
        71: StaticTimeSets(prescription=StaticTimePrescription(sets=3, duration_seconds=30), rest_seconds=60),
        72: StaticRepsSets(prescription=StaticRepsPrescription(sets=3, reps=15), rest_seconds=90),
    }

    snapshot = build_workout_snapshot(workout, [pushups_item, plank_item], exercises, protocols)

    assert [i.exercise_name for i in snapshot.items] == ["Планка", "Отжимания"]
    assert [i.order for i in snapshot.items] == [0, 1]


def test_builder_does_not_import_progression_internals():
    """Архитектурный инвариант (issue #188, design contract): snapshot
    builder не должен импортировать STEP strategy / ProgramInclusion — весь
    progression-контекст приходит только через ProgressionResolver, builder
    о нём не знает. Проверяем реальные import-узлы AST, не текст модуля —
    докстринг файла намеренно упоминает эти термины прозой, объясняя,
    почему их здесь нет (наивный substring-поиск по всему исходнику ловил
    бы именно эту прозу как ложное срабатывание)."""
    import app.domain.workout_snapshot as module

    tree = ast.parse(inspect.getsource(module))
    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    forbidden_names = {"StepProgressionStrategy", "ProgressionStrategyType", "ProgramInclusion"}
    assert not (forbidden_names & imported_names), (
        f"snapshot builder не должен импортировать: {forbidden_names & imported_names}"
    )
    assert not any("progression_strategy" in mod or "program_inclusion" in mod for mod in imported_modules), (
        f"snapshot builder не должен импортировать progression/inclusion-модули, нашёл: {imported_modules}"
    )
