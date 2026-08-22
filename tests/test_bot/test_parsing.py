"""parse_reps (пакет #4) — объединяет прежние parse_block_result и
parse_free_reps: произвольное количество чисел через пробел, без жёсткого
требования "ровно work_sets + 1" (несовпадение с ожидаемым структурно
количеством — теперь мягкая аномалия, см. tests/test_anomalies.py, не
повод отклонить ввод на этапе парсинга)."""

from app.bot.parsing import ParseError, parse_int_sequence, parse_reps
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
    # Жёсткий предел ввода (parsing.MAX_REPS=999) остаётся — это защита от
    # опечаток (лишний ноль и т.п.), не то же самое, что мягкий порог
    # аномалии (50), который только переспрашивает, не блокирует.
    result = parse_reps("15 15 15 1000")
    assert isinstance(result, ParseError)


def test_accepts_three_digit_number():
    # Баг: раньше MAX_REPS был 100, любое трёхзначное число (например 102)
    # жёстко отклонялось — трёхзначные результаты вполне реальны (высокий
    # объём, факультативы на объём и т.п.), это не опечатка.
    result = parse_reps("15 15 15 102")
    assert result == BlockLog(working_reps=(15, 15, 15), max_reps=102)


def test_accepts_zero():
    result = parse_reps("0 0 0 0")
    assert result == BlockLog(working_reps=(0, 0, 0), max_reps=0)


# --- parse_int_sequence (пакет #6, факультативы) — без выделения "максимума" -------


def test_int_sequence_all_numbers_are_equal_no_max_split():
    assert parse_int_sequence("12 10 8 6") == [12, 10, 8, 6]


def test_int_sequence_single_number():
    assert parse_int_sequence("52") == [52]


def test_int_sequence_rejects_empty_input():
    assert isinstance(parse_int_sequence(""), ParseError)


def test_int_sequence_rejects_non_numeric_token():
    result = parse_int_sequence("5 four 3")
    assert isinstance(result, ParseError)
    assert "four" in result.message


def test_int_sequence_rejects_above_hard_cap():
    assert isinstance(parse_int_sequence("5 4 1000"), ParseError)


def test_int_sequence_accepts_three_digit_number():
    assert parse_int_sequence("102 50 30") == [102, 50, 30]
