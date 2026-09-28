"""Чистая логика исполнения одного блока Builder-тренировки (REBUILD-1, R1):
как resolved-протокол из замороженного WorkoutSnapshot превращается в цели
подходов (SetTarget) и в паузу отдыха. Единственный источник целей для
Builder-блоков — протокол из снапшота, а не устаревшие ComplexItem.sets/
target_value (те остаются только для legacy protocol=None, см.
app.services.live_session). Домен не знает про SQLAlchemy/время."""

from dataclasses import dataclass

from app.domain.multi_program import MetricType
from app.domain.workout_protocol import (
    ProtocolType,
    ResolvedInterval,
    ResolvedMaxEffort,
    ResolvedProtocol,
    ResolvedRepsSets,
    ResolvedTimeSets,
)


@dataclass(frozen=True)
class ProtocolTarget:
    """Одна цель подхода/попытки, выведенная из протокола. value=0 у
    max_effort — цели нет (попытка "сколько получится"), потребитель обязан
    не показывать такой ноль как план."""

    set_number: int
    metric_type: MetricType
    value: int
    unit: str
    is_max_set: bool = False


def targets_for_protocol(protocol: ResolvedProtocol, exercise_metric: MetricType) -> list[ProtocolTarget]:
    """reps_sets -> N целей в повторениях; time_sets -> N целей в секундах;
    max_effort -> N попыток (метрика — метрика самого упражнения, цели нет);
    interval -> ноль целей (таймер сервера, не подходы)."""
    if isinstance(protocol, ResolvedRepsSets):
        return [
            ProtocolTarget(i + 1, MetricType.REPS, s.target_reps, "reps")
            for i, s in enumerate(protocol.sets)
        ]
    if isinstance(protocol, ResolvedTimeSets):
        return [
            ProtocolTarget(i + 1, MetricType.TIME, s.target_seconds, "s")
            for i, s in enumerate(protocol.sets)
        ]
    if isinstance(protocol, ResolvedMaxEffort):
        unit = "s" if exercise_metric == MetricType.TIME else "reps"
        metric = MetricType.TIME if exercise_metric == MetricType.TIME else MetricType.REPS
        return [
            ProtocolTarget(i + 1, metric, 0, unit, is_max_set=True)
            for i, _ in enumerate(protocol.attempts)
        ]
    return []


def rest_seconds_for_protocol(protocol: ResolvedProtocol | None) -> int | None:
    """Отдых между подходами из протокола; None — у legacy/interval блока
    своей паузы нет, вызывающий берёт продуктовый дефолт."""
    if isinstance(protocol, (ResolvedRepsSets, ResolvedTimeSets, ResolvedMaxEffort)):
        return protocol.rest_seconds
    return None


def is_interval_protocol(protocol: ResolvedProtocol | None) -> bool:
    return protocol is not None and protocol.type == ProtocolType.INTERVAL


def interval_protocol(protocol: ResolvedProtocol | None) -> ResolvedInterval | None:
    return protocol if isinstance(protocol, ResolvedInterval) else None
