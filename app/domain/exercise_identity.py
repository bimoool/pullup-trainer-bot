"""Идентичность упражнения и категории (issue #303, WORKOUT_DOMAIN_V2 §2, инварианты E1–E4).

- E1: любая видимая пользователю строка об упражнении/категории — display_name. Внутренний
  slug (`pull_ups`, `block_a`, `user`, …) — ключ сида, не подпись.
- E2: история и аналитика группируют по analytics_identity = analytics_exercise_id ?? id —
  служебные «Подтягивания — объём/сила» и факультативы указывают на публичное «Подтягивания».
- E3: пользовательские упражнения получают категорию «Мои упражнения», не строку "user".

Таблица соответствия «старая строка категории → категория» — канонический справочник для
кода; миграция b7d2e9f4a1c3 содержит его замороженную копию (конвенция репозитория: ревизия
не импортирует живые константы).
"""

import re
from dataclasses import dataclass

SLUG_PATTERN = re.compile(r"^[a-z_]+$")
UNNAMED_EXERCISE_LABEL = "Упражнение"


@dataclass(frozen=True)
class CategorySeed:
    slug: str
    display_name: str
    parent_slug: str | None
    sort_order: int
    is_service: bool


CATEGORY_PULL_UPS = "pull_ups"
CATEGORY_MY_EXERCISES = "my_exercises"
CATEGORY_UNCATEGORIZED = "uncategorized"

CATEGORY_SEEDS: tuple[CategorySeed, ...] = (
    CategorySeed(CATEGORY_PULL_UPS, "Подтягивания", None, 10, False),
    CategorySeed("grip", "Хват", None, 20, False),
    CategorySeed("general_fitness", "Общая физическая подготовка", None, 30, False),
    CategorySeed(CATEGORY_MY_EXERCISES, "Мои упражнения", None, 90, False),
    CategorySeed(CATEGORY_UNCATEGORIZED, "Без категории", None, 99, False),
    # Служебные подкатегории курса «Подтягивания» и факультативов: в аналитике не видны как
    # отдельные упражнения (E2), но и у них есть человеческое имя (E1).
    CategorySeed("block_a", "Блок A — объём", CATEGORY_PULL_UPS, 11, True),
    CategorySeed("block_b", "Блок Б — сила", CATEGORY_PULL_UPS, 12, True),
    CategorySeed("elective_max_reps_ladder", "Факультатив — на максимум", CATEGORY_PULL_UPS, 13, True),
    CategorySeed("elective_w_ladder", "Факультатив — W", CATEGORY_PULL_UPS, 14, True),
    CategorySeed("elective_three_minutes", "Факультатив — 3 минуты", CATEGORY_PULL_UPS, 15, True),
    CategorySeed("elective_volume_target", "Факультатив — на объём", CATEGORY_PULL_UPS, 16, True),
)

# Строки, реально встречающиеся в exercises.category / subcategory (сид a4c8e1f7b2d9,
# scripts/seed_exercise_library.py, ProgramRepository.create_user_exercise).
LEGACY_CATEGORY_TO_SLUG: dict[str, str] = {
    "pull_ups": CATEGORY_PULL_UPS,
    "Подтягивания": CATEGORY_PULL_UPS,
    "Хват": "grip",
    "Общая физическая подготовка": "general_fitness",
    "user": CATEGORY_MY_EXERCISES,
}
LEGACY_SUBCATEGORY_TO_SLUG: dict[str, str] = {
    seed.slug: seed.slug for seed in CATEGORY_SEEDS if seed.is_service
}


def category_slug_for_legacy(category: str | None) -> str:
    """Неизвестная строка → «Без категории» (MIGRATION §3: не угадываем, а сообщаем)."""
    if category is None:
        return CATEGORY_UNCATEGORIZED
    return LEGACY_CATEGORY_TO_SLUG.get(category, CATEGORY_UNCATEGORIZED)


def subcategory_slug_for_legacy(subcategory: str | None) -> str | None:
    if subcategory is None:
        return None
    return LEGACY_SUBCATEGORY_TO_SLUG.get(subcategory)


def looks_like_slug(text: str | None) -> bool:
    return text is not None and bool(SLUG_PATTERN.match(text))


def exercise_display_label(display_name: str | None, name: str | None) -> str:
    """Подпись упражнения для UI. display_name — канон (E1); старое name — только если
    display_name ещё не заполнен (строка до бэкфилла); slug не становится подписью никогда."""
    for candidate in (display_name, name):
        if candidate is not None and candidate.strip() and not looks_like_slug(candidate.strip()):
            return candidate.strip()
    return UNNAMED_EXERCISE_LABEL


def analytics_identity(exercise_id: int, analytics_exercise_id: int | None) -> int:
    """E2: в истории/аналитике упражнение — это analytics_exercise_id ?? id."""
    return analytics_exercise_id if analytics_exercise_id is not None else exercise_id
