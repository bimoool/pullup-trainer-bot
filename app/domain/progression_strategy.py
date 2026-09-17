from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Protocol

from app.domain.constants import VOLUME_BLOCK
from app.domain.progression import recalculate_cascade
from app.domain.session import WorkoutRecord


@dataclass(frozen=True)
class ProgressionContext:
    """Вход StepProgressionStrategy — буквально параметры
    app.domain.progression.recalculate_cascade, сгруппированные в один
    датакласс (волна 0 многокурсовой платформы, issue #158): состояние,
    действующее СРАЗУ ПЕРЕД первой записью subsequent_workouts, плюс сама
    цепочка, которую нужно пересчитать.

    starting_target_a/b/starting_volume_a/b — цель/объём, действующие
    непосредственно перед первой записью цепочки. starting_weak_streak_a/b/
    starting_work_sets_a/starting_stall_streak_a — бегущие счётчики иерархии
    роста блока на объём и стрика слабых тренировок, накопленные ДО этой
    точки — считает вызывающий код из истории (см.
    WorkoutRepository._build_edit_context/_build_delete_context), домен сам
    историю не хранит."""

    starting_target_a: int
    starting_target_b: int
    starting_volume_a: int
    starting_volume_b: int
    subsequent_workouts: list[WorkoutRecord]
    starting_weak_streak_a: int = 0
    starting_weak_streak_b: int = 0
    starting_work_sets_a: int = VOLUME_BLOCK.work_sets
    starting_stall_streak_a: int = 0


class ProgressionStrategy(Protocol):
    """Структурный контракт (волна 0, issue #158): "умеет preview/apply с
    этой сигнатурой" — НЕ общий датакласс контекста для всех реализаций.
    У StepProgressionStrategy (шаговая прогрессия подтягиваний) и
    PercentageProgressionStrategy (демо процентной программы, см. ниже)
    принципиально разная форма входа (ProgressionContext vs
    PercentageProgressionContext) — унификация контекста была бы ложной:
    у процентной программы нет понятий "слабый стрик"/"застой"/"потолок
    подходов", которые есть у шаговой. Единственное общее — обе отдают
    список WorkoutRecord, либо сухим прогоном (preview, БЕЗ побочных
    эффектов — вызывающий код, см. WorkoutRepository.preview_edit_workout,
    не пишет результат в БД), либо тем же расчётом, который потом реально
    применяется (apply)."""

    def preview(self, context) -> list[WorkoutRecord]: ...

    def apply(self, context) -> list[WorkoutRecord]: ...


class StepProgressionStrategy:
    """Шаговая прогрессия подтягиваний (единственная боевая программа на
    момент волны 0) — apply() целиком делегирует уже существующей чистой
    app.domain.progression.recalculate_cascade (не копирует её тело: тот
    же код, который раньше вызывал WorkoutRepository напрямую).

    preview() физически вызывает тот же apply(), не отдельную копию
    расчёта — так preview не может разойтись с apply по построению, а не
    только по факту зелёных тестов (issue #158, критерий готовности)."""

    def apply(self, context: ProgressionContext) -> list[WorkoutRecord]:
        return recalculate_cascade(
            context.starting_target_a,
            context.starting_target_b,
            context.starting_volume_a,
            context.starting_volume_b,
            context.subsequent_workouts,
            starting_weak_streak_a=context.starting_weak_streak_a,
            starting_weak_streak_b=context.starting_weak_streak_b,
            starting_work_sets_a=context.starting_work_sets_a,
            starting_stall_streak_a=context.starting_stall_streak_a,
        )

    def preview(self, context: ProgressionContext) -> list[WorkoutRecord]:
        return self.apply(context)


@dataclass(frozen=True)
class PercentageProgressionContext:
    """Вход PercentageProgressionStrategy — принципиально ДРУГАЯ форма,
    чем ProgressionContext (волна 0, issue #158, доказательство п.5 плана):
    нет ни стрика слабых/застойных тренировок, ни растущего числа рабочих
    подходов — процентная программа не знает этих понятий, насильно
    заполнять их заглушками было бы ложной унификацией.

    test_result — результат теста (условный аналог "2ПМ" у Crimpd, в
    повторениях или кг — эта демо-стратегия не уточняет единицу), от
    которого считается %."""

    test_result: int
    subsequent_workouts: list[WorkoutRecord]


class PercentageProgressionStrategy:
    """Демонстрационная вторая реализация ProgressionStrategy (issue #158,
    волна 0) — доказательство, что интерфейс preview/apply не заточен под
    шаговую логику подтягиваний. Никуда не подключена: конфиг Program и
    грейды ещё не существуют в БД на момент волны 0 (см. обсуждение в
    issue) — это только domain-модуль со своими тестами.

    target каждой записи блока Б = round(percentage * test_result), БЕЗ
    каскадной арифметики шагов/откатов/стриков — не итерация с бегущим
    состоянием, как у StepProgressionStrategy, а фиксированное значение,
    одинаковое для всех переданных тренировок (программа не переигрывает
    сами тренировки — только показывает, какой была бы цель при заданном
    результате теста). round() — обычное (Python round-half-to-even),
    для согласованности с остальным доменом (см. app.domain.progression).

    Блок A каждой записи проходит НЕТРОНУТЫМ (target_after остаётся её
    собственным target_before) — эта демо-версия описывает прогрессию
    только одного измерения (аналог "90% от 2ПМ" у Crimpd), не обе
    половины схемы подтягиваний."""

    def __init__(self, percentage: Decimal) -> None:
        self._percentage = percentage

    def apply(self, context: PercentageProgressionContext) -> list[WorkoutRecord]:
        target = round(self._percentage * context.test_result)
        updated = []
        for record in context.subsequent_workouts:
            block_b = replace(record.block_b, target_before=target, target_after=target, equipment_changed=False)
            updated.append(replace(record, block_b=block_b))
        return updated

    def preview(self, context: PercentageProgressionContext) -> list[WorkoutRecord]:
        return self.apply(context)
