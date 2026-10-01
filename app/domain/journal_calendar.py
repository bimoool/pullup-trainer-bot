"""Календарь Журнала (#256): границы месяца и разбивка моментов по локальным дням.

Чистая логика — без БД/aiogram; часовой пояс приходит снаружи."""

import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_month(value: str) -> tuple[int, int]:
    """'YYYY-MM' -> (year, month); иначе ValueError."""
    match = _MONTH_RE.match(value)
    if match is None or int(match.group(1)) < 1900:
        raise ValueError(f"месяц должен быть в формате YYYY-MM: {value!r}")
    return int(match.group(1)), int(match.group(2))


def month_date_range(year: int, month: int) -> tuple[date, date]:
    """Первый и последний локальный день месяца."""
    first = date(year, month, 1)
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first, next_first - timedelta(days=1)


def local_range_bounds_utc(first_day: date, last_day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start, end) в UTC для локальных дней first_day..last_day включительно."""
    start = datetime.combine(first_day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def local_day_counts(moments: Iterable[datetime], tz: tzinfo) -> dict[date, int]:
    """Число моментов на каждый локальный день (aware datetime -> дата в tz)."""
    return dict(Counter(moment.astimezone(tz).date() for moment in moments))
