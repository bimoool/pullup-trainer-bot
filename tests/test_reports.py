from datetime import UTC, datetime
from decimal import Decimal

from app.domain.constants import EquipmentType
from app.domain.reports import current_equipment_progress, set_close_summary, weekly_summary
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord

BAND = Decimal("20.0")


def _record(
    day: int, *, a_reps=(15, 15, 15), a_max=16, b_reps=(3, 3, 3, 3), b_max=4,
    a_equipment_type=EquipmentType.BAND, a_equipment_value=BAND,
    b_equipment_type=EquipmentType.BAND, b_equipment_value=BAND,
    a_equipment_changed=False, b_equipment_changed=False,
) -> WorkoutRecord:
    return WorkoutRecord(
        performed_at=datetime(2026, 1, day, tzinfo=UTC),
        block_a=BlockAssignment(
            log=BlockLog(working_reps=a_reps, max_reps=a_max), target_before=10, target_after=11,
            equipment_changed=a_equipment_changed, equipment_type=a_equipment_type,
            equipment_value=a_equipment_value,
        ),
        block_b=BlockAssignment(
            log=BlockLog(working_reps=b_reps, max_reps=b_max), target_before=3, target_after=4,
            equipment_changed=b_equipment_changed, equipment_type=b_equipment_type,
            equipment_value=b_equipment_value,
        ),
    )


def test_weekly_summary_counts_and_totals_volume():
    records = [_record(1), _record(3)]
    # каждая запись: block_a volume = 15+15+15+16=61, block_b = 3+3+3+3+4=16 -> 77 на запись
    summary = weekly_summary(records, previous_week_volume=100)

    assert summary.workout_count == 2
    assert summary.total_volume == 77 * 2
    assert summary.volume_change_pct == round((154 - 100) / 100 * 100, 1)


def test_weekly_summary_zero_previous_volume_gives_none_pct():
    summary = weekly_summary([_record(1)], previous_week_volume=0)
    assert summary.volume_change_pct is None


def test_weekly_summary_detects_equipment_changed_in_either_block():
    records = [_record(1), _record(3, b_equipment_changed=True)]
    summary = weekly_summary(records, previous_week_volume=0)
    assert summary.equipment_changed_a is False
    assert summary.equipment_changed_b is True


def test_current_equipment_progress_empty_history_is_none():
    assert current_equipment_progress([], "a") is None


def test_current_equipment_progress_isolates_contiguous_tail_segment():
    older = _record(1, a_equipment_type=EquipmentType.BAND, a_equipment_value=Decimal("30.0"), a_max=20)
    switch = _record(4, a_equipment_type=EquipmentType.BODYWEIGHT, a_equipment_value=None, a_max=12)
    later = _record(7, a_equipment_type=EquipmentType.BODYWEIGHT, a_equipment_value=None, a_max=18)

    progress = current_equipment_progress([older, switch, later], "a")

    assert progress.equipment_type == EquipmentType.BODYWEIGHT
    assert progress.equipment_value is None
    # объём блока a: working(15+15+15) + max
    assert progress.first_volume == 45 + 12  # switch — первая тренировка на новом снаряде
    assert progress.current_volume == 45 + 18  # later — последняя
    assert progress.change_pct == round((63 - 57) / 57 * 100, 1)


def test_current_equipment_progress_single_record_has_zero_change():
    progress = current_equipment_progress([_record(1)], "b")
    assert progress.first_volume == progress.current_volume
    assert progress.change_pct == 0.0


def test_set_close_summary_computes_growth_and_equipment_changes():
    first = _record(1, a_max=16, b_max=4)
    middle = _record(4, a_max=18, b_max=5, a_equipment_changed=True)
    last = _record(7, a_max=20, b_max=6)

    summary = set_close_summary([first, middle, last], previous_set_total_volume=200)

    assert summary.workout_count == 3
    assert summary.max_reps_growth_a == 20 - 16
    assert summary.max_reps_growth_b == 6 - 4
    assert summary.equipment_changes_count == 1
    assert summary.total_volume == sum(r.block_a.log.volume + r.block_b.log.volume for r in [first, middle, last])
    assert summary.volume_change_pct is not None


def test_set_close_summary_no_previous_set_gives_none_pct():
    summary = set_close_summary([_record(1)], previous_set_total_volume=None)
    assert summary.volume_change_pct is None


def test_set_close_summary_empty_records():
    summary = set_close_summary([], previous_set_total_volume=None)
    assert summary.workout_count == 0
    assert summary.total_volume == 0
    assert summary.max_reps_growth_a == 0
    assert summary.max_reps_growth_b == 0
