"""Чистая логика обзора плана (issue #266): человекочитаемые подписи расписания
программы и номер недели курса. Без БД и aiogram; «сегодня» приходит снаружи."""

from datetime import date

_BLOCK_ROLE_TITLES = {"block_a": "Блок A", "block_b": "Блок Б"}


def duration_weeks(config: dict | None) -> int | None:
    """Длина курса в неделях — только если она явно задана в config
    (`duration_weeks` — положительное целое); иначе None, длину не выдумываем."""
    value = (config or {}).get("duration_weeks")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def course_week_number(started_on: date, today: date, total_weeks: int | None) -> int | None:
    """Номер недели курса (с 1) для курса фиксированной длины; None без длины.
    После окончания остаётся на последней неделе, до старта — на первой."""
    if total_weeks is None:
        return None
    week = max((today - started_on).days, 0) // 7 + 1
    return min(week, total_weeks)


def count_per_week_label(count: int) -> str:
    """«1 раз в неделю», «3 раза в неделю», «5 раз в неделю»."""
    tail = count % 100
    if tail % 10 in (2, 3, 4) and tail not in (12, 13, 14):
        word = "раза"
    else:
        word = "раз"
    return f"{count} {word} в неделю"


def block_role_title(subcategory: str | None) -> str | None:
    """Человеческое имя внутренней STEP-роли упражнения (block_a/block_b)."""
    return _BLOCK_ROLE_TITLES.get(subcategory) if subcategory else None


def block_target_label(config: dict | None, subcategory: str | None) -> str | None:
    """Стартовая цель блока из config программы («старт: 10 повт. × 3 подх.»);
    None, если в config её нет — ничего не придумываем."""
    if subcategory not in _BLOCK_ROLE_TITLES:
        return None
    block = (config or {}).get(subcategory)
    if not isinstance(block, dict):
        return None
    target, sets = block.get("base_target"), block.get("work_sets")
    if not isinstance(target, int) or isinstance(target, bool):
        return None
    if isinstance(sets, int) and not isinstance(sets, bool):
        return f"старт: {target} повт. × {sets} подх."
    return f"старт: {target} повт."
