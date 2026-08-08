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

    if len(parts) != expected_count:
        example = " ".join(["15"] * block.work_sets + ["18"])
        return ParseError(
            f"Нужно {expected_count} чисел через пробел (рабочие подходы + подход на максимум), "
            f"а я насчитал {len(parts)}. Например: {example}",
        )

    numbers = []
    for part in parts:
        if not part.isdigit():
            return ParseError(f"«{part}» — это не число. Введи только цифры через пробел.")
        value = int(part)
        if not (MIN_REPS <= value <= MAX_REPS):
            return ParseError(f"«{value}» — подозрительное число повторений (ожидается 0–{MAX_REPS}).")
        numbers.append(value)

    return BlockLog(working_reps=tuple(numbers[:-1]), max_reps=numbers[-1])
