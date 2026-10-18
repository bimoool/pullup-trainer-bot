"""Свой план: количество каждой тренировки по неделям + фаза недели (UX-EDITOR, contract v2).

Чистая логика, без БД и без «сейчас». PlanSpec — `custom_plans.spec` (JSONB):
{"v": 2, "quantities": [[int по неделям] на каждую запись `workouts`], "phases": ["base"|"rest"|"peak" по неделям]}.
Старые планы (spec IS NULL) выводятся из `workouts` + `weeks` ротацией — результат совпадает с тем, что
материализовал прежний код (custom_week_occurrences), поэтому до первой правки пользователь ничего не видит."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.plan_occurrence import (
    CUSTOM_PLAN_MAX_WEEKS,
    CUSTOM_WEEK_MAX_COUNT,
    CustomPlanRepeat,
    custom_week_count,
)

PHASES = ("base", "rest", "peak")
DEFAULT_PHASE = "base"
SPEC_VERSION = 2


class PlanSpecError(ValueError):
    """Невалидная правка. code — машинный код для API (detail.code)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlanSpec:
    workouts: tuple[int, ...]
    quantities: tuple[tuple[int, ...], ...]  # [позиция в workouts][неделя]
    phases: tuple[str, ...]
    repeat: CustomPlanRepeat = CustomPlanRepeat.ONCE
    notice: str | None = None  # пояснение к конвертации (не хранится)

    @property
    def week_count(self) -> int:
        return len(self.phases)

    def totals(self) -> list[int]:
        return [sum(row[w] for row in self.quantities) for w in range(self.week_count)]

    def offset_index(self, week_offset: int) -> int | None:
        """Индекс недели матрицы для смещения от старта плана; None — вне плана."""
        if week_offset < 0 or self.week_count == 0:
            return None
        if week_offset >= self.week_count:
            if self.repeat != CustomPlanRepeat.CYCLE:
                return None
            return week_offset % self.week_count
        return week_offset

    def expected_counts(self, week_offset: int) -> dict[int, int]:
        """{workout_id: сколько занятий} недели со смещением week_offset (дубли id суммируются)."""
        index = self.offset_index(week_offset)
        result: dict[int, int] = {}
        if index is None:
            return result
        for position, workout_id in enumerate(self.workouts):
            count = self.quantities[position][index]
            if count:
                result[workout_id] = result.get(workout_id, 0) + count
        return result

    def phase_at(self, week_offset: int) -> str | None:
        index = self.offset_index(week_offset)
        return self.phases[index] if index is not None else None

    def to_json(self) -> dict:
        return {"v": SPEC_VERSION, "quantities": [list(row) for row in self.quantities], "phases": list(self.phases)}


def validate_matrix(quantities: Sequence[Sequence[int]], phases: Sequence[str], workout_count: int) -> None:
    weeks = len(phases)
    if not 1 <= weeks <= CUSTOM_PLAN_MAX_WEEKS:
        raise PlanSpecError("invalid_spec", f"Недель в плане: от 1 до {CUSTOM_PLAN_MAX_WEEKS}")
    if len(quantities) != workout_count or any(len(row) != weeks for row in quantities):
        raise PlanSpecError("invalid_spec", "Размер таблицы не совпадает с числом тренировок и недель")
    if any(phase not in PHASES for phase in phases):
        raise PlanSpecError("invalid_spec", "Неизвестная фаза недели")
    for row in quantities:
        for count in row:
            if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= CUSTOM_WEEK_MAX_COUNT:
                raise PlanSpecError("invalid_quantity", f"Занятий в неделю: от 0 до {CUSTOM_WEEK_MAX_COUNT}")
    for w in range(weeks):
        if sum(row[w] for row in quantities) > CUSTOM_WEEK_MAX_COUNT:
            raise PlanSpecError("invalid_quantity", f"В неделе не больше {CUSTOM_WEEK_MAX_COUNT} занятий")


def spec_from_json(workouts: Sequence[int], data: dict, repeat: str) -> PlanSpec:
    return PlanSpec(
        workouts=tuple(workouts), quantities=tuple(tuple(int(c) for c in row) for row in data["quantities"]),
        phases=tuple(data["phases"]), repeat=CustomPlanRepeat(repeat),
    )


def derive_spec_from_legacy(workout_ids: Sequence[int], weeks: Sequence[int], repeat: CustomPlanRepeat) -> PlanSpec:
    """Ротация → матрица. Цикл: матрица повторяется точно как старая ротация только если Σweeks кратна N;
    иначе разворачиваем k циклов (наименьшее k ≤ N, k·Σ кратно N); больше 52 недель — обрезаем и
    переводим в once (notice)."""
    n = len(workout_ids)
    total_weeks = len(weeks)
    notice = None
    out_repeat = repeat
    if repeat == CustomPlanRepeat.CYCLE and n and sum(weeks) % n != 0:
        s = sum(weeks)
        k = next(k for k in range(1, n + 1) if (k * s) % n == 0)
        if k * total_weeks <= CUSTOM_PLAN_MAX_WEEKS:
            total_weeks = k * total_weeks
        else:
            total_weeks = CUSTOM_PLAN_MAX_WEEKS
            out_repeat = CustomPlanRepeat.ONCE
            notice = "План повторялся по кругу; он развёрнут на 52 недели и дальше не повторяется."
    quantities = [[0] * total_weeks for _ in range(n)]
    for w in range(total_weeks):
        count = custom_week_count(weeks, repeat, w)
        before = sum(custom_week_count(weeks, repeat, o) for o in range(w))
        for k_i in range(count):
            quantities[(before + k_i) % n][w] += 1
    return PlanSpec(
        workouts=tuple(workout_ids), quantities=tuple(tuple(r) for r in quantities),
        phases=(DEFAULT_PHASE,) * total_weeks, repeat=out_repeat, notice=notice,
    )


# --- Правки (чистые; ограничения «прошлое/выполнено» проверяет сервис) ----------------------------


def with_quantities(spec: PlanSpec, week_index: int, by_workout: dict[int, int]) -> PlanSpec:
    """week_index — 0-based. by_workout — {workout_id: количество} для ЗАДАННЫХ тренировок; остальные
    не меняются. Дубль id в workouts: значение получает первая позиция, остальные обнуляются."""
    if not 0 <= week_index < spec.week_count:
        raise PlanSpecError("week_not_found", "Нет такой недели")
    rows = [list(r) for r in spec.quantities]
    seen: set[int] = set()
    for position, workout_id in enumerate(spec.workouts):
        if workout_id in by_workout:
            rows[position][week_index] = by_workout[workout_id] if workout_id not in seen else 0
            seen.add(workout_id)
    unknown = set(by_workout) - set(spec.workouts)
    if unknown:
        raise PlanSpecError("workout_not_in_plan", "Тренировки нет в плане")
    validate_matrix(rows, spec.phases, len(spec.workouts))
    return PlanSpec(spec.workouts, tuple(tuple(r) for r in rows), spec.phases, spec.repeat)


def with_phase(spec: PlanSpec, week_index: int, phase: str) -> PlanSpec:
    if not 0 <= week_index < spec.week_count:
        raise PlanSpecError("week_not_found", "Нет такой недели")
    if phase not in PHASES:
        raise PlanSpecError("invalid_spec", "Неизвестная фаза недели")
    phases = list(spec.phases)
    phases[week_index] = phase
    return PlanSpec(spec.workouts, spec.quantities, tuple(phases), spec.repeat)


def insert_week(spec: PlanSpec, position: int) -> PlanSpec:
    """position — 0-based индекс новой пустой недели (0..W)."""
    if not 0 <= position <= spec.week_count:
        raise PlanSpecError("week_not_found", "Нет такой недели")
    if spec.week_count + 1 > CUSTOM_PLAN_MAX_WEEKS:
        raise PlanSpecError("too_many_weeks", f"Недель в плане не больше {CUSTOM_PLAN_MAX_WEEKS}")
    rows = tuple(row[:position] + (0,) + row[position:] for row in spec.quantities)
    phases = spec.phases[:position] + (DEFAULT_PHASE,) + spec.phases[position:]
    return PlanSpec(spec.workouts, rows, phases, spec.repeat)


def delete_week(spec: PlanSpec, index: int) -> PlanSpec:
    if not 0 <= index < spec.week_count:
        raise PlanSpecError("week_not_found", "Нет такой недели")
    if spec.week_count == 1:
        raise PlanSpecError("last_week", "Нельзя удалить единственную неделю")
    rows = tuple(row[:index] + row[index + 1:] for row in spec.quantities)
    return PlanSpec(spec.workouts, rows, spec.phases[:index] + spec.phases[index + 1:], spec.repeat)


def add_workout(spec: PlanSpec, workout_id: int) -> PlanSpec:
    if workout_id in spec.workouts:
        raise PlanSpecError("workout_in_plan", "Тренировка уже в плане")
    return PlanSpec(
        spec.workouts + (workout_id,), spec.quantities + ((0,) * spec.week_count,), spec.phases, spec.repeat,
    )


def remove_workout(spec: PlanSpec, workout_id: int) -> PlanSpec:
    if workout_id not in spec.workouts:
        raise PlanSpecError("workout_not_in_plan", "Тренировки нет в плане")
    if len(set(spec.workouts)) == 1:
        raise PlanSpecError("last_workout", "Последнюю тренировку убрать нельзя — остановите план")
    keep = [i for i, w in enumerate(spec.workouts) if w != workout_id]
    return PlanSpec(
        tuple(spec.workouts[i] for i in keep), tuple(spec.quantities[i] for i in keep), spec.phases, spec.repeat,
    )
