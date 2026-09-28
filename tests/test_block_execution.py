"""REBUILD-1 (R1): чистая логика целей блока из resolved-протокола и отдыха из
протокола в фазовой машине."""

from app.domain.block_execution import rest_seconds_for_protocol, targets_for_protocol
from app.domain.live_session import (
    DEFAULT_REST_SECONDS,
    BlockPlan,
    PhaseState,
    SessionPhaseName,
    next_phase,
)
from app.domain.multi_program import MetricType
from app.domain.workout_protocol import (
    ResolvedInterval,
    ResolvedMaxEffort,
    ResolvedMaxEffortAttempt,
    ResolvedRepsSets,
    ResolvedSetTarget,
    ResolvedTimeSets,
    ResolvedTimeSetTarget,
)


def test_reps_time_max_interval_targets():
    reps = ResolvedRepsSets(sets=[ResolvedSetTarget(target_reps=8)] * 3, rest_seconds=45)
    time_ = ResolvedTimeSets(sets=[ResolvedTimeSetTarget(target_seconds=30)] * 2, rest_seconds=20)
    max_ = ResolvedMaxEffort(attempts=[ResolvedMaxEffortAttempt(is_max=True)] * 2, rest_seconds=0)
    interval = ResolvedInterval(total_duration_seconds=60, work_seconds=10, rest_seconds=20, starts_with="work")

    assert [(t.value, t.unit) for t in targets_for_protocol(reps, MetricType.REPS)] == [(8, "reps")] * 3
    assert [(t.value, t.unit) for t in targets_for_protocol(time_, MetricType.TIME)] == [(30, "s")] * 2
    max_targets = targets_for_protocol(max_, MetricType.REPS)
    assert [(t.value, t.is_max_set) for t in max_targets] == [(0, True)] * 2
    assert targets_for_protocol(interval, MetricType.REPS) == []


def test_rest_seconds_from_protocol_drives_phase_machine():
    reps = ResolvedRepsSets(sets=[ResolvedSetTarget(target_reps=8)] * 2, rest_seconds=45)
    assert rest_seconds_for_protocol(reps) == 45
    assert rest_seconds_for_protocol(None) is None

    go = PhaseState(SessionPhaseName.GO, block_index=0, set_number=1, ends_at_offset_seconds=None)
    assert next_phase(go, [BlockPlan(2, rest_seconds=45)]).ends_at_offset_seconds == 45
    assert next_phase(go, [BlockPlan(2)]).ends_at_offset_seconds == DEFAULT_REST_SECONDS
