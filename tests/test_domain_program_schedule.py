from datetime import date

from app.domain.program_schedule import (
    block_target_label,
    count_per_week_label,
    course_week_number,
    duration_weeks,
)


def test_count_per_week_label_russian_plurals():
    assert count_per_week_label(1) == "1 раз в неделю"
    assert count_per_week_label(2) == "2 раза в неделю"
    assert count_per_week_label(4) == "4 раза в неделю"
    assert count_per_week_label(5) == "5 раз в неделю"
    assert count_per_week_label(11) == "11 раз в неделю"
    assert count_per_week_label(12) == "12 раз в неделю"


def test_duration_weeks_only_when_explicit_positive_int():
    assert duration_weeks({"duration_weeks": 8}) == 8
    assert duration_weeks({}) is None
    assert duration_weeks(None) is None
    assert duration_weeks({"duration_weeks": 0}) is None
    assert duration_weeks({"duration_weeks": True}) is None
    assert duration_weeks({"duration_weeks": "8"}) is None


def test_course_week_number():
    start = date(2026, 9, 1)
    assert course_week_number(start, date(2026, 9, 1), 8) == 1
    assert course_week_number(start, date(2026, 9, 7), 8) == 1
    assert course_week_number(start, date(2026, 9, 8), 8) == 2
    assert course_week_number(start, date(2027, 9, 8), 8) == 8  # после конца — последняя
    assert course_week_number(start, date(2026, 8, 1), 8) == 1  # до старта — первая
    assert course_week_number(start, date(2026, 9, 8), None) is None


def test_block_target_label():
    cfg = {"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}}
    assert block_target_label(cfg, "block_a") == "старт: 10 повт. × 3 подх."
    assert block_target_label(cfg, "block_b") == "старт: 3 повт."
    assert block_target_label(cfg, None) is None
    assert block_target_label({}, "block_a") is None
