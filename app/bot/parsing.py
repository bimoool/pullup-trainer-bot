from dataclasses import dataclass

from app.domain.constants import BlockConfig
from app.domain.session import BlockLog

MIN_REPS = 0
MAX_REPS = 100  # разумный верхний предел на одно число — не тренировочная константа, просто защита от опечаток


@dataclass(frozen=True)
class ParseError:
    message: str


def parse_block_result(raw_text: str, block: BlockConfig) -> BlockLog | ParseError:
    """Разбирает ввод вида "15 15 15 18": block.work_sets рабочих подходов
    + один подход на максимум, через пробел. Не домен — домен работает с
    типизированными данными, а не строками пользовательского ввода."""
    parts = raw_text.split()
    expected_count = block.work_sets + 1
    example = " ".join(["15"] * block.work_sets + ["18"])

    if len(parts) != expected_count:
        return ParseError(
            f"Нужно {expected_count} чисел через пробел (рабочие подходы + подход на максимум), "
            f"а я насчитал {len(parts)}. Например: {example}",
        )

    numbers = []
    for part in parts:
        if not part.isdigit():
            return ParseError(f"«{part}» — не разобрал как число. Пришли только цифры через пробел, например: {example}")
        value = int(part)
        if not (MIN_REPS <= value <= MAX_REPS):
            return ParseError(f"«{value}» — не похоже на число повторений (жду 0–{MAX_REPS}). Например: {example}")
        numbers.append(value)

    return BlockLog(working_reps=tuple(numbers[:-1]), max_reps=numbers[-1])


def parse_free_reps(raw_text: str) -> BlockLog | ParseError:
    """Разбирает произвольное количество подходов (Часть 10, пакет #2,
    п.21 — свободные подтягивания вне схемы: не фиксированные 3+1, как в
    parse_block_result, а сколько реально сделал, столько и ввёл). Хотя бы
    одно число обязательно. Последнее введённое число условно уходит в
    max_reps (для читаемого отображения "максимум N" в истории) — порядок
    ввода для свободной тренировки смысловой роли не играет."""
    parts = raw_text.split()
    if not parts:
        return ParseError("Нужно хотя бы одно число повторений через пробел, например: 8 6 5")

    numbers = []
    for part in parts:
        if not part.isdigit():
            return ParseError(f"«{part}» — не разобрал как число. Пришли повторения по подходам через пробел, например: 8 6 5")
        value = int(part)
        if not (MIN_REPS <= value <= MAX_REPS):
            return ParseError(f"«{value}» — не похоже на число повторений (жду 0–{MAX_REPS}). Например: 8 6 5")
        numbers.append(value)

    return BlockLog(working_reps=tuple(numbers[:-1]), max_reps=numbers[-1])
