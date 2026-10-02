"""Peer Insights для тестов (CRIMPD #276): как последний результат пользователя соотносится с
«похожими» — когортой по полу и возрастной ступени. Чистая логика без БД и без «сегодня»
внутри: агрегаты считает репозиторий одним SQL, здесь — выбор когорты, процентиль, медиана,
следующая цель, подписи и границы дат рождения для SQL-фильтра.

Кандидаты-когорты: ALL; G(пол) для каждого пола; C(пол, возрастная ступень)
(`app.domain.leaderboard.age_bucket`, 6 ступеней). Пользователь без пола, без даты рождения или
младше 18 — «невыбираемый остаток» своего родителя (в ALL / в G), отдельной когортой не является.
Когорта показывается только при размере >= MIN_COHORT_SIZE (20). Когорта пользователя — самая
узкая ПОКАЗЫВАЕМАЯ на его пути C → G → ALL; ни одной — статус «insufficient», никаких синтетических
чисел. Сам пользователь входит в когорту. Результат — только агрегаты; чужие id и значения сюда не
попадают.

Защита от реконструкции чужих значений (ревью #283, #284): пользователь сам задаёт своё значение и
свою когорту (пол/дата рождения), поэтому
  * процентиль отдаётся только 10-пунктовой полосой (`percentile_band`, floor) — не точное «below»;
  * медиана и пороги округляются до точности отображения протокола (`round_for_display`);
  * ДОПОЛНИТЕЛЬНОЕ ПОДАВЛЕНИЕ УЗКИХ КОГОРТ (`shown_cohorts`): набор показываемых когорт — функция
    только данных, не зрителя. Для каждой показываемой когорты P берутся её ближайшие показываемые
    потомки (непересекающиеся); остаток = |P| − Σ|потомков|. Если остаток 1..19 — разность двух
    ответов раскрыла бы агрегаты малой группы, и подавляется САМЫЙ МАЛЕНЬКИЙ из этих потомков;
    повторяется до неподвижной точки. Широкие уровни (ALL, пол) не страдают из-за малого меньшинства:
    прячутся более узкие. Инвариант: для показываемых P ⊃ C разность |P| − |C| равна 0 или >= 20
    (и то же для любой суммы непересекающихся показываемых потомков);
  * частоту запросов ограничивает `app.web.rate_limit` (в роуте)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
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
class CohortKey:
    """Идентификатор когорты-кандидата: ALL (gender=None, bucket=None), G(пол) (bucket=None),
    C(пол, ступень)."""

    level: CohortLevel
    gender: str | None = None
    bucket: str | None = None


ALL_COHORT = CohortKey(CohortLevel.ALL)


def gender_cohort(gender: str) -> CohortKey:
    return CohortKey(CohortLevel.GENDER, gender)


def cell_cohort(gender: str, bucket: str) -> CohortKey:
    return CohortKey(CohortLevel.GENDER_AGE, gender, bucket)


@dataclass(frozen=True)
class CohortStats:
    """Агрегаты одной когорты относительно значения пользователя. `quantiles` — значения на
    NEXT_TARGET_PERCENTILES (percentile_cont), в том же порядке."""

    key: CohortKey
    size: int
    median: Decimal
    quantiles: tuple[Decimal, ...]
    below: int  # результатов строго ниже значения пользователя
    equal: int  # результатов, равных значению пользователя (включая его самого)

    @property
    def level(self) -> CohortLevel:
        return self.key.level


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
    percentile: int | None = None  # 10-пунктовая полоса (floor), не точный процентиль
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


PERCENTILE_BAND = 10


def percentile_band(percentile: int) -> int:
    """Грубая полоса процентиля: floor до 10 пунктов (0, 10, …, 90). Честно: реальный процентиль
    лежит в [band, band + 10); точное значение наружу не отдаётся (иначе по нему восстанавливается
    число результатов ниже заданного — см. docstring модуля)."""
    return max(0, min(100 - PERCENTILE_BAND, percentile // PERCENTILE_BAND * PERCENTILE_BAND))


def round_for_display(value: Decimal, integer_only: bool, *, up: bool = False) -> Decimal:
    """Округление агрегата до точности отображения протокола: повторения — целые, остальные
    метрики — один знак. `up=True` — вверх (для «следующего ориентира»: он остаётся строго выше
    результата пользователя)."""
    step = Decimal(1) if integer_only else Decimal("0.1")
    return value.quantize(step, rounding=ROUND_CEILING if up else ROUND_HALF_UP)


def _parent(key: CohortKey) -> CohortKey | None:
    if key.level is CohortLevel.GENDER_AGE:
        return gender_cohort(key.gender or "")
    if key.level is CohortLevel.GENDER:
        return ALL_COHORT
    return None


def _is_descendant(key: CohortKey, ancestor: CohortKey) -> bool:
    parent = _parent(key)
    while parent is not None:
        if parent == ancestor:
            return True
        parent = _parent(parent)
    return False


def _hide_order(key: CohortKey, size: int) -> tuple[int, int, str, str]:
    # самый маленький; при равенстве — более узкий уровень, затем по имени (детерминизм)
    depth = {CohortLevel.GENDER_AGE: 0, CohortLevel.GENDER: 1, CohortLevel.ALL: 2}[key.level]
    return size, depth, key.gender or "", key.bucket or ""


def shown_cohorts(sizes: Mapping[CohortKey, int]) -> frozenset[CohortKey]:
    """Набор показываемых когорт (комплементарное подавление узких, см. docstring модуля).
    `sizes` — размеры кандидатов ALL / G(пол) / C(пол, ступень); отсутствующий ключ = 0.

    Алгоритм: shown = {размер >= MIN_COHORT_SIZE}; для каждой показываемой P (сначала пол, затем
    ALL) пока остаток |P| − Σ|ближайшие показываемые потомки| в 1..MIN_COHORT_SIZE-1 — скрыть самого
    маленького из этих потомков (его показываемые потомки «всплывают» и становятся ближайшими, так
    что цепочка ALL → пол → ступень добирается до нужной глубины); внешний цикл повторяет проход до
    неподвижной точки.

    Инвариант результата (для P ⊃ C, обе показываются): |P| − |C| = 0 или >= MIN_COHORT_SIZE.
    Эскиз доказательства: пусть D — ближайший к P показываемый потомок, содержащий C (D = C или
    D ⊋ C). |P| − |D| = остаток(P) + Σ остальных ближайших потомков — это 0 или >= 20 (остаток по
    условию остановки 0 или >= 20, каждый потомок >= 20); |D| − |C| — то же по индукции по глубине
    (дерево трёхуровневое); сумма двух чисел из {0} ∪ [20, ∞) снова из {0} ∪ [20, ∞).
    Скрытие потомка только увеличивает остаток предков (на его собственный остаток, 0 или >= 20),
    поэтому уже устойчивые узлы не ломаются, а число показываемых только убывает — цикл конечен."""
    shown = {key for key, size in sizes.items() if size >= MIN_COHORT_SIZE}
    parents = sorted(
        (key for key in shown if key.level is not CohortLevel.GENDER_AGE),
        key=lambda key: (key.level is CohortLevel.ALL, key.gender or ""),
    )

    def nearest(parent: CohortKey) -> list[CohortKey]:
        below = [key for key in shown if _is_descendant(key, parent)]
        return [key for key in below if not any(_is_descendant(key, other) for other in below)]

    changed = True
    while changed:
        changed = False
        for parent in parents:
            if parent not in shown:
                continue
            while True:
                children = nearest(parent)
                residual = sizes[parent] - sum(sizes[key] for key in children)
                if not 0 < residual < MIN_COHORT_SIZE:
                    break
                shown.discard(min(children, key=lambda key: _hide_order(key, sizes[key])))
                changed = True
    return frozenset(shown)


def next_target(value: Decimal, quantiles: tuple[Decimal, ...], integer_only: bool = False) -> NextTarget | None:
    """Ближайший порог из NEXT_TARGET_PERCENTILES, строго выше значения пользователя (сравнение
    до округления), затем округлённый вверх до точности протокола — так он остаётся выше
    результата; None — пользователь уже выше всех порогов."""
    for percentile, threshold in zip(NEXT_TARGET_PERCENTILES, quantiles, strict=True):
        if threshold > value:
            return NextTarget(percentile=percentile, value=round_for_display(threshold, integer_only, up=True))
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
    own_value: Decimal | None, cohorts: Mapping[CohortKey, CohortStats], gender: str | None, bucket: str | None,
    integer_only: bool = False,
) -> PeerInsight:
    """`cohorts` — агрегаты кандидатов (достаточно тех, что >= MIN_COHORT_SIZE; меньшие и так не
    показываются). Показываемый набор — `shown_cohorts` по размерам; когорта пользователя — самая
    узкая показываемая на его пути C(пол, ступень) → G(пол) → ALL."""
    if own_value is None:
        return PeerInsight(status=PeerStatus.NO_RESULT)
    shown = shown_cohorts({key: stats.size for key, stats in cohorts.items()})
    path: list[CohortKey] = []
    if gender is not None and bucket is not None:
        path.append(cell_cohort(gender, bucket))
    if gender is not None:
        path.append(gender_cohort(gender))
    path.append(ALL_COHORT)
    for key in path:
        if key in shown:
            stats = cohorts[key]
            return PeerInsight(
                status=PeerStatus.OK,
                own_value=own_value,
                level=key.level,
                label=cohort_label(key.level, gender, bucket),
                size_bucket=size_bucket(stats.size),
                percentile=percentile_band(percentile_rank(stats.below, stats.equal, stats.size)),
                median=round_for_display(stats.median, integer_only),
                next_target=next_target(own_value, stats.quantiles, integer_only),
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
