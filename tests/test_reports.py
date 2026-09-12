from datetime import UTC, datetime
from decimal import Decimal

from app.domain.constants import EquipmentType, ExerciseType
from app.domain.reports import (
    all_cycles_analytics,
    current_equipment_progress,
    epley_progress,
    set_close_summary,
    weekly_summary,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord

BAND = Decimal("20.0")


def _record(
    day: int, *, a_reps=(15, 15, 15), a_max=16, b_reps=(3, 3, 3, 3), b_max=4,
    a_equipment_type=EquipmentType.BAND, a_equipment_value=BAND,
    b_equipment_type=EquipmentType.BAND, b_equipment_value=BAND,
    a_equipment_changed=False, b_equipment_changed=False,
    a_equipment_item_id=None, b_equipment_item_id=None,
    workout_set_id: int | None = None, exercise_type: ExerciseType | None = None,
    b_reported_volume: int | None = None, participates_in_cascade: bool = True,
) -> WorkoutRecord:
    return WorkoutRecord(
        performed_at=datetime(2026, 1, day, tzinfo=UTC),
        block_a=BlockAssignment(
            log=BlockLog(working_reps=a_reps, max_reps=a_max), target_before=10, target_after=11,
            equipment_changed=a_equipment_changed, equipment_type=a_equipment_type,
            equipment_value=a_equipment_value, equipment_item_id=a_equipment_item_id,
        ),
        block_b=BlockAssignment(
            log=BlockLog(working_reps=b_reps, max_reps=b_max, reported_volume=b_reported_volume),
            target_before=3, target_after=4,
            equipment_changed=b_equipment_changed, equipment_type=b_equipment_type,
            equipment_value=b_equipment_value, equipment_item_id=b_equipment_item_id,
        ),
        workout_set_id=workout_set_id, exercise_type=exercise_type,
        participates_in_cascade=participates_in_cascade,
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


# --- current_equipment_progress: BAND identity через equipment_item_id (Часть 8) --


def test_current_equipment_progress_band_kg_drift_does_not_break_segment():
    # Тот же физический снаряд (equipment_item_id=1), но kg введён по-разному
    # в разных тренировках (неточная маркировка резины в зале) — это НЕ
    # должно считаться сменой снаряда.
    first = _record(1, a_equipment_type=EquipmentType.BAND, a_equipment_item_id=1, a_equipment_value=Decimal("30.0"), a_max=12)
    second = _record(4, a_equipment_type=EquipmentType.BAND, a_equipment_item_id=1, a_equipment_value=Decimal("28.0"), a_max=16)

    progress = current_equipment_progress([first, second], "a")

    assert progress.equipment_item_id == 1
    assert progress.first_volume == 45 + 12
    assert progress.current_volume == 45 + 16


def test_current_equipment_progress_band_item_change_breaks_segment():
    older = _record(1, a_equipment_type=EquipmentType.BAND, a_equipment_item_id=1, a_max=12)
    newer = _record(4, a_equipment_type=EquipmentType.BAND, a_equipment_item_id=2, a_max=16)

    progress = current_equipment_progress([older, newer], "a")

    # Сегмент — только newer: другой equipment_item_id считается другим снарядом.
    assert progress.equipment_item_id == 2
    assert progress.first_volume == progress.current_volume == 45 + 16


# --- all_cycles_analytics ----------------------------------------------------------


def test_all_cycles_analytics_groups_by_workout_set_id_in_order():
    cycle_1 = [_record(1, workout_set_id=10), _record(2, workout_set_id=10)]
    cycle_2 = [_record(3, workout_set_id=11)]
    analytics = all_cycles_analytics([*cycle_1, *cycle_2])

    assert analytics.cycle_count == 2
    assert [c.workout_set_id for c in analytics.cycles] == [10, 11]
    assert analytics.cycles[0].workout_count == 2
    assert analytics.cycles[1].workout_count == 1
    assert analytics.total_volume == sum(r.block_a.log.volume + r.block_b.log.volume for r in [*cycle_1, *cycle_2])


def test_all_cycles_analytics_second_cycle_change_pct_relative_to_first():
    cycle_1 = [_record(1, workout_set_id=10, a_max=16)]  # volume = 45+16 + 12+4 = 77
    cycle_2 = [_record(2, workout_set_id=11, a_max=16)]  # same volume -> 0% change
    analytics = all_cycles_analytics([*cycle_1, *cycle_2])

    assert analytics.cycles[0].volume_change_pct is None  # первый цикл — сравнивать не с чем
    assert analytics.cycles[1].volume_change_pct == 0.0


def test_all_cycles_analytics_ignores_records_without_workout_set_id():
    records = [_record(1, workout_set_id=None), _record(2, workout_set_id=10)]
    analytics = all_cycles_analytics(records)

    assert analytics.cycle_count == 1
    assert analytics.cycles[0].workout_set_id == 10
    # Объём записи без workout_set_id не попадает даже в total_volume —
    # такая запись не входит ни в один цикл, значит не должна искажать
    # общую сумму по циклам.
    assert analytics.total_volume == records[1].block_a.log.volume + records[1].block_b.log.volume


def test_all_cycles_analytics_empty_history():
    analytics = all_cycles_analytics([])
    assert analytics.cycle_count == 0
    assert analytics.total_volume == 0
    assert analytics.cycles == []


# --- epley_progress (issue #96) -----------------------------------------------------

WEIGHT_KG = Decimal(70)


def _weight_record(day: int, *, equipment_value: Decimal, best_set: int = 6, **kwargs) -> WorkoutRecord:
    """best_set=6 по умолчанию для всех записей теста — держит формулу Эпли
    (1 + повторения/30) равной ровно 1.2, чтобы ожидаемые числа считались
    вручную без периодических дробей."""
    return _record(
        day, b_reps=(), b_max=best_set, b_equipment_type=EquipmentType.WEIGHT, b_equipment_value=equipment_value,
        **kwargs,
    )


def test_epley_progress_none_without_body_weight():
    records = [_weight_record(1, equipment_value=Decimal(10))]
    assert epley_progress(records, None) is None


def test_epley_progress_none_when_no_eligible_block_b():
    # Дефолт _record — блок Б на резине (BAND), формула Эпли для неё не
    # определена (issue #96: сопротивление резины физически неизвестно).
    records = [_record(1)]
    assert epley_progress(records, WEIGHT_KG) is None


def test_epley_progress_ignores_australian_block_b():
    records = [_record(1, b_equipment_type=EquipmentType.AUSTRALIAN, b_equipment_value=None)]
    assert epley_progress(records, WEIGHT_KG) is None


def test_epley_progress_ignores_backdate_total_without_max_reps():
    # issue #88: бэкдейт-итог блока Б без раскладки по подходам — best_set=0,
    # такая запись не должна попадать в расчёт Эпли вовсе (даже как "текущее
    # значение") — иначе "0 повторений" исказило бы формулу до голого веса.
    records = [_weight_record(1, equipment_value=Decimal(10), best_set=0, b_reported_volume=60)]
    assert epley_progress(records, WEIGHT_KG) is None


def test_epley_progress_single_official_record_matches_itself():
    # (70 + 10) кг × (1 + 6/30) = 80 × 1.2 = 96.0. Единственная официальная
    # тренировка блока Б — "прошлая"/"первая" совпадают с текущей (0%, не None).
    records = [_weight_record(1, equipment_value=Decimal(10))]
    progress = epley_progress(records, WEIGHT_KG)
    assert progress.current_load_kg == 96.0
    assert progress.change_pct_vs_previous == 0.0
    assert progress.change_pct_vs_first == 0.0


def test_epley_progress_compares_against_previous_and_first_official():
    # A: (70+10)×1.2=96.0, B: (70+15)×1.2=102.0, C: (70+20)×1.2=108.0
    a = _weight_record(1, equipment_value=Decimal(10))
    b = _weight_record(5, equipment_value=Decimal(15))
    c = _weight_record(10, equipment_value=Decimal(20))

    progress = epley_progress([a, b, c], WEIGHT_KG)

    assert progress.current_load_kg == 108.0
    assert progress.change_pct_vs_previous == round((108 - 102) / 102 * 100, 1)  # 5.9
    assert progress.change_pct_vs_first == 12.5  # (108-96)/96*100


def test_epley_progress_band_history_between_weight_records_does_not_break_it():
    # Резина между двумя тренировками на отягощении просто пропускается —
    # у неё нет знаковой шкалы, совместимой с кг Эпли, но остальные записи
    # блока Б по-прежнему сравниваются между собой как непрерывный ряд.
    a = _weight_record(1, equipment_value=Decimal(10))
    band = _record(3)  # блок Б на резине по умолчанию
    c = _weight_record(5, equipment_value=Decimal(20))

    progress = epley_progress([a, band, c], WEIGHT_KG)

    assert progress.current_load_kg == 108.0
    assert progress.change_pct_vs_previous == 12.5  # a — единственный официальный анкор до c
    assert progress.change_pct_vs_first == 12.5


def test_epley_progress_backdate_is_current_but_not_an_anchor():
    # A, B, C — официальные (участвуют в каскаде); D — бэкдейт (issue #88),
    # позже C по времени, виден как "текущее значение", но НЕ становится
    # анкором для %, сравнение всё равно идёт против последней/первой
    # ОФИЦИАЛЬНОЙ тренировки (C/A).
    a = _weight_record(1, equipment_value=Decimal(10))
    b = _weight_record(5, equipment_value=Decimal(15))
    c = _weight_record(10, equipment_value=Decimal(20))
    d = _weight_record(12, equipment_value=Decimal(26), participates_in_cascade=False)

    progress = epley_progress([a, b, c, d], WEIGHT_KG)

    assert progress.current_load_kg == 115.2  # (70+26)×1.2 — факт последней тренировки, включая бэкдейт
    assert progress.change_pct_vs_previous == round((115.2 - 108) / 108 * 100, 1)  # против C (последней официальной)
    assert progress.change_pct_vs_first == 20.0  # (115.2-96)/96*100, против A


def test_epley_progress_bodyweight_block_b_is_eligible_without_equipment_value():
    # BODYWEIGHT: отягощения нет, equipment_value=None — только вес тела.
    # 70 × (1 + 6/30) = 70 × 1.2 = 84.0.
    records = [
        _record(1, b_reps=(), b_max=6, b_equipment_type=EquipmentType.BODYWEIGHT, b_equipment_value=None),
    ]
    progress = epley_progress(records, WEIGHT_KG)
    assert progress.current_load_kg == 84.0
