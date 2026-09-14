from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain.constants import EquipmentType
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord
from app.domain.wsf import FEMALE, MALE, calculate_wsf_status

TODAY = date(2026, 9, 13)


def _birth_date_for_exact_age(years: int) -> date:
    return date(TODAY.year - years, TODAY.month, TODAY.day)


def _record(
    day: int,
    *,
    b_equipment_type: EquipmentType = EquipmentType.WEIGHT,
    b_equipment_value: Decimal | None = Decimal(0),
    b_max_reps: int = 0,
    b_reported_volume: int | None = None,
) -> WorkoutRecord:
    return WorkoutRecord(
        performed_at=datetime(2026, 1, day, tzinfo=UTC),
        block_a=BlockAssignment(
            log=BlockLog(working_reps=(15, 15, 15), max_reps=16), target_before=10, target_after=11,
            equipment_changed=False, equipment_type=EquipmentType.BODYWEIGHT,
        ),
        block_b=BlockAssignment(
            log=BlockLog(working_reps=(), max_reps=b_max_reps, reported_volume=b_reported_volume),
            target_before=3, target_after=4, equipment_changed=False,
            equipment_type=b_equipment_type, equipment_value=b_equipment_value,
        ),
    )


def test_missing_gender():
    status = calculate_wsf_status(gender=None, weight_kg=Decimal(70), birth_date=None, records=[], today=TODAY)
    assert status.applicable is False
    assert status.reason == "missing_gender"


def test_missing_weight():
    status = calculate_wsf_status(gender=MALE, weight_kg=None, birth_date=None, records=[], today=TODAY)
    assert status.applicable is False
    assert status.reason == "missing_weight"


def test_no_workouts_with_empty_history():
    status = calculate_wsf_status(gender=MALE, weight_kg=Decimal(58), birth_date=None, records=[], today=TODAY)
    assert status.applicable is False
    assert status.reason == "no_workouts"
    assert status.weight_category == "60"


def test_no_workouts_when_only_band_block_b():
    records = [_record(1, b_equipment_type=EquipmentType.BAND, b_equipment_value=Decimal(20), b_max_reps=10)]
    status = calculate_wsf_status(gender=MALE, weight_kg=Decimal(58), birth_date=None, records=records, today=TODAY)
    assert status.applicable is False
    assert status.reason == "no_workouts"


def test_no_workouts_when_backdate_total_without_max_reps():
    # issue #88: bce итог без раскладки — best_set=0, не должно попадать в расчёт.
    records = [_record(1, b_max_reps=0, b_reported_volume=60)]
    status = calculate_wsf_status(gender=MALE, weight_kg=Decimal(58), birth_date=None, records=records, today=TODAY)
    assert status.applicable is False
    assert status.reason == "no_workouts"


def test_norm_data_missing_for_women_at_uncovered_weight_step():
    # Женщины: добавленное отягощение 25/35/50 кг не покрыто таблицей вовсе
    # (см. wsf_multirep_norms.json) — 30 кг фактически округляется вниз до
    # ступени 25, для которой данных нет ни у одной весовой категории.
    records = [_record(1, b_equipment_value=Decimal(30), b_max_reps=10)]
    status = calculate_wsf_status(gender=FEMALE, weight_kg=Decimal(50), birth_date=None, records=records, today=TODAY)
    assert status.applicable is False
    assert status.reason == "norm_data_missing"
    assert status.weight_category == "52"


def test_bodyweight_rank_and_next_rank():
    # non_tested/0/men/60: elite56 msmk43 ms33 kms25 i20 ii16 iii14.
    # 58 кг -> категория "60" (минимальная >= фактического веса).
    records = [_record(1, b_equipment_type=EquipmentType.BODYWEIGHT, b_equipment_value=None, b_max_reps=20)]

    status = calculate_wsf_status(gender=MALE, weight_kg=Decimal(58), birth_date=None, records=records, today=TODAY)

    assert status.applicable is True
    assert status.weight_category == "60"
    assert status.added_weight_step_kg == Decimal(0)
    assert status.actual_added_weight_kg == Decimal(0)
    assert status.rank == "i"
    assert status.best_reps == 20
    assert status.next_rank == "kms"
    assert status.reps_to_next_rank == 5  # 25 - 20


def test_added_weight_rounds_down_to_step_below():
    # Кириллов пример из issue #104: реальные +23 кг -> ступень 15.
    # non_tested/15/men/60: elite23 msmk18 ms14 kms12 i11 ii10 iii9.
    records = [_record(1, b_equipment_value=Decimal(23), b_max_reps=10)]

    status = calculate_wsf_status(gender=MALE, weight_kg=Decimal(58), birth_date=None, records=records, today=TODAY)

    assert status.applicable is True
    assert status.added_weight_step_kg == Decimal(15)
    assert status.actual_added_weight_kg == Decimal(23)
    assert status.rank == "ii"
    assert status.next_rank == "i"
    assert status.reps_to_next_rank == 1  # 11 - 10


def test_best_rank_kept_across_history_even_if_not_latest():
    # non_tested/0/men/60: kms=25, ms=33. Первая тренировка достигает kms,
    # вторая (позже, но слабее) — вообще без разряда: итоговый статус должен
    # остаться на лучшем ЗА ВСЮ ИСТОРИЮ (kms), не откатываться на "none".
    strong = _record(1, b_equipment_type=EquipmentType.BODYWEIGHT, b_equipment_value=None, b_max_reps=25)
    weak = _record(5, b_equipment_type=EquipmentType.BODYWEIGHT, b_equipment_value=None, b_max_reps=5)

    status = calculate_wsf_status(
        gender=MALE, weight_kg=Decimal(58), birth_date=None, records=[strong, weak], today=TODAY,
    )

    assert status.rank == "kms"
    assert status.best_reps == 25
    assert status.next_rank == "ms"
    assert status.reps_to_next_rank == 8  # 33 - 25


def test_elite_rank_has_no_next_rank():
    # non_tested/0/men/999 (открытая категория): elite=40.
    records = [_record(1, b_equipment_type=EquipmentType.BODYWEIGHT, b_equipment_value=None, b_max_reps=45)]

    status = calculate_wsf_status(gender=MALE, weight_kg=Decimal(120), birth_date=None, records=records, today=TODAY)

    assert status.weight_category == "999"
    assert status.rank == "elite"
    assert status.next_rank is None
    assert status.reps_to_next_rank is None


def test_age_bonus_lets_lower_real_reps_reach_next_rank():
    # non_tested/15/men/60: ii=10, i=11, iii=9. Возраст 55 -> бонус +15%
    # (округление результата ВНИЗ): 9 реальных повторений -> floor(9*1.15)=10
    # -> разряд II (без бонуса было бы только III, порог 9). Не хватает 1
    # реального повторения до I: floor(10*1.15)=11 удовлетворяет i=11.
    records = [_record(1, b_equipment_value=Decimal(23), b_max_reps=9)]

    status = calculate_wsf_status(
        gender=MALE, weight_kg=Decimal(58), birth_date=_birth_date_for_exact_age(55), records=records, today=TODAY,
    )

    assert status.age_bonus_pct == Decimal("0.15")
    assert status.rank == "ii"
    assert status.best_reps == 9
    assert status.next_rank == "i"
    assert status.reps_to_next_rank == 1


def test_thresholds_output_excludes_null_cells():
    # non_tested/50/men/48: [7,5,2,null,null,null,null] -> только elite/msmk/ms.
    records = [_record(1, b_equipment_value=Decimal(50), b_max_reps=5)]

    status = calculate_wsf_status(gender=MALE, weight_kg=Decimal(46), birth_date=None, records=records, today=TODAY)

    assert status.weight_category == "48"
    assert [t.rank for t in status.thresholds] == ["elite", "msmk", "ms"]
    assert status.rank == "msmk"
    assert status.next_rank == "elite"
    assert status.reps_to_next_rank == 2  # 7 - 5
