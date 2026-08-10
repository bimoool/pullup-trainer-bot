from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain.constants import EquipmentType
from app.domain.recommendations import (
    RecommendationCode,
    check_consistent_streak,
    check_equipment_too_light,
    check_minimal_rest_volume_drop,
    check_underworking_sets,
    check_weak_set_index,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord

BAND = Decimal("20.0")


def _record(
    day: int, *, a_reps=(15, 15, 15), a_max=16, target_before=10,
    a_equipment_type=EquipmentType.BAND, a_equipment_value=BAND, a_equipment_item_id=None,
) -> WorkoutRecord:
    return WorkoutRecord(
        performed_at=datetime(2026, 1, day, tzinfo=UTC),
        block_a=BlockAssignment(
            log=BlockLog(working_reps=a_reps, max_reps=a_max), target_before=target_before, target_after=11,
            equipment_changed=False, equipment_type=a_equipment_type, equipment_value=a_equipment_value,
            equipment_item_id=a_equipment_item_id,
        ),
        block_b=BlockAssignment(
            log=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4), target_before=3, target_after=4,
            equipment_changed=False, equipment_type=EquipmentType.BAND, equipment_value=BAND,
        ),
    )


# --- check_underworking_sets ------------------------------------------------------


def test_underworking_sets_triggers_on_large_gap():
    record = _record(1, a_reps=(10, 10, 10), a_max=16)  # gap = 16-10 = 6 >= 5
    result = check_underworking_sets(record, "a")
    assert result.code == RecommendationCode.UNDERWORKING_SETS
    assert result.context["gap"] == 6.0


def test_underworking_sets_no_trigger_on_small_gap():
    record = _record(1, a_reps=(15, 15, 15), a_max=16)  # gap = 1
    assert check_underworking_sets(record, "a") is None


# --- check_equipment_too_light -----------------------------------------------------


def test_equipment_too_light_triggers_when_max_beats_target_repeatedly():
    records = [_record(day, a_max=16, target_before=10) for day in (1, 4, 7)]  # gap=6 >= 5, каждый раз
    result = check_equipment_too_light(records, "a")
    assert result.code == RecommendationCode.EQUIPMENT_TOO_LIGHT


def test_equipment_too_light_no_trigger_with_not_enough_history():
    records = [_record(1, a_max=16, target_before=10), _record(4, a_max=16, target_before=10)]
    assert check_equipment_too_light(records, "a") is None


def test_equipment_too_light_no_trigger_when_band_item_changed_mid_lookback():
    # Идентичность резины — по equipment_item_id (личный список, Часть 8),
    # не по equipment_value (kg часто неизвестен/неточен) — смена item_id
    # означает реальную смену снаряда и должна сбрасывать окно lookback.
    records = [
        _record(1, a_max=16, target_before=10, a_equipment_item_id=1),
        _record(4, a_max=16, target_before=10, a_equipment_item_id=2),
        _record(7, a_max=16, target_before=10, a_equipment_item_id=2),
    ]
    assert check_equipment_too_light(records, "a") is None


def test_equipment_too_light_still_triggers_when_only_band_kg_estimate_drifts():
    # Тот же физический снаряд (equipment_item_id не меняется), но kg
    # каждый раз введён/пересчитан немного по-разному — это НЕ должно
    # считаться сменой снаряда и НЕ должно блокировать рекомендацию.
    records = [
        _record(1, a_max=16, target_before=10, a_equipment_item_id=1, a_equipment_value=Decimal("30.0")),
        _record(4, a_max=16, target_before=10, a_equipment_item_id=1, a_equipment_value=Decimal("20.0")),
        _record(7, a_max=16, target_before=10, a_equipment_item_id=1, a_equipment_value=Decimal("20.0")),
    ]
    result = check_equipment_too_light(records, "a")
    assert result.code == RecommendationCode.EQUIPMENT_TOO_LIGHT


def test_equipment_too_light_no_trigger_when_close_to_target():
    records = [_record(day, a_max=11, target_before=10) for day in (1, 4, 7)]  # gap=1
    assert check_equipment_too_light(records, "a") is None


# --- check_weak_set_index -----------------------------------------------------------


def test_weak_set_index_detects_consistently_low_position():
    records = [_record(day, a_reps=(15, 15, 5)) for day in (1, 4, 7)]  # третий подход стабильно ниже
    result = check_weak_set_index(records, "a")
    assert result.code == RecommendationCode.WEAK_SET_INDEX
    assert result.context["set_number"] == 3


def test_weak_set_index_no_trigger_when_even():
    records = [_record(day, a_reps=(15, 15, 15)) for day in (1, 4, 7)]
    assert check_weak_set_index(records, "a") is None


# --- check_minimal_rest_volume_drop -------------------------------------------------


def test_minimal_rest_volume_drop_triggers():
    # MIN_REST_DAYS=2, margin=1 -> промежутки <=3 дня; объём падает: 61,55,50 (a) + 16 (b фикс.)
    records = [
        _record(1, a_reps=(15, 15, 15), a_max=16),  # объём a = 61
        _record(4, a_reps=(13, 13, 13), a_max=14),  # объём a = 53
        _record(7, a_reps=(10, 10, 10), a_max=11),  # объём a = 41
    ]
    result = check_minimal_rest_volume_drop(records)
    assert result.code == RecommendationCode.MINIMAL_REST_VOLUME_DROP


def test_minimal_rest_volume_drop_no_trigger_when_rest_is_generous():
    records = [_record(1), _record(10), _record(20)]  # большие промежутки — не "на грани"
    assert check_minimal_rest_volume_drop(records) is None


def test_minimal_rest_volume_drop_no_trigger_when_volume_grows():
    records = [
        _record(1, a_reps=(10, 10, 10), a_max=11),
        _record(4, a_reps=(13, 13, 13), a_max=14),
        _record(7, a_reps=(15, 15, 15), a_max=16),
    ]
    assert check_minimal_rest_volume_drop(records) is None


# --- check_consistent_streak --------------------------------------------------------


def test_consistent_streak_triggers_with_no_gaps():
    records = [_record(d) for d in (1, 5, 10, 15, 20)]
    result = check_consistent_streak(records, current_date=date(2026, 1, 21))
    assert result.code == RecommendationCode.CONSISTENT_STREAK


def test_consistent_streak_no_trigger_with_big_gap():
    # окно — последние 21 день от 31 января (с 10 января); тренировка в
    # самом начале окна и одна в самом конце — разрыв между ними ровно
    # 21 день, это уже не "без пропусков"
    records = [_record(10), _record(31)]
    result = check_consistent_streak(records, current_date=date(2026, 1, 31))
    assert result is None


def test_consistent_streak_no_trigger_with_empty_history():
    assert check_consistent_streak([], current_date=date(2026, 1, 21)) is None
