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
    next_target,
    percentile_rank,
    size_bucket,
)

D = Decimal
Q = (D(8), D(10), D(12), D(15))


def _stats(level: CohortLevel, size: int, below: int = 5, equal: int = 1) -> CohortStats:
    return CohortStats(level=level, size=size, median=D("10.5"), quantiles=Q, below=below, equal=equal)


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
    assert enough.status is PeerStatus.OK and enough.percentile == 28 and enough.median == D("10.5")
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
