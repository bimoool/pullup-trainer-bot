"""Аналитика TrainingSession v2 (REBUILD-1, R3) — чистый расчёт по уже
загруженным завершённым сессиям. Не знает про SQLAlchemy/HTTP/текущее время
(now передаётся явно).

Принципы:
  * Агрегация — по (exercise_id, protocol_type). Несовместимые протоколы
    одного упражнения (повторения и максимум "Подтягиваний") НЕ суммируются.
  * Идентичность протокола блока приходит снаружи из ЗАМОРОЖЕННОГО снимка;
    блок без протокола (STEP/legacy) даёт вклад только в активность и НЕ
    попадает в протокол-специфичные метрики.
  * Активность — по локальным календарным дням пользователя; сессии из
    будущего исключены; смешанная сессия считается ОДИН раз.
  * Не выдумываем: общий объём между протоколами, стрик, длительность
    сессии, вес/нагрузку, RPE, "план vs факт" для интервалов.
  * Тренировка атомарна (issue #308, SESSION §6 A2): каждая сессия — ровно в одной
    категории, все счётчики тренировок — целые; минуты считаются в секундах и
    раздаются методом наибольшего остатка (A5), чтобы части давали показанный итог."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

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
    subcategory_label,
)

ACTIVITY_WINDOW_DAYS = 30
ACTIVITY_WEEKS = 12
# Верхняя граница точек тренда на панель в ответе (агрегаты считаются по
# ВСЕМ сессиям, ограничена только длина ряда для графика).
MAX_TREND_POINTS = 200


@dataclass(frozen=True)
class AnalyticsSetLog:
    value: Decimal
    unit: str


@dataclass(frozen=True)
class AnalyticsBlock:
    exercise_id: int | None
    exercise_name: str | None
    protocol_type: str | None  # reps_sets | time_sets | max_effort | interval | None
    set_logs: list[AnalyticsSetLog] = field(default_factory=list)
    result: dict | None = None  # interval result
    # Подходы "на максимум" блока рабочих подходов (course Block B: 4×3 + max): отдельная панель
    # max_effort того же упражнения (A4); у блока одного протокола пусто.
    max_set_logs: list[AnalyticsSetLog] = field(default_factory=list)
    # Категория упражнения каталога (#274); None — нет упражнения/legacy
    category: str | None = None
    subcategory: str | None = None


@dataclass(frozen=True)
class AnalyticsSession:
    performed_at: datetime  # aware
    blocks: list[AnalyticsBlock]
    completed_at: datetime | None = None  # aware; NULL у старых сессий
    # Свободная активность (#263): заявленная длительность, источник минут вместо completed_at
    duration_seconds: int | None = None
    activity_type: str | None = None
    # Подпись вида внешней активности («Бег») — подкатегория «Другой активности»; None — неизвестный вид.
    activity_label: str | None = None
    # Каноническая сессия (#308): id строки TrainingSession — для тестов/диагностики сверки.
    session_id: int | None = None


@dataclass(frozen=True)
class WeekBucket:
    week_start: date  # понедельник
    sessions: int
    active_days: int


@dataclass(frozen=True)
class Activity:
    sessions_last_30_days: int
    active_days_last_30_days: int
    weeks: list[WeekBucket]  # от старой недели к текущей, ровно ACTIVITY_WEEKS


@dataclass(frozen=True)
class TrendPoint:
    at: datetime
    value: Decimal
    best: Decimal | None = None
    cumulative_best: Decimal | None = None
    is_new_pb: bool | None = None
    cycles: int | None = None


@dataclass(frozen=True)
class ProtocolPanel:
    exercise_id: int
    exercise_name: str
    protocol_type: str
    session_count: int
    # единица значений точек/рекорда ("reps" | "s"); None у interval
    unit: str | None = None
    # reps
    total_reps: Decimal | None = None
    # time
    total_work_seconds: Decimal | None = None
    # reps/time
    set_count: int | None = None
    best_set: Decimal | None = None
    # max
    attempt_count: int | None = None
    best: Decimal | None = None
    # interval
    actual_duration_seconds: int | None = None
    cycles: int | None = None
    points: list[TrendPoint] = field(default_factory=list)
    points_total: int = 0


@dataclass(frozen=True)
class TrainingAnalytics:
    activity: Activity
    panels: list[ProtocolPanel]


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def compute_activity(sessions: list[AnalyticsSession], now: datetime, tz: ZoneInfo) -> Activity:
    today = now.astimezone(tz).date()
    window_start = today - timedelta(days=ACTIVITY_WINDOW_DAYS - 1)
    current_week = _week_start(today)
    first_week = current_week - timedelta(weeks=ACTIVITY_WEEKS - 1)

    days_in_window: set[date] = set()
    sessions_in_window = 0
    per_week_sessions: dict[date, int] = {}
    per_week_days: dict[date, set[date]] = {}
    for session in sessions:
        local_day = session.performed_at.astimezone(tz).date()
        if window_start <= local_day <= today:
            sessions_in_window += 1
            days_in_window.add(local_day)
        week = _week_start(local_day)
        if first_week <= week <= current_week:
            per_week_sessions[week] = per_week_sessions.get(week, 0) + 1
            per_week_days.setdefault(week, set()).add(local_day)

    weeks = [
        WeekBucket(
            week_start=first_week + timedelta(weeks=i),
            sessions=per_week_sessions.get(first_week + timedelta(weeks=i), 0),
            active_days=len(per_week_days.get(first_week + timedelta(weeks=i), set())),
        )
        for i in range(ACTIVITY_WEEKS)
    ]
    return Activity(
        sessions_last_30_days=sessions_in_window, active_days_last_30_days=len(days_in_window), weeks=weeks,
    )


def _completed_past(sessions: list[AnalyticsSession], now: datetime) -> list[AnalyticsSession]:
    """Сессии из будущего исключаются (перенесённое время/сдвиг часов)."""
    return sorted((s for s in sessions if s.performed_at <= now), key=lambda s: s.performed_at)


def _bounded(points: list[TrendPoint]) -> list[TrendPoint]:
    return points[-MAX_TREND_POINTS:]


def _sets_panel(
    protocol_type: str, exercise_id: int, name: str, entries: list[tuple[datetime, AnalyticsBlock]],
) -> ProtocolPanel:
    """reps_sets / time_sets: сумма значений подходов, число подходов,
    лучший подход, ряд по сессиям (сумма и лучший подход сессии)."""
    points: list[TrendPoint] = []
    total, sets, best = Decimal(0), 0, Decimal(0)
    for at, block in entries:
        values = [log.value for log in block.set_logs]
        if not values:
            continue
        session_total = sum(values, Decimal(0))
        total += session_total
        sets += len(values)
        best = max(best, max(values))
        points.append(TrendPoint(at=at, value=session_total, best=max(values)))
    is_reps = protocol_type == "reps_sets"
    return ProtocolPanel(
        exercise_id=exercise_id, exercise_name=name, protocol_type=protocol_type, session_count=len(points),
        unit="reps" if is_reps else "s",
        total_reps=total if is_reps else None, total_work_seconds=None if is_reps else total,
        set_count=sets, best_set=best, points=_bounded(points), points_total=len(points),
    )


def _max_panel(exercise_id: int, name: str, entries: list[tuple[datetime, AnalyticsBlock]]) -> ProtocolPanel:
    points: list[TrendPoint] = []
    attempts = 0
    cumulative: Decimal | None = None
    unit = "reps"
    for at, block in entries:
        values = [log.value for log in block.set_logs]
        if not values:
            continue
        unit = block.set_logs[-1].unit
        attempts += len(values)
        session_best = max(values)
        # Новый рекорд — строго лучше всего, что было ДО этой сессии; первая
        # запись — точка отсчёта, не "рекорд".
        is_pb = cumulative is not None and session_best > cumulative
        cumulative = session_best if cumulative is None else max(cumulative, session_best)
        points.append(TrendPoint(
            at=at, value=session_best, best=session_best, cumulative_best=cumulative, is_new_pb=is_pb,
        ))
    return ProtocolPanel(
        exercise_id=exercise_id, exercise_name=name, protocol_type="max_effort", session_count=len(points),
        unit=unit, attempt_count=attempts, best=cumulative, points=_bounded(points), points_total=len(points),
    )


def _interval_panel(exercise_id: int, name: str, entries: list[tuple[datetime, AnalyticsBlock]]) -> ProtocolPanel:
    points: list[TrendPoint] = []
    duration, cycles = 0, 0
    for at, block in entries:
        result = block.result
        if not isinstance(result, dict) or result.get("type") != "interval":
            continue  # невыполненный блок — не вклад
        actual = int(result.get("actual_duration_seconds", 0))
        done_cycles = int(result.get("completed_cycles", 0))
        duration += actual
        cycles += done_cycles
        points.append(TrendPoint(at=at, value=Decimal(actual), cycles=done_cycles))
    return ProtocolPanel(
        exercise_id=exercise_id, exercise_name=name, protocol_type="interval", session_count=len(points),
        actual_duration_seconds=duration, cycles=cycles, points=_bounded(points), points_total=len(points),
    )


_PANEL_BUILDERS = {
    "reps_sets": lambda *args: _sets_panel("reps_sets", *args),
    "time_sets": lambda *args: _sets_panel("time_sets", *args),
    "max_effort": _max_panel,
    "interval": _interval_panel,
}
_PROTOCOL_ORDER = {"reps_sets": 0, "time_sets": 1, "max_effort": 2, "interval": 3}


def compute_training_analytics(sessions: list[AnalyticsSession], now: datetime, tz: ZoneInfo) -> TrainingAnalytics:
    past = _completed_past(sessions, now)
    activity = compute_activity(past, now, tz)

    groups: dict[tuple[int, str], list[tuple[datetime, AnalyticsBlock]]] = {}
    names: dict[int, str] = {}
    for session in past:
        for block in session.blocks:
            if block.protocol_type is None or block.exercise_id is None:
                continue  # блок без идентичности/протокола: только активность
            groups.setdefault((block.exercise_id, block.protocol_type), []).append((session.performed_at, block))
            if block.max_set_logs and block.protocol_type == "reps_sets":
                groups.setdefault((block.exercise_id, "max_effort"), []).append(
                    (session.performed_at, AnalyticsBlock(
                        exercise_id=block.exercise_id, exercise_name=block.exercise_name,
                        protocol_type="max_effort", set_logs=block.max_set_logs,
                    )),
                )
            if block.exercise_name:
                names[block.exercise_id] = block.exercise_name  # самое свежее имя

    panels = [
        panel
        for (exercise_id, protocol), entries in groups.items()
        if (panel := _PANEL_BUILDERS[protocol](exercise_id, names.get(exercise_id, ""), entries)).session_count > 0
    ]
    panels.sort(key=lambda p: (p.exercise_name.lower(), _PROTOCOL_ORDER[p.protocol_type], p.exercise_id))
    return TrainingAnalytics(activity=activity, panels=panels)


# --- Метрики по неделям: тренировки / минуты (CRIMPD, #259; целые и сверенные, #308) ------

MIN_DURATION_SECONDS = 60
MAX_DURATION_SECONDS = 6 * 3600
MAX_RANGE_DAYS = 366


@dataclass(frozen=True)
class WeekMetric:
    week_start: date  # понедельник
    workouts: int
    minutes: int  # целые минуты, метод наибольшего остатка: Σ недель == total_minutes
    seconds: int = 0  # исходные секунды недели (A5: считаем в секундах, округляем один раз)


@dataclass(frozen=True)
class MetricsSeries:
    date_from: date
    date_to: date
    weeks: list[WeekMetric]
    total_workouts: int
    total_minutes: int
    without_duration: int  # тренировки диапазона, не попавшие в минуты (A5: неизвестная длительность)
    total_seconds: int = 0


def session_duration_seconds(session: AnalyticsSession) -> int | None:
    """completed_at - performed_at только если оба есть и результат в
    [1 мин, 6 ч]; иначе None (сессия — тренировка, но не минуты)."""
    if session.duration_seconds is not None:
        return session.duration_seconds
    if session.completed_at is None:
        return None
    seconds = (session.completed_at - session.performed_at).total_seconds()
    if MIN_DURATION_SECONDS <= seconds <= MAX_DURATION_SECONDS:
        return int(seconds)
    return None


def compute_metrics_series(
    sessions: list[AnalyticsSession], date_from: date, date_to: date, now: datetime, tz: ZoneInfo,
) -> MetricsSeries:
    """Недельные ряды (недели с понедельника в часовом поясе пользователя)
    по локальным дням [date_from, date_to]; сессии из будущего исключены.
    Каждая неделя диапазона присутствует в ряду, даже пустая.

    A5: секунды недель суммируются без потерь, total_minutes = round(Σ секунд / 60), а минуты недель —
    метод наибольшего остатка от тех же секунд, поэтому Σ weeks.minutes == total_minutes (раньше каждая
    неделя усекалась отдельно, и сумма расходилась с итогом, D13)."""
    week_seconds: dict[date, int] = {}
    week_workouts: dict[date, int] = {}
    without = 0
    total_seconds = 0
    total_workouts = 0
    for session in _completed_past(sessions, now):
        local_day = session.performed_at.astimezone(tz).date()
        if not date_from <= local_day <= date_to:
            continue
        week = _week_start(local_day)
        week_workouts[week] = week_workouts.get(week, 0) + 1
        total_workouts += 1
        seconds = session_duration_seconds(session)
        if seconds is None:
            without += 1
            continue
        week_seconds[week] = week_seconds.get(week, 0) + seconds
        total_seconds += seconds

    weeks_list: list[date] = []
    week = _week_start(date_from)
    last = _week_start(date_to)
    while week <= last:
        weeks_list.append(week)
        week += timedelta(weeks=1)
    total_minutes = round_minutes(total_seconds)
    minutes = allocate_largest_remainder([week_seconds.get(w, 0) for w in weeks_list], total_minutes)
    return MetricsSeries(
        date_from=date_from, date_to=date_to,
        weeks=[
            WeekMetric(
                week_start=w, workouts=week_workouts.get(w, 0), minutes=m, seconds=week_seconds.get(w, 0),
            )
            for w, m in zip(weeks_list, minutes, strict=True)
        ],
        total_workouts=total_workouts, total_minutes=total_minutes, without_duration=without,
        total_seconds=total_seconds,
    )


# --- Распределение по категориям (CRIMPD #274; одна категория на сессию, #308) ------------

OTHER_ACTIVITY_CATEGORY = OTHER_ACTIVITY_LABEL
UNCATEGORIZED = UNCATEGORIZED_LABEL


@dataclass(frozen=True)
class DistributionSub:
    name: str
    workouts: int
    minutes: int


@dataclass(frozen=True)
class DistributionCategory:
    name: str
    workouts: int
    minutes: int
    subcategories: list[DistributionSub]


@dataclass(frozen=True)
class Distribution:
    categories: list[DistributionCategory]
    total_workouts: int
    total_minutes: int


def primary_category_of(session: AnalyticsSession) -> tuple[str, str | None]:
    """A2: (категория, подкатегория) сессии — подписи для людей, ровно одна пара. Правило — в
    app.domain.canonical_history.attribute_primary_category; блок без упражнения/категории даёт
    «Без категории», а не пропадает."""
    result = attribute_primary_category(
        is_external_activity=session.activity_type is not None, activity_label=session.activity_label,
        blocks=[
            AttributionBlock(
                category=block.category, subcategory=block.subcategory,
                performed_sets=len(block.set_logs) + len(block.max_set_logs),
            )
            for block in session.blocks
        ],
    )
    return result.category, result.subcategory


def compute_distribution(
    sessions: list[AnalyticsSession], library: list[tuple[str, str | None]],
    date_from: date, date_to: date, now: datetime, tz: ZoneInfo,
) -> Distribution:
    """Тренировки и минуты по категориям за [date_from, date_to] (локальные дни; сессии из будущего
    исключены). library — (category, subcategory) каталога: их строки присутствуют и с нулями (подписи
    человеческие, дубли после сопоставления схлопываются). Каждая сессия — ровно в одной категории:
    Σ workouts по категориям == число тренировок диапазона, все счётчики целые (A1/A2). Сессия без
    валидной длительности даёт тренировку, но не минуты (A5). Минуты категорий — секунды, раздаваемые
    наибольшим остатком до итога round(Σ секунд / 60); внутри категории подкатегории — тем же
    методом до минут категории (остаток минут категории — «без подкатегории»)."""
    cells: dict[str, dict[str | None, list[int]]] = {}  # категория -> подкатегория|None -> [тренировки, секунды]
    for category, subcategory in library:
        label = category_label(category)
        if label == UNCATEGORIZED:
            continue  # «Без категории» из каталога не показываем нулевой строкой
        cells.setdefault(label, {None: [0, 0]})
        sub = subcategory_label(subcategory)
        if sub is not None:
            cells[label].setdefault(sub, [0, 0])
    total_seconds = 0
    for session in _completed_past(sessions, now):
        if not date_from <= session.performed_at.astimezone(tz).date() <= date_to:
            continue
        category, subcategory = primary_category_of(session)
        seconds = session_duration_seconds(session) or 0
        total_seconds += seconds
        group = cells.setdefault(category, {None: [0, 0]})
        for key in {None, subcategory}:
            cell = group.setdefault(key, [0, 0])
            cell[0] += 1
            cell[1] += seconds

    names = list(cells)
    total_minutes = round_minutes(total_seconds)
    category_minutes = allocate_largest_remainder([cells[name][None][1] for name in names], total_minutes)
    categories: list[DistributionCategory] = []
    for name, minutes in zip(names, category_minutes, strict=True):
        group = cells[name]
        sub_names = sorted((key for key in group if key is not None), key=str.lower)
        sub_minutes = allocate_sub_minutes([group[key][1] for key in sub_names], group[None][1], minutes)
        categories.append(DistributionCategory(
            name=name, workouts=group[None][0], minutes=minutes,
            subcategories=[
                DistributionSub(name=key, workouts=group[key][0], minutes=m)
                for key, m in zip(sub_names, sub_minutes, strict=True)
            ],
        ))
    # Крупные сверху; при равенстве — по имени. Служебные категории — в конце.
    tail = {OTHER_ACTIVITY_CATEGORY: 1, UNCATEGORIZED: 2}
    categories.sort(key=lambda c: (tail.get(c.name, 0), -c.workouts, c.name.lower()))
    return Distribution(
        categories=categories, total_workouts=sum(c.workouts for c in categories), total_minutes=total_minutes,
    )


def allocate_sub_minutes(sub_seconds: list[int], category_seconds: int, category_minutes: int) -> list[int]:
    """Минуты подкатегорий внутри категории: секунды подкатегорий + «остаток без подкатегории» делят
    минуты категории наибольшим остатком; возвращаются только подкатегории (Σ ≤ минут категории,
    остальное — строка категории без подкатегории)."""
    rest_seconds = max(category_seconds - sum(sub_seconds), 0)
    allocated = allocate_largest_remainder([*sub_seconds, rest_seconds], category_minutes)
    return allocated[:-1]
