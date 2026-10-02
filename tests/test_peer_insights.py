"""Peer Insights, чистая логика (#276): процентиль, пороги когорты, следующая цель, подписи,
границы дат рождения (эквивалентны `leaderboard.age_bucket`)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.domain.leaderboard import AGE_BUCKETS, age_bucket
from app.domain.peer_insights import (
    MIN_COHORT_SIZE,
    CohortLevel,
    CohortStats,
    PeerStatus,
    birth_date_range,
    build_insight,
    cohort_label,
    is_differencing_safe,
    next_target,
    percentile_band,
    percentile_rank,
    round_for_display,
    size_bucket,
)

D = Decimal
Q = (D(8), D(10), D(12), D(15))


def _stats(level: CohortLevel, size: int, below: int = 5, equal: int = 1, parts: tuple[int, ...] = ()) -> CohortStats:
    return CohortStats(level=level, size=size, median=D("10.5"), quantiles=Q, below=below, equal=equal, parts=parts)


@pytest.mark.parametrize(
    ("below", "equal", "size", "expected"),
    [
        (14, 1, 20, 73),  # (14 + 0.5) / 20 = 72.5 → вверх
        (0, 1, 20, 3),  # 2.5 → 3
        (10, 4, 20, 60),  # ничьи считаются наполовину
        (0, 1, 1000, 1),  # зажато снизу: «0-го» не бывает
        (999, 1, 1000, 99),  # и сверху: «100-го» не бывает
        (19, 1, 20, 98),
    ],
)
def test_percentile_rank(below, equal, size, expected):
    assert percentile_rank(below, equal, size) == expected


def test_percentile_rank_rejects_empty_cohort():
    with pytest.raises(ValueError):
        percentile_rank(0, 0, 0)


def test_next_target_is_first_threshold_strictly_above_value():
    assert next_target(D(7), Q).percentile == 25 and next_target(D(7), Q).value == D(8)
    assert next_target(D(8), Q).percentile == 50  # равное порогу — уже достигнут
    assert next_target(D(12), Q).percentile == 90
    assert next_target(D(15), Q) is None  # выше всех порогов — следующего диапазона нет
    assert next_target(D(20), Q) is None


def test_size_bucket_is_coarse():
    assert [size_bucket(n) for n in (20, 49, 50, 99, 100, 5000)] == ["20–49", "20–49", "50–99", "50–99", "100+", "100+"]


def test_cohort_labels():
    assert cohort_label(CohortLevel.GENDER_AGE, "male", "30_39") == "Мужчины 30–39 лет"
    assert cohort_label(CohortLevel.GENDER_AGE, "female", "70_plus") == "Женщины 70+ лет"
    assert cohort_label(CohortLevel.GENDER, "female", "18_29") == "Женщины"
    assert cohort_label(CohortLevel.ALL, "male", "30_39") == "Все пользователи"


def test_threshold_19_is_insufficient_and_20_is_enough():
    below = build_insight(D(9), [_stats(CohortLevel.ALL, MIN_COHORT_SIZE - 1)], None, None)
    assert below.status is PeerStatus.INSUFFICIENT
    assert (below.percentile, below.median, below.label, below.size_bucket, below.next_target) == (None,) * 5
    enough = build_insight(D(9), [_stats(CohortLevel.ALL, MIN_COHORT_SIZE)], None, None)
    assert enough.status is PeerStatus.OK and enough.percentile == 20 and enough.median == D("10.5")
    assert (enough.label, enough.size_bucket, enough.next_target.percentile) == ("Все пользователи", "20–49", 50)


def test_no_cohorts_at_all_is_insufficient_and_no_result_wins():
    assert build_insight(D(9), [], "male", "30_39").status is PeerStatus.INSUFFICIENT
    assert build_insight(None, [_stats(CohortLevel.ALL, 500)], "male", "30_39").status is PeerStatus.NO_RESULT


def test_cascade_takes_first_big_enough_cohort_narrowest_first():
    cohorts = [
        _stats(CohortLevel.GENDER_AGE, 19), _stats(CohortLevel.GENDER, 30), _stats(CohortLevel.ALL, 300),
    ]
    assert build_insight(D(9), cohorts, "male", "30_39").label == "Мужчины"
    cohorts[0] = _stats(CohortLevel.GENDER_AGE, 20)
    assert build_insight(D(9), cohorts, "male", "30_39").label == "Мужчины 30–39 лет"
    cohorts[1] = _stats(CohortLevel.GENDER, 19)
    cohorts[0] = _stats(CohortLevel.GENDER_AGE, 19)
    assert build_insight(D(9), cohorts, "male", "30_39").label == "Все пользователи"


def test_birth_date_range_matches_age_bucket_everywhere():
    """Для каждого «сегодня» (в т.ч. около 29 февраля) диапазон дат рождения даёт ту же ступень,
    что и `leaderboard.age_bucket` — SQL-фильтр не расходится с доменом."""
    todays = [date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1), date(2025, 2, 28), date(2025, 3, 1), date(2026, 10, 2)]
    for today in todays:
        for offset in range(0, 366 * 80, 7):
            born = today - timedelta(days=offset)
            expected = age_bucket(born, today)
            matched = []
            for bucket in AGE_BUCKETS:
                after, upto = birth_date_range(bucket, today)
                if born <= upto and (after is None or born > after):
                    matched.append(bucket)
            assert matched == ([] if expected is None else [expected]), (today, born)
        # граничные дни рождения: ровно N лет сегодня и за день до
        for bucket in AGE_BUCKETS:
            after, upto = birth_date_range(bucket, today)
            assert age_bucket(upto, today) == bucket
            assert age_bucket(upto + timedelta(days=1), today) != bucket
            if after is not None:
                assert age_bucket(after + timedelta(days=1), today) == bucket
                assert age_bucket(after, today) != bucket


@pytest.mark.parametrize(
    ("percentile", "band"),
    [(1, 0), (9, 0), (10, 10), (19, 10), (28, 20), (73, 70), (89, 80), (90, 90), (99, 90)],
)
def test_percentile_band_floors_to_ten_point_bands(percentile, band):
    assert percentile_band(percentile) == band


def test_insight_exposes_only_the_band_never_the_exact_percentile():
    # below=14 equal=1 size=20 → точный процентиль 73; наружу — только полоса 70
    insight = build_insight(D(9), [_stats(CohortLevel.ALL, 20, below=14)], None, None)
    assert percentile_rank(14, 1, 20) == 73 and insight.percentile == 70
    # соседние точные значения (73, 74, 78) неразличимы — разворот «below» по 1 % невозможен
    seen = {build_insight(D(9), [_stats(CohortLevel.ALL, 100, below=b, equal=1)], None, None).percentile for b in range(70, 79)}
    assert seen == {70}


def test_round_for_display_matches_protocol_precision():
    assert round_for_display(D("10.5"), True) == D(11) and round_for_display(D("10.4"), True) == D(10)
    assert round_for_display(D("10.25"), False) == D("10.3") and round_for_display(D("12.34"), False) == D("12.3")
    assert round_for_display(D("15.01"), True, up=True) == D(16)
    assert round_for_display(D("12.31"), False, up=True) == D("12.4")


def test_median_and_next_target_are_rounded_in_the_insight():
    stats = CohortStats(
        level=CohortLevel.ALL, size=30, median=D("10.5"), quantiles=(D("8.25"), D("10.5"), D("12.25"), D("15.75")),
        below=5, equal=1,
    )
    reps = build_insight(D(12), [stats], None, None, integer_only=True)
    assert reps.median == D(11) and (reps.next_target.percentile, reps.next_target.value) == (75, D(13))
    weight = build_insight(D("12.2"), [stats], None, None)
    assert weight.median == D("10.5") and weight.next_target.value == D("12.3")  # строго выше 12.2


def test_next_target_stays_strictly_above_own_value_after_rounding():
    for own in (D("12"), D("12.2"), D("12.24")):
        target = next_target(own, (D(1), D(2), D("12.25"), D(99)), integer_only=False)
        assert target.value > own
    assert next_target(D(15), (D(8), D(10), D(12), D("15.01")), integer_only=True).value == D(16)


def test_differencing_guard_rule():
    # подкогорта ≥ 20 с остатком 1..19 — небезопасно
    assert not is_differencing_safe(_stats(CohortLevel.GENDER, 30, parts=(20, 5)))
    assert not is_differencing_safe(_stats(CohortLevel.GENDER, 21, parts=(20,)))  # остаток 1
    assert not is_differencing_safe(_stats(CohortLevel.ALL, 39, parts=(20, 4)))  # остаток 19
    # остаток 0 или ≥ 20 — безопасно; подкогорты < 20 никогда не показываются, их вычитание не страшно
    assert is_differencing_safe(_stats(CohortLevel.GENDER, 20, parts=(20,)))
    assert is_differencing_safe(_stats(CohortLevel.GENDER, 40, parts=(20, 20)))
    assert is_differencing_safe(_stats(CohortLevel.ALL, 30, parts=(19, 5)))
    assert is_differencing_safe(_stats(CohortLevel.GENDER_AGE, 25))  # самый узкий уровень — без подкогорт
    assert is_differencing_safe(_stats(CohortLevel.ALL, 30))


def test_guard_falls_through_to_wider_level_then_to_insufficient():
    risky_gender = _stats(CohortLevel.GENDER, 30, parts=(22,))  # остаток 8
    safe_all = _stats(CohortLevel.ALL, 300, parts=(30, 30))
    assert build_insight(D(9), [risky_gender, safe_all], "male", None).label == "Все пользователи"
    risky_all = _stats(CohortLevel.ALL, 25, parts=(22,))  # остаток 3
    assert build_insight(D(9), [risky_gender, risky_all], "male", None).status is PeerStatus.INSUFFICIENT
    # самый узкий уровень не режется защитой
    narrow = _stats(CohortLevel.GENDER_AGE, 20)
    assert build_insight(D(9), [narrow, risky_gender, safe_all], "male", "30_39").label == "Мужчины 30–39 лет"
