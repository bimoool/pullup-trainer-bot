"""Peer Insights, чистая логика (#276, #284): процентиль, пороги когорты, следующая цель, подписи,
границы дат рождения (эквивалентны `leaderboard.age_bucket`), комплементарное подавление узких
когорт (`shown_cohorts`)."""

import itertools
import random
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.domain.leaderboard import AGE_BUCKETS, age_bucket
from app.domain.peer_insights import (
    ALL_COHORT,
    MIN_COHORT_SIZE,
    CohortKey,
    CohortLevel,
    CohortStats,
    PeerStatus,
    birth_date_range,
    build_insight,
    cell_cohort,
    cohort_label,
    gender_cohort,
    next_target,
    percentile_band,
    percentile_rank,
    round_for_display,
    shown_cohorts,
    size_bucket,
)

D = Decimal
Q = (D(8), D(10), D(12), D(15))


ALL = ALL_COHORT
M, F = gender_cohort("male"), gender_cohort("female")


def _stats(key: CohortKey, size: int, below: int = 5, equal: int = 1) -> CohortStats:
    return CohortStats(key=key, size=size, median=D("10.5"), quantiles=Q, below=below, equal=equal)


def _cohorts(*items: tuple[CohortKey, int], **kw) -> dict[CohortKey, CohortStats]:
    return {key: _stats(key, size, **kw) for key, size in items}


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
    below = build_insight(D(9), _cohorts((ALL, MIN_COHORT_SIZE - 1)), None, None)
    assert below.status is PeerStatus.INSUFFICIENT
    assert (below.percentile, below.median, below.label, below.size_bucket, below.next_target) == (None,) * 5
    enough = build_insight(D(9), _cohorts((ALL, MIN_COHORT_SIZE)), None, None)
    assert enough.status is PeerStatus.OK and enough.percentile == 20 and enough.median == D("10.5")
    assert (enough.label, enough.size_bucket, enough.next_target.percentile) == ("Все пользователи", "20–49", 50)


def test_no_cohorts_at_all_is_insufficient_and_no_result_wins():
    assert build_insight(D(9), {}, "male", "30_39").status is PeerStatus.INSUFFICIENT
    assert build_insight(None, _cohorts((ALL, 500)), "male", "30_39").status is PeerStatus.NO_RESULT


def test_cascade_takes_narrowest_shown_cohort_on_the_users_path():
    c = cell_cohort("male", "30_39")
    # ступень 19 → не показывается; пол 30 (остаток от ступени не рассматривается — её нет)
    assert build_insight(D(9), _cohorts((c, 19), (M, 30), (ALL, 300)), "male", "30_39").label == "Мужчины"
    # ступень 20 из пола 45: остаток 25 — всё показывается, берётся ступень
    assert build_insight(D(9), _cohorts((c, 20), (M, 45), (ALL, 300)), "male", "30_39").label == "Мужчины 30–39 лет"
    # пол мал → «все»
    assert build_insight(D(9), _cohorts((c, 19), (M, 19), (ALL, 300)), "male", "30_39").label == "Все пользователи"
    # без пола — только «все», даже при дате рождения
    assert build_insight(D(9), _cohorts((c, 25), (M, 25), (ALL, 300)), None, "30_39").label == "Все пользователи"
    # пол без ступени — пол
    assert build_insight(D(9), _cohorts((c, 25), (M, 45), (ALL, 300)), "male", None).label == "Мужчины"


# --- комплементарное подавление узких когорт (#284) ----------------------------------------------


def _cells(counts: dict[tuple[str, str], int], extra_gender: dict[str, int] | None = None,
           no_gender: int = 0) -> dict[CohortKey, int]:
    """Размеры кандидатов из счётчиков ячеек (пол, ступень); extra_gender — пользователи пола без
    ступени, no_gender — без пола (в ALL невыбираемый остаток)."""
    sizes: dict[CohortKey, int] = Counter()
    for (gender, bucket), n in counts.items():
        sizes[cell_cohort(gender, bucket)] += n
        sizes[gender_cohort(gender)] += n
        sizes[ALL] += n
    for gender, n in (extra_gender or {}).items():
        sizes[gender_cohort(gender)] += n
        sizes[ALL] += n
    sizes[ALL] += no_gender
    return dict(sizes)


def test_review_scenario_male_only_protocol_all_equals_gender_difference_is_closed():
    """35 мужчин: 25 в 18–29 и 10 в 30–39, женщин нет. Раньше «все» (parts [35, 0]) показывалось,
    а «мужчины» — нет; смена даты рождения на 18–29 вскрывала 9 «чужих». Теперь «мужчины» ≡ «все»
    (остаток 0) показываются, а ступень 18–29 (остаток 10) скрыта — разности, раскрывающей 10, нет."""
    sizes = _cells({("male", "18_29"): 25, ("male", "30_39"): 10})
    assert sizes[M] == sizes[ALL] == 35
    assert shown_cohorts(sizes) == {ALL, M}
    cohorts = _cohorts(*sizes.items())
    for bucket in ("18_29", "30_39"):
        insight = build_insight(D(9), cohorts, "male", bucket)
        assert insight.status is PeerStatus.OK and insight.level is CohortLevel.GENDER and insight.size_bucket == "20–49"
    assert build_insight(D(9), cohorts, None, None).level is CohortLevel.ALL  # те же цифры, что у «мужчин»


def test_review_scenario_minority_does_not_suppress_the_wide_levels():
    """200 мужчин + 8 женщин: раньше «все» скрывалось для всех. Теперь скрывается узкий «мужчины»
    (остаток от «все» = 8) и ступени мужчин, что тоже раскрыли бы остаток; «все» остаётся для женщин
    и пользователей без пола/даты рождения."""
    sizes = _cells({("male", "18_29"): 100, ("male", "30_39"): 100, ("female", "18_29"): 8})
    shown = shown_cohorts(sizes)
    assert ALL in shown and M not in shown and F not in shown
    assert shown == {ALL, cell_cohort("male", "30_39")}  # при равенстве скрывается ступень по имени (детерминизм)
    cohorts = _cohorts(*sizes.items())
    for gender, bucket in (("female", "18_29"), (None, None), (None, "30_39"), ("female", None)):
        insight = build_insight(D(9), cohorts, gender, bucket)
        assert insight.status is PeerStatus.OK and insight.level is CohortLevel.ALL, (gender, bucket)


def test_hides_smallest_shown_child_when_residual_is_small():
    # ALL 70 = M 30 + F 25 + 15 без пола: остаток 15 → скрыт самый маленький показываемый (F)
    sizes = _cells({("male", "18_29"): 30, ("female", "18_29"): 25}, no_gender=15)
    shown = shown_cohorts(sizes)
    assert F not in shown and cell_cohort("female", "18_29") not in shown
    # после скрытия F остаток ALL = 25 + 15 = 40 ≥ 20, M (30 = своя ступень) остаётся
    assert M in shown and ALL in shown


def test_residual_zero_or_at_least_twenty_keeps_everything():
    sizes = _cells({("male", "18_29"): 20, ("male", "30_39"): 20, ("female", "18_29"): 20, ("female", "30_39"): 20})
    assert shown_cohorts(sizes) == set(sizes)  # остатки 0; ступени = сумме пола
    sizes = _cells({("male", "18_29"): 25}, extra_gender={"male": 20})  # остаток пола 20
    assert shown_cohorts(sizes) == set(sizes)


def test_identical_size_parent_and_child_are_both_shown():
    sizes = _cells({("female", "40_49"): 22})
    assert shown_cohorts(sizes) == {ALL, F, cell_cohort("female", "40_49")}


def test_three_level_cascade_hiding_a_gender_promotes_cells_which_must_hide_too():
    """25 мужчин в одной ступени + 7 без пола: ALL 32, M 25 ≡ ступень 25. Остаток ALL = 7 → скрыть M;
    теперь ближайший показываемый потомок ALL — ступень (25), остаток всё те же 7 → скрыть и её.
    Иначе пара «ALL − ступень» = 7 раскрыла бы 7 человек (а правило «только прямые дети» это
    пропускало)."""
    sizes = _cells({("male", "18_29"): 25}, no_gender=7)
    assert sizes[ALL] == 32
    assert shown_cohorts(sizes) == {ALL}


def test_gender_cells_residual_hides_smallest_cell_then_rechecks_the_top():
    # мужчины: 30 + 22 в ступенях, 10 без ступени (M=62, остаток 10 → скрыть ступень 22 → остаток 32);
    # женщины 5 → ALL 67: остаток от M = 5 → скрыть M; ступень 30 всплывает, остаток ALL = 37 — ок
    sizes = _cells({("male", "18_29"): 30, ("male", "30_39"): 22, ("female", "18_29"): 5}, extra_gender={"male": 10})
    assert sizes[M] == 62 and sizes[ALL] == 67
    assert shown_cohorts(sizes) == {ALL, cell_cohort("male", "18_29")}
    # без женщин: M ≡ ALL (62), ступень 30 (остаток 32) показывается, ступень 22 скрыта лишь
    # из-за остатка 62 − 30 − 22 = 10
    sizes = _cells({("male", "18_29"): 30, ("male", "30_39"): 22}, extra_gender={"male": 10})
    assert shown_cohorts(sizes) == {ALL, M, cell_cohort("male", "18_29")}


def _antichains(shown: frozenset[CohortKey], parent: CohortKey, rng: random.Random):
    """Случайное непересекающееся подмножество показываемых строгих потомков `parent`."""
    from app.domain.peer_insights import _is_descendant

    below = [k for k in shown if _is_descendant(k, parent)]
    rng.shuffle(below)
    chosen: list[CohortKey] = []
    for key in below:
        if rng.random() < 0.6 and not any(_is_descendant(key, c) or _is_descendant(c, key) for c in chosen):
            chosen.append(key)
    return chosen


def _random_sizes(rng: random.Random) -> dict[CohortKey, int]:
    counts: dict[tuple[str, str], int] = {}
    pick = rng.choice
    scale = pick([5, 12, 25, 40, 80])
    for gender in ("male", "female"):
        for bucket in AGE_BUCKETS:
            if rng.random() < 0.5:
                counts[(gender, bucket)] = rng.randint(1, scale)
    extra = {g: rng.randint(0, scale) if rng.random() < 0.5 else 0 for g in ("male", "female")}
    return _cells(counts, extra, no_gender=rng.randint(0, scale) if rng.random() < 0.5 else 0)


def test_property_no_shown_pair_or_sum_of_shown_descendants_leaves_a_small_remainder():
    from app.domain.peer_insights import _is_descendant

    rng = random.Random(284)
    nontrivial = 0
    for _ in range(3000):
        sizes = _random_sizes(rng)
        shown = shown_cohorts(sizes)
        # только достаточно большие
        assert all(sizes[k] >= MIN_COHORT_SIZE for k in shown)
        # не прячем лишнего без причины хотя бы в тривиальных случаях: ALL≥20 и один пол
        for parent in shown:
            for child in shown:
                if _is_descendant(child, parent):
                    diff = sizes[parent] - sizes[child]
                    assert diff == 0 or diff >= MIN_COHORT_SIZE, (sizes, parent, child)
            # любая сумма непересекающихся показываемых потомков: остаток не в 1..19
            for _ in range(8):
                chosen = _antichains(shown, parent, rng)
                residual = sizes[parent] - sum(sizes[k] for k in chosen)
                assert residual == 0 or residual >= MIN_COHORT_SIZE, (sizes, parent, chosen)
        if len(shown) < sum(1 for n in sizes.values() if n >= MIN_COHORT_SIZE):
            nontrivial += 1
    assert nontrivial > 200  # генератор действительно упирается в подавление, тест не пустой


def test_property_shown_set_does_not_depend_on_dict_order_and_is_idempotent():
    rng = random.Random(7)
    for _ in range(300):
        sizes = _random_sizes(rng)
        items = list(sizes.items())
        rng.shuffle(items)
        shown = shown_cohorts(sizes)
        assert shown_cohorts(dict(items)) == shown
        # повторное применение к размерам только показываемых ничего не добавляет
        assert shown_cohorts({k: sizes[k] for k in shown}) <= shown


def test_property_brute_force_every_pair_of_shown_cohorts_over_exhaustive_small_trees():
    """Исчерпывающе на малой сетке: две ступени × два пола + остатки 0/6/22, все комбинации."""
    from app.domain.peer_insights import _is_descendant

    grid = (0, 6, 22)
    for a, b, c, d, xm, xf, ng in itertools.product(grid, grid, grid, grid, grid, grid, grid):
        counts = {k: n for k, n in {("male", "18_29"): a, ("male", "30_39"): b,
                                     ("female", "18_29"): c, ("female", "30_39"): d}.items() if n}
        sizes = _cells(counts, {"male": xm, "female": xf}, no_gender=ng)
        shown = shown_cohorts(sizes)
        for parent, child in itertools.permutations(shown, 2):
            if _is_descendant(child, parent):
                diff = sizes[parent] - sizes[child]
                assert diff == 0 or diff >= MIN_COHORT_SIZE, (sizes, parent, child)


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
    insight = build_insight(D(9), _cohorts((ALL, 20), below=14), None, None)
    assert percentile_rank(14, 1, 20) == 73 and insight.percentile == 70
    # соседние точные значения (73, 74, 78) неразличимы — разворот «below» по 1 % невозможен
    seen = {build_insight(D(9), _cohorts((ALL, 100), below=b, equal=1), None, None).percentile for b in range(70, 79)}
    assert seen == {70}


def test_round_for_display_matches_protocol_precision():
    assert round_for_display(D("10.5"), True) == D(11) and round_for_display(D("10.4"), True) == D(10)
    assert round_for_display(D("10.25"), False) == D("10.3") and round_for_display(D("12.34"), False) == D("12.3")
    assert round_for_display(D("15.01"), True, up=True) == D(16)
    assert round_for_display(D("12.31"), False, up=True) == D("12.4")


def test_median_and_next_target_are_rounded_in_the_insight():
    stats = CohortStats(
        key=ALL, size=30, median=D("10.5"), quantiles=(D("8.25"), D("10.5"), D("12.25"), D("15.75")),
        below=5, equal=1,
    )
    reps = build_insight(D(12), {ALL: stats}, None, None, integer_only=True)
    assert reps.median == D(11) and (reps.next_target.percentile, reps.next_target.value) == (75, D(13))
    weight = build_insight(D("12.2"), {ALL: stats}, None, None)
    assert weight.median == D("10.5") and weight.next_target.value == D("12.3")  # строго выше 12.2


def test_next_target_stays_strictly_above_own_value_after_rounding():
    for own in (D("12"), D("12.2"), D("12.24")):
        target = next_target(own, (D(1), D(2), D("12.25"), D(99)), integer_only=False)
        assert target.value > own
    assert next_target(D(15), (D(8), D(10), D(12), D("15.01")), integer_only=True).value == D(16)
