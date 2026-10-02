"""Peer Insights для тестов (CRIMPD #276): как последний результат пользователя соотносится с
«похожими» — когортой по полу и возрастной ступени. Чистая логика без БД и без «сегодня»
внутри: агрегаты считает репозиторий одним SQL, здесь — выбор когорты, процентиль, медиана,
следующая цель, подписи и границы дат рождения для SQL-фильтра.

Когорта выбирается каскадом (первая достаточно большая):
  1. тот же пол + та же возрастная ступень (`app.domain.leaderboard.age_bucket`, 6 ступеней);
  2. тот же пол;
  3. все пользователи.
Нет пола — уровни 1–2 пропускаются; нет даты рождения или младше 18 — пропускается уровень 1.
Когорта меньше MIN_COHORT_SIZE (20) не показывается вообще: никаких синтетических чисел —
статус «insufficient». Сам пользователь входит в когорту (его последний результат — одна из строк).
Результат — только агрегаты; чужие id и значения сюда не попадают."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.domain.leaderboard import AGE_BUCKETS

MIN_COHORT_SIZE = 20

# Ступени «следующего диапазона»: процентили, по которым считается пороговое значение.
NEXT_TARGET_PERCENTILES: tuple[int, ...] = (25, 50, 75, 90)


class CohortLevel(StrEnum):
    GENDER_AGE = "gender_age"
    GENDER = "gender"
    ALL = "all"


class PeerStatus(StrEnum):
    OK = "ok"
    INSUFFICIENT = "insufficient"  # ни одна когорта не набрала MIN_COHORT_SIZE
    NO_RESULT = "no_result"  # у пользователя нет результата по этому тесту


@dataclass(frozen=True)
class CohortStats:
    """Агрегаты одной когорты относительно значения пользователя. `quantiles` — значения на
    NEXT_TARGET_PERCENTILES (percentile_cont), в том же порядке."""

    level: CohortLevel
    size: int
    median: Decimal
    quantiles: tuple[Decimal, ...]
    below: int  # результатов строго ниже значения пользователя
    equal: int  # результатов, равных значению пользователя (включая его самого)


@dataclass(frozen=True)
class NextTarget:
    percentile: int
    value: Decimal


@dataclass(frozen=True)
class PeerInsight:
    status: PeerStatus
    own_value: Decimal | None = None
    level: CohortLevel | None = None
    label: str | None = None
    size_bucket: str | None = None
    percentile: int | None = None
    median: Decimal | None = None
    next_target: NextTarget | None = None


def percentile_rank(below: int, equal: int, size: int) -> int:
    """Процентиль по середине ранга: доля строго худших + половина равных, в целых процентах,
    зажато в 1..99 (честно не бывает «0-го» и «100-го» процентиля среди себя и других)."""
    if size <= 0:
        raise ValueError("size must be positive")
    # целочисленно: floor((below + equal/2) / size * 100 + 0.5) — половина вверх, без float-шума
    rounded = ((2 * below + equal) * 100 + size) // (2 * size)
    return max(1, min(99, rounded))


def next_target(value: Decimal, quantiles: tuple[Decimal, ...]) -> NextTarget | None:
    """Ближайший порог из NEXT_TARGET_PERCENTILES, строго выше значения пользователя; None —
    пользователь уже выше всех порогов (или порог совпал бы с текущим значением)."""
    for percentile, threshold in zip(NEXT_TARGET_PERCENTILES, quantiles, strict=True):
        if threshold > value:
            return NextTarget(percentile=percentile, value=threshold)
    return None


def size_bucket(size: int) -> str:
    """Грубый размер когорты вместо точного числа: «20–49» / «50–99» / «100+»."""
    if size < 50:
        return "20–49"
    if size < 100:
        return "50–99"
    return "100+"


_GENDER_LABELS = {"male": "Мужчины", "female": "Женщины"}


def _age_range_label(bucket: str) -> str:
    return "70+ лет" if bucket == "70_plus" else f"{bucket.replace('_', '–')} лет"


def cohort_label(level: CohortLevel, gender: str | None, bucket: str | None) -> str:
    if level is CohortLevel.GENDER_AGE and gender in _GENDER_LABELS and bucket in AGE_BUCKETS:
        return f"{_GENDER_LABELS[gender]} {_age_range_label(bucket)}"
    if level is CohortLevel.GENDER and gender in _GENDER_LABELS:
        return _GENDER_LABELS[gender]
    return "Все пользователи"


def build_insight(
    own_value: Decimal | None, cohorts: list[CohortStats], gender: str | None, bucket: str | None,
) -> PeerInsight:
    """`cohorts` — кандидаты от самой узкой к самой широкой; берётся первая с size >= MIN_COHORT_SIZE."""
    if own_value is None:
        return PeerInsight(status=PeerStatus.NO_RESULT)
    for stats in cohorts:
        if stats.size >= MIN_COHORT_SIZE:
            return PeerInsight(
                status=PeerStatus.OK,
                own_value=own_value,
                level=stats.level,
                label=cohort_label(stats.level, gender, bucket),
                size_bucket=size_bucket(stats.size),
                percentile=percentile_rank(stats.below, stats.equal, stats.size),
                median=stats.median,
                next_target=next_target(own_value, stats.quantiles),
            )
    return PeerInsight(status=PeerStatus.INSUFFICIENT, own_value=own_value)


# --- границы дат рождения для SQL (вместо дублирующего CASE по age()) --------------------------

_BUCKET_AGES: dict[str, tuple[int, int | None]] = {
    "18_29": (18, 29), "30_39": (30, 39), "40_49": (40, 49),
    "50_59": (50, 59), "60_69": (60, 69), "70_plus": (70, None),
}


def _years_ago(today: date, years: int) -> date:
    """Крайняя дата рождения человека, которому сегодня исполнилось ровно `years` (29 февраля в
    невисокосный год — 28 февраля; такой человек «стареет» 1 марта, как в `leaderboard.age_bucket`)."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return date(today.year - years, 2, 28)


def birth_date_range(bucket: str, today: date) -> tuple[date | None, date]:
    """(after, upto): пользователь в ступени `bucket` на `today` ⇔ after < birth_date <= upto
    (after=None — без нижней границы, ступень 70+). Эквивалентно `leaderboard.age_bucket`."""
    low, high = _BUCKET_AGES[bucket]
    upto = _years_ago(today, low)
    after = None if high is None else _years_ago(today, high + 1)
    return after, upto
