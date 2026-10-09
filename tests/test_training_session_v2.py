"""Чистый домен TrainingSession v2 (issue #307, docs/domain/TRAINING_SESSION_V2.md) — без БД."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import training_analytics
from app.domain.training_session_v2 import (
    MAX_MEASURED_SECONDS,
    MIN_MEASURED_SECONDS,
    PRESCRIPTION_UNPRESCRIBED,
    REASON_ACTIVE,
    REASON_LEGACY_COPY,
    REASON_PROGRESSION,
    DurationSource,
    EditField,
    LogRecord,
    SessionFacts,
    SessionKind,
    SessionOrigin,
    SessionSourceV2,
    SessionTimes,
    SetStatus,
    SynthBlock,
    SynthSet,
    TargetRecord,
    clone_source,
    edit_verdict,
    entered_duration,
    legacy_duration,
    legacy_source_v2,
    measured_duration,
    move_session_date,
    recover_identity,
    set_outcomes,
    snapshot_matches_blocks,
    synthesize_snapshot,
)
from app.domain.workout_definition import SetKind, snapshot_from_dict

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


# --- источник (MIGRATION_V2 §3) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("legacy", "activity", "snapshot", "live", "recovered", "expected"),
    [
        ("plan", False, False, True, False, SessionSourceV2.PLANNED_LIVE),
        ("plan", False, False, False, False, SessionSourceV2.PLANNED_LIVE),
        ("freeform", True, False, False, False, SessionSourceV2.EXTERNAL_ACTIVITY),
        ("freeform", False, True, True, False, SessionSourceV2.DIRECT_LIVE),
        ("freeform", False, False, True, False, SessionSourceV2.DIRECT_LIVE),
        ("freeform", False, False, False, False, SessionSourceV2.MANUAL_CUSTOM),
        ("backdated", False, True, False, False, SessionSourceV2.MANUAL_EXISTING_WORKOUT),
        ("backdated", False, False, False, True, SessionSourceV2.MANUAL_EXISTING_WORKOUT),
        ("backdated", False, False, False, False, SessionSourceV2.MANUAL_CUSTOM),
        ("elective", False, False, False, False, SessionSourceV2.MANUAL_EXISTING_WORKOUT),
    ],
)
def test_legacy_source_mapping(legacy, activity, snapshot, live, recovered, expected):
    assert legacy_source_v2(
        legacy_source=legacy, has_activity=activity, has_workout_snapshot=snapshot, is_live=live,
        recovered_definition=recovered,
    ) is expected


def test_legacy_source_unknown_value_is_an_error():
    with pytest.raises(ValueError):
        legacy_source_v2(legacy_source="bogus", has_activity=False, has_workout_snapshot=False, is_live=False)


def test_clone_source_never_carries_plan_semantics():
    assert clone_source(original_kind=SessionKind.STRENGTH, workout_definition_id=7) is SessionSourceV2.MANUAL_EXISTING_WORKOUT
    assert clone_source(original_kind=SessionKind.STRENGTH, workout_definition_id=None) is SessionSourceV2.MANUAL_CUSTOM
    assert clone_source(original_kind=SessionKind.EXTERNAL_ACTIVITY, workout_definition_id=None) is (
        SessionSourceV2.EXTERNAL_ACTIVITY
    )


# --- идентичность (MIGRATION_V2 §3: только точное совпадение) ---------------------------------


def test_identity_recovery_exact_single_match_only():
    candidates = {10: {(1, 2)}, 11: {(3,)}, 12: {(2, 1)}}
    assert recover_identity([1, 2], candidates) == 10
    assert recover_identity([2, 1], candidates) == 12  # порядок важен
    assert recover_identity([1], candidates) is None  # подмножество — не совпадение
    assert recover_identity([], candidates) is None


def test_identity_recovery_ambiguous_is_never_guessed():
    candidates = {10: {(1, 2)}, 11: {(1, 2)}}
    assert recover_identity([1, 2], candidates) is None


def test_identity_recovery_matches_any_known_version():
    candidates = {10: {(1, 2), (1, 2, 3)}, 11: {(4,)}}
    assert recover_identity([1, 2, 3], candidates) == 10


# --- длительность (R3, R4) ------------------------------------------------------------------


def test_window_is_the_same_as_analytics():
    assert MIN_MEASURED_SECONDS == training_analytics.MIN_DURATION_SECONDS
    assert MAX_MEASURED_SECONDS == training_analytics.MAX_DURATION_SECONDS


def test_measured_duration_prefers_engine_active_time():
    # пауза 10 минут внутри часа: движок говорит 50 минут — это и есть длительность
    duration = measured_duration(T0, T0 + timedelta(hours=1), active_elapsed_ms=50 * 60 * 1000)
    assert duration.seconds == 3000 and duration.source is DurationSource.MEASURED


def test_measured_duration_wall_clock_window():
    assert measured_duration(T0, T0 + timedelta(minutes=25)).seconds == 1500
    assert measured_duration(T0, T0 + timedelta(seconds=30)).source is DurationSource.UNKNOWN
    assert measured_duration(T0, T0 + timedelta(days=2)).source is DurationSource.UNKNOWN
    assert measured_duration(T0, None).source is DurationSource.UNKNOWN
    with pytest.raises(ValueError):
        measured_duration(T0, T0, active_elapsed_ms=-1)


def test_entered_duration_is_never_zero():
    assert entered_duration(None).source is DurationSource.UNKNOWN
    assert entered_duration(None).seconds is None
    assert entered_duration(1800).seconds == 1800
    with pytest.raises(ValueError):
        entered_duration(0)


def test_legacy_duration_reproduces_analytics_minutes():
    manual = legacy_duration(has_activity=False, duration_seconds=None, performed_at=T0, completed_at=T0)
    assert manual.seconds is None and manual.source is DurationSource.UNKNOWN  # D13: не «0 минут»
    live = legacy_duration(
        has_activity=False, duration_seconds=None, performed_at=T0, completed_at=T0 + timedelta(minutes=40, seconds=30),
    )
    assert (live.seconds, live.source) == (2430, DurationSource.MEASURED)
    activity = legacy_duration(has_activity=True, duration_seconds=2700, performed_at=T0, completed_at=T0)
    assert (activity.seconds, activity.source) == (2700, DurationSource.ENTERED)


def test_move_session_date_keeps_duration():
    """R4/D13: перенос на прошлую неделю сдвигает все моменты на одну дельту — длительность прежняя."""
    times = SessionTimes(
        performed_at=T0, started_at=T0, ended_at=T0 + timedelta(minutes=40), completed_at=T0 + timedelta(minutes=40),
    )
    moved = move_session_date(times, T0 - timedelta(days=7))
    assert moved.performed_at == T0 - timedelta(days=7)
    assert moved.ended_at - moved.started_at == timedelta(minutes=40)
    assert moved.completed_at - moved.performed_at == timedelta(minutes=40)
    manual = move_session_date(SessionTimes(T0, None, None, T0), T0 - timedelta(days=1))
    assert manual.started_at is None and manual.completed_at == T0 - timedelta(days=1)


# --- ED1 ------------------------------------------------------------------------------------


def _facts(**overrides) -> SessionFacts:
    values = {
        "completed": True, "kind": SessionKind.STRENGTH, "source": SessionSourceV2.MANUAL_EXISTING_WORKOUT,
        "origin": SessionOrigin.NATIVE, "consumed_by_progression": False,
    }
    values.update(overrides)
    return SessionFacts(**values)


def test_ed1_manual_and_direct_sessions_are_fully_editable():
    for source in (SessionSourceV2.MANUAL_EXISTING_WORKOUT, SessionSourceV2.MANUAL_CUSTOM, SessionSourceV2.DIRECT_LIVE):
        verdict = edit_verdict(_facts(source=source))
        assert verdict.can_edit_sets and verdict.can_clone and EditField.DURATION in verdict.fields


def test_ed1_progression_session_metadata_only_and_no_clone():
    verdict = edit_verdict(_facts(source=SessionSourceV2.PLANNED_LIVE, consumed_by_progression=True))
    assert not verdict.can_edit_sets and not verdict.can_clone
    assert {EditField.DATE, EditField.DURATION, EditField.EFFORT, EditField.COMMENT, EditField.SET_NOTES} == verdict.fields
    assert verdict.reason == REASON_PROGRESSION


def test_ed1_external_activity_fields():
    verdict = edit_verdict(_facts(kind=SessionKind.EXTERNAL_ACTIVITY, source=SessionSourceV2.EXTERNAL_ACTIVITY))
    assert verdict.fields == {
        EditField.DATE, EditField.DURATION, EditField.EFFORT, EditField.COMMENT, EditField.ACTIVITY_TYPE,
        EditField.DISTANCE,
    }
    assert not verdict.can_edit_sets


def test_ed1_active_and_legacy_copies_are_read_only():
    active = edit_verdict(_facts(completed=False))
    assert not active.can_edit and not active.can_clone and active.reason == REASON_ACTIVE
    copy = edit_verdict(_facts(origin=SessionOrigin.LEGACY_BACKFILL))
    assert not copy.can_edit and copy.reason == REASON_LEGACY_COPY


def test_ed1_elective_editable_but_not_cloneable():
    verdict = edit_verdict(_facts(origin=SessionOrigin.LEGACY_ELECTIVE))
    assert verdict.can_edit_sets and not verdict.can_clone


# --- факт vs рецепт (R1/R2) -----------------------------------------------------------------


def _targets(*values, max_last=False):
    return [
        TargetRecord(set_number=i + 1, value=Decimal(v), is_max_set=max_last and i == len(values) - 1)
        for i, v in enumerate(values)
    ]


def _logs(*values, extra=()):
    logs = [LogRecord(set_number=i + 1, value=Decimal(v), is_max_set=False, is_extra=False) for i, v in enumerate(values)]
    return logs + [
        LogRecord(set_number=len(values) + j + 1, value=Decimal(v), is_max_set=False, is_extra=True)
        for j, v in enumerate(extra)
    ]


def test_actual_differs_from_prescription_is_preserved():
    """J4: рецепт 4 × 6, факт 6/6/5/4 — история хранит 6/6/5/4, а не 6/6/6/6."""
    outcomes = set_outcomes(_targets(6, 6, 6, 6), _logs(6, 6, 5, 4))
    assert [o.actual for o in outcomes] == [6, 6, 5, 4]
    assert [o.target for o in outcomes] == [6, 6, 6, 6]
    assert all(o.status is SetStatus.PERFORMED and not o.is_extra for o in outcomes)


def test_skipped_and_extra_sets_are_distinguishable():
    """J5: две цели из четырёх не выполнены; один подход сверх плана."""
    outcomes = set_outcomes(_targets(6, 6, 6, 6), _logs(6, 5, extra=(3,)))
    assert [o.status for o in outcomes] == [
        SetStatus.PERFORMED, SetStatus.PERFORMED, SetStatus.NOT_PERFORMED, SetStatus.NOT_PERFORMED, SetStatus.PERFORMED,
    ]
    assert [o.actual for o in outcomes[2:4]] == [None, None]
    assert outcomes[4].is_extra and outcomes[4].prescribed_set_number is None and outcomes[4].actual == 3


def test_planned_logs_beyond_targets_are_extra():
    outcomes = set_outcomes(_targets(5), _logs(5, 5))
    assert [o.is_extra for o in outcomes] == [False, True]


def test_max_set_flag_comes_from_target():
    """R2/J6: SetLog до #305 писался с is_max_set=False — исход берёт признак у цели."""
    outcomes = set_outcomes(_targets(3, 3, 0, max_last=True), _logs(3, 3, 7))
    assert [o.is_max_set for o in outcomes] == [False, False, True]
    assert outcomes[2].actual == 7


def test_explicit_not_performed_log():
    logs = [LogRecord(1, Decimal(0), False, False, status=SetStatus.NOT_PERFORMED)]
    [outcome] = set_outcomes(_targets(6), logs)
    assert outcome.status is SetStatus.NOT_PERFORMED and outcome.actual is None


# --- синтезированный снимок (S4) ------------------------------------------------------------


def _block(exercise_id: int, *sets: SynthSet, interval: bool = False) -> SynthBlock:
    return SynthBlock(exercise_id, f"E{exercise_id}", exercise_id, None, tuple(sets), is_interval=interval)


def test_synthesized_snapshot_round_trips_and_keeps_max_set():
    data = synthesize_snapshot(
        title="Подтягивания", resolved_at=T0, unprescribed=False, program_inclusion_id=5,
        blocks=[_block(1, SynthSet("reps", Decimal(3)), SynthSet("reps", Decimal(0), is_max_set=True)),
                _block(2, interval=True)],
    )
    snapshot = snapshot_from_dict(data)
    assert snapshot.synthesized and snapshot.provenance.program_inclusion_id == 5
    assert [s.kind for s in snapshot.blocks[0].sets] == [SetKind.REPS, SetKind.MAX_REPS]
    assert snapshot.blocks[1].kind.value == "interval"
    assert "prescription_kind" not in data


def test_unprescribed_snapshot_is_marked():
    data = synthesize_snapshot(
        title="", resolved_at=T0, unprescribed=True, blocks=[_block(1, SynthSet("time", Decimal(45)))],
    )
    assert data["prescription_kind"] == PRESCRIPTION_UNPRESCRIBED
    assert snapshot_from_dict(data).blocks[0].sets[0].target_seconds == 45


def test_synthesis_is_deterministic():
    blocks = [_block(1, SynthSet("reps", Decimal(8)))]
    first = synthesize_snapshot(title="X", resolved_at=T0, unprescribed=False, blocks=blocks)
    assert synthesize_snapshot(title="X", resolved_at=T0, unprescribed=False, blocks=blocks) == first


def test_snapshot_matches_blocks():
    data = synthesize_snapshot(
        title="X", resolved_at=T0, unprescribed=False,
        blocks=[_block(1, SynthSet("reps", Decimal(8)), SynthSet("reps", Decimal(8)))],
    )
    assert snapshot_matches_blocks(data, [(1, 2)])
    assert not snapshot_matches_blocks(data, [(1, 3)])  # другое число подходов
    assert not snapshot_matches_blocks(data, [(2, 2)])  # другое упражнение
    assert not snapshot_matches_blocks(data, [(1, 2), (3, 1)])
