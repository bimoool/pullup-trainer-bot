"""Каноническая история — чистый домен (issue #308, TRAINING_SESSION_V2 §6 A2/A3/A5). Без БД."""

import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.domain.canonical_history import (
    AttributionBlock,
    allocate_largest_remainder,
    attribute_primary_category,
    round_minutes,
)
from app.domain.exercise_identity import (
    OTHER_ACTIVITY_LABEL,
    UNCATEGORIZED_LABEL,
    category_label,
    looks_like_internal_key,
    subcategory_label,
)
from app.domain.training_analytics import AnalyticsSession, compute_metrics_series

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
TZ = ZoneInfo("UTC")


# --- A5: минуты ----------------------------------------------------------------------------------------


def test_round_minutes_is_half_up_integer_math():
    assert [round_minutes(s) for s in (0, 29, 30, 59, 89, 90, 149, 150)] == [0, 0, 1, 1, 1, 2, 2, 3]


def test_largest_remainder_hands_extra_minutes_to_biggest_remainders_then_earlier_parts():
    assert allocate_largest_remainder([30, 30, 30]) == [1, 1, 0]  # итог 2: тай-брейк — раньше стоящая
    assert allocate_largest_remainder([90, 59, 0]) == [1, 1, 0]  # 149 с -> 2: остаток 59 > 30
    assert allocate_largest_remainder([0, 0]) == [0, 0]
    # пустая часть минуту сверх нуля не получает, даже когда есть что раздавать
    assert allocate_largest_remainder([59, 0, 1]) == [1, 0, 0]


def test_largest_remainder_rejects_an_unreachable_total():
    with pytest.raises(ValueError):
        allocate_largest_remainder([10, 10], total_minutes=5)
    with pytest.raises(ValueError):
        allocate_largest_remainder([120, 120], total_minutes=1)


def test_largest_remainder_always_sums_to_the_total_property():
    rng = random.Random(308)
    for _ in range(500):
        parts = [rng.choice([0, 0, rng.randint(1, 59), rng.randint(60, 7200)]) for _ in range(rng.randint(1, 12))]
        result = allocate_largest_remainder(parts)
        assert sum(result) == round_minutes(sum(parts))
        assert all(m in (p // 60, p // 60 + 1) for m, p in zip(result, parts, strict=True))
        assert all(m == 0 for m, p in zip(result, parts, strict=True) if p == 0)


def _session(day: date, seconds: int | None) -> AnalyticsSession:
    return AnalyticsSession(
        performed_at=datetime(day.year, day.month, day.day, 10, tzinfo=UTC), blocks=[], duration_seconds=seconds,
    )


def test_weekly_minutes_sum_exactly_to_the_total_and_unknown_duration_is_counted_not_zeroed():
    # три недели по 40 с + одна неделя без длительности: поминутное усечение дало бы 0+0+0, итог 120 с = 2 мин
    sessions = [
        _session(date(2026, 9, 7), 40), _session(date(2026, 9, 14), 40), _session(date(2026, 9, 21), 40),
        _session(date(2026, 9, 28), None),
    ]
    series = compute_metrics_series(sessions, date(2026, 9, 7), date(2026, 10, 4), NOW, TZ)
    assert series.total_workouts == 4 and series.without_duration == 1
    assert series.total_seconds == 120 and series.total_minutes == 2
    assert [w.minutes for w in series.weeks] == [1, 1, 0, 0]
    assert sum(w.minutes for w in series.weeks) == series.total_minutes
    assert [w.workouts for w in series.weeks] == [1, 1, 1, 1]  # неизвестная длительность — всё равно тренировка


def test_weekly_minutes_reconcile_on_random_histories():
    rng = random.Random(1308)
    for _ in range(200):
        base = date(2026, 1, 5)
        sessions = [
            _session(base + timedelta(days=rng.randint(0, 90)), rng.choice([None, rng.randint(61, 7000)]))
            for _ in range(rng.randint(0, 25))
        ]
        series = compute_metrics_series(sessions, base, base + timedelta(days=90), NOW, TZ)
        assert sum(w.minutes for w in series.weeks) == series.total_minutes == round_minutes(series.total_seconds)
        assert sum(w.workouts for w in series.weeks) == series.total_workouts == len(sessions)
        assert series.without_duration == sum(s.duration_seconds is None for s in sessions)


# --- A2: одна категория на сессию ------------------------------------------------------------------------


def _block(category, sub=None, sets=1):
    return AttributionBlock(category=category, subcategory=sub, performed_sets=sets)


def test_course_session_is_pull_ups_whatever_the_service_subcategories():
    result = attribute_primary_category(
        is_external_activity=False, activity_label=None,
        blocks=[_block("pull_ups", "block_a", 3), _block("pull_ups", "block_b", 5)],
    )
    assert (result.category, result.subcategory) == ("Подтягивания", None)  # block_a/block_b — служебные


def test_custom_strength_picks_the_block_with_most_performed_sets_and_ties_go_to_the_first():
    blocks = [_block("Хват", None, 2), _block("general_fitness", None, 5), _block("user", None, 5)]
    assert attribute_primary_category(is_external_activity=False, activity_label=None, blocks=blocks).category == (
        "Общая физическая подготовка"
    )
    assert attribute_primary_category(
        is_external_activity=False, activity_label=None, blocks=[_block("Хват", None, 1), _block("user", None, 1)],
    ).category == "Хват"


def test_interval_and_elective_and_empty_sessions_follow_the_same_rule():
    interval = attribute_primary_category(
        is_external_activity=False, activity_label=None, blocks=[_block("general_fitness", None, 0)],
    )
    assert interval.category == "Общая физическая подготовка"  # блок без подходов (интервал) всё равно блок
    elective = attribute_primary_category(
        is_external_activity=False, activity_label=None, blocks=[_block("pull_ups", "elective_w_ladder", 1)],
    )
    assert (elective.category, elective.subcategory) == ("Подтягивания", None)
    assert attribute_primary_category(is_external_activity=False, activity_label=None, blocks=[]).category == (
        UNCATEGORIZED_LABEL
    )


def test_external_activity_is_other_activity_with_its_display_name_as_subcategory():
    result = attribute_primary_category(is_external_activity=True, activity_label="Бег", blocks=[])
    assert (result.category, result.subcategory) == (OTHER_ACTIVITY_LABEL, "Бег")
    assert attribute_primary_category(is_external_activity=True, activity_label=None, blocks=[]).subcategory is None


# --- A3: только человеческие подписи --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", ["pull_ups", "block_a", "block_b", "user", "manual_custom", "elective_w_ladder", "dist274_x", "journal-log", None, ""],
)
def test_no_internal_key_ever_becomes_a_category_label(raw):
    label = category_label(raw)
    assert not looks_like_internal_key(label), label
    assert subcategory_label(raw) is None or not looks_like_internal_key(subcategory_label(raw))


def test_known_keys_map_to_display_names_and_human_text_passes_through():
    assert category_label("pull_ups") == "Подтягивания" == category_label("Подтягивания")
    assert category_label("user") == "Мои упражнения"
    assert category_label("Кардио") == "Кардио"
    assert subcategory_label("block_a") is None and subcategory_label("Вертикальная тяга") == "Вертикальная тяга"
