from dataclasses import dataclass

from app.domain.session import BlockLog

MIN_REPS = 0
MAX_REPS = 100  # разумный верхний предел на одно число — не тренировочная константа, просто защита от опечаток


@dataclass(frozen=True)
class ParseError:
    message: str


def parse_reps(raw_text: str) -> BlockLog | ParseError:
    """Разбирает произвольное количество подходов через пробел — сколько
    реально сделал, столько и ввёл, без фиксированного количества
    (пакет #4: раньше parse_block_result жёстко требовал ровно
    block.work_sets + 1 чисел и отклонял любое другое количество; теперь
    несовпадение с ожидаемым числом подходов — не отказ, а мягкая
    аномалия, см. app.domain.anomalies.detect_anomalies). Хотя бы одно
    число обязательно. Последнее число — подход на максимум, все числа
    перед ним — рабочие подходы."""
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


def parse_int_sequence(raw_text: str) -> list[int] | ParseError:
    """Как parse_reps, но БЕЗ выделения последнего числа в "подход на
    максимум" — плоский список, каждое число равноправно (факультативы,
    app/bot/handlers/electives.py: каждое введённое число — повторения в
    своём подходе, нет отдельного "финального" подхода на максимум, в
    отличие от структурных блоков A/B)."""
    parts = raw_text.split()
    if not parts:
        return ParseError("Нужно хотя бы одно число повторений через пробел, например: 8 6 5")

    numbers = []
    for part in parts:
        if not part.isdigit():
            return ParseError(f"«{part}» — не разобрал как число. Пришли повторения через пробел, например: 8 6 5")
        value = int(part)
        if not (MIN_REPS <= value <= MAX_REPS):
            return ParseError(f"«{value}» — не похоже на число повторений (жду 0–{MAX_REPS}). Например: 8 6 5")
        numbers.append(value)

    return numbers
