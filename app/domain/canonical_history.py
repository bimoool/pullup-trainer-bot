"""Каноническая история: чистые правила Журнала/Профиля/Аналитики поверх TrainingSession (issue #308).

Контракт: docs/domain/TRAINING_SESSION_V2.md §6 (A1–A8) и docs/domain/MIGRATION_V2.md §4. Ни SQLAlchemy,
ни времени «сейчас» здесь нет.

Что решено этим модулем (а не разбросано по эндпоинтам):

* A2 — ``attribute_primary_category``: КАЖДАЯ сессия попадает ровно в одну категорию (тренировка
  атомарна; долей тренировки не существует);
* A5 — ``round_minutes`` и ``allocate_largest_remainder``: минуты считаются в секундах, округляются один
  раз для итога, а недели/категории получают целые минуты методом наибольшего остатка, так что сумма
  частей РАВНА показанному итогу;
* A3 — подписи только человеческие (``app.domain.exercise_identity.category_label`` и др.).

Продуктовые числа (решение продукта, не научный факт): ничьи в наибольшем остатке разрешаются в пользу
более раннего элемента (детерминизм); округление итога — «половина вверх» (30 с и больше — минута).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.exercise_identity import (
    OTHER_ACTIVITY_LABEL,
    UNCATEGORIZED_LABEL,
    category_label,
    subcategory_label,
)

SECONDS_PER_MINUTE = 60


def round_minutes(total_seconds: int) -> int:
    """Итог минут = round(Σ секунд / 60), половина вверх (целочисленно, без float)."""
    if total_seconds < 0:
        raise ValueError("seconds < 0")
    return (total_seconds + SECONDS_PER_MINUTE // 2) // SECONDS_PER_MINUTE


def allocate_largest_remainder(seconds: Sequence[int], total_minutes: int | None = None) -> list[int]:
    """A5: целые минуты по частям так, что Σ = total_minutes (по умолчанию round_minutes(Σ секунд)).

    Каждая часть получает floor(секунды / 60); недостающие минуты (total − Σ floor) раздаются частям с
    наибольшим остатком секунд, при равенстве — раньше стоящей. Часть с нулевым остатком минуты сверх
    своей не получает: пустая неделя остаётся нулём. Если total меньше Σ floor (вызывающий передал
    заведомо меньший итог) — ValueError, а не молчаливая подгонка."""
    if any(value < 0 for value in seconds):
        raise ValueError("seconds < 0")
    target = round_minutes(sum(seconds)) if total_minutes is None else total_minutes
    floors = [value // SECONDS_PER_MINUTE for value in seconds]
    extra = target - sum(floors)
    if extra < 0:
        raise ValueError("total_minutes below the sum of whole minutes")
    candidates = sorted(
        (index for index, value in enumerate(seconds) if value % SECONDS_PER_MINUTE > 0),
        key=lambda index: (-(seconds[index] % SECONDS_PER_MINUTE), index),
    )
    if extra > len(candidates):
        raise ValueError("total_minutes unreachable for these parts")
    result = list(floors)
    for index in candidates[:extra]:
        result[index] += 1
    return result


# --- A2: одна категория на сессию -------------------------------------------------------------


@dataclass(frozen=True)
class AttributionBlock:
    """Блок сессии для атрибуции: сырая категория/подкатегория упражнения (slug, старая строка или
    подпись) и число ВЫПОЛНЕННЫХ подходов (подходы сверх плана считаются, невыполненные — нет)."""

    category: str | None
    subcategory: str | None
    performed_sets: int


@dataclass(frozen=True)
class PrimaryCategory:
    category: str  # человеческая подпись
    subcategory: str | None = None  # человеческая подпись публичной подкатегории; служебные — None


def attribute_primary_category(
    *, is_external_activity: bool, activity_label: str | None, blocks: Sequence[AttributionBlock],
) -> PrimaryCategory:
    """TRAINING_SESSION_V2 §6 A2, детерминированно:

    1. внешняя активность → «Другая активность» (подкатегория — подпись вида: «Бег»; неизвестный вид — нет);
    2. силовая сессия → категория блока с наибольшим числом выполненных подходов; при равенстве — первый
       блок (по порядку). Курс «Подтягивания» (блоки A и Б — упражнения подкатегорий block_a/block_b),
       факультатив, ручная запись «из моих», копия и пользовательская тренировка проходят ОДНО правило:
       источник сессии на категорию не влияет;
    3. сессия без блоков → «Без категории».

    Контракт называет первой строкой «категорию определения тренировки, если задана». В схеме 1a/3a у
    определения (complexes) собственной категории нет — её единственное выражение это категории его
    упражнений, поэтому правило 2 и есть категория определения; когда у определения появится явная
    категория, она встанет шагом 1.5 здесь, остальное не изменится."""
    if is_external_activity:
        return PrimaryCategory(OTHER_ACTIVITY_LABEL, activity_label)
    if not blocks:
        return PrimaryCategory(UNCATEGORIZED_LABEL)
    best = blocks[0]
    for block in blocks[1:]:
        if block.performed_sets > best.performed_sets:
            best = block
    return PrimaryCategory(category_label(best.category), subcategory_label(best.subcategory))
