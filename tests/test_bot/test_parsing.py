"""parse_reps (пакет #4) — объединяет прежние parse_block_result и
parse_free_reps: произвольное количество чисел через пробел, без жёсткого
требования "ровно work_sets + 1" (несовпадение с ожидаемым структурно
количеством — теперь мягкая аномалия, см. tests/test_anomalies.py, не
повод отклонить ввод на этапе парсинга)."""

from app.bot.parsing import ParseError, parse_reps
from app.domain.session import BlockLog


def test_parses_valid_input():
    result = parse_reps("15 15 15 18")
    assert result == BlockLog(working_reps=(15, 15, 15), max_reps=18)


def test_handles_extra_whitespace():
    result = parse_reps("  15   15  15   18  ")
    assert result == BlockLog(working_reps=(15, 15, 15), max_reps=18)


def test_accepts_fewer_numbers_than_structurally_expected():
    # Раньше жёстко отклонялось ("Нужно 4 числа... а я насчитал 3") —
    # теперь принимается, несовпадение уходит в detect_anomalies.
    result = parse_reps("15 15 18")
    assert result == BlockLog(working_reps=(15, 15), max_reps=18)


def test_accepts_more_numbers_than_structurally_expected():
    result = parse_reps("15 15 15 15 18")
    assert result == BlockLog(working_reps=(15, 15, 15, 15), max_reps=18)


def test_accepts_single_number():
    result = parse_reps("8")
    assert result == BlockLog(working_reps=(), max_reps=8)


def test_rejects_empty_input():
    result = parse_reps("")
    assert isinstance(result, ParseError)


def test_rejects_non_numeric_token():
    result = parse_reps("15 пятнадцать 15 18")
    assert isinstance(result, ParseError)
    assert "пятнадцать" in result.message


def test_rejects_negative_number():
    result = parse_reps("15 -5 15 18")
    assert isinstance(result, ParseError)


def test_rejects_number_above_hard_cap():
    # Жёсткий предел ввода (parsing.MAX_REPS=100) остаётся — это защита от
    # опечаток, не то же самое, что мягкий порог аномалии (50).
    result = parse_reps("15 15 15 999")
    assert isinstance(result, ParseError)


def test_accepts_zero():
    result = parse_reps("0 0 0 0")
    assert result == BlockLog(working_reps=(0, 0, 0), max_reps=0)
