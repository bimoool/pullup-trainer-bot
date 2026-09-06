from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class LeaderboardMetric(StrEnum):
    MAX_REPS = "max_reps"
    MAX_WEIGHT = "max_weight"
    TOTAL_VOLUME = "total_volume"


# Возрастные ступени ГТО для взрослых (issue #67) — взяты как готовый
# ориентир по просьбе автора, а не потому что это официальный стандарт для
# лидерборда: 6 категорий не мельчат выборку на типичном объёме
# пользователей. Пользователи младше 18 (age_bucket ниже вернёт None) сюда
# не попадают — учитываются только в общем зачёте (фильтр "все").
AGE_BUCKETS: tuple[str, ...] = ("18_29", "30_39", "40_49", "50_59", "60_69", "70_plus")

LEADERBOARD_TOP_LIMIT: int = 20


def age_bucket(birth_date: date | None, today: date) -> str | None:
    """Тот же расчёт возраста, что app.bot.formatting.calculate_age (не
    импортируется отсюда — app/domain/ не должен зависеть от app/bot/, а
    расчёт достаточно короткий, чтобы продублировать явно). None — нет даты
    рождения или младше 18 лет: такой пользователь попадает только в общий
    зачёт лидерборда (app/db/repositories/leaderboard.py зеркалит эту же
    логику в SQL для фильтрации по возрастной категории)."""
    if birth_date is None:
        return None
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    if years < 18:
        return None
    if years <= 29:
        return "18_29"
    if years <= 39:
        return "30_39"
    if years <= 49:
        return "40_49"
    if years <= 59:
        return "50_59"
    if years <= 69:
        return "60_69"
    return "70_plus"


@dataclass(frozen=True)
class LeaderboardEntry:
    """Одна строка лидерборда — то, во что LeaderboardRepository.top()
    конвертирует сырые строки агрегирующего SQL-запроса. value — Decimal
    для max_weight (Numeric-колонка), int для max_reps/total_volume (сумма/
    максимум целых повторений)."""

    user_id: int
    display_name: str | None
    value: Decimal | int
    rank: int
    is_current_user: bool
