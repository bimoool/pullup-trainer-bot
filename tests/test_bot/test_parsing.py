from app.bot.parsing import ParseError, parse_block_result
from app.domain.constants import BLOCK_A, BLOCK_B
from app.domain.session import BlockLog


def test_parses_valid_block_a_input():
    result = parse_block_result("15 15 15 18", BLOCK_A)
    assert result == BlockLog(working_reps=(15, 15, 15), max_reps=18)


def test_parses_valid_block_b_input():
    result = parse_block_result("3 3 3 3 4", BLOCK_B)
    assert result == BlockLog(working_reps=(3, 3, 3, 3), max_reps=4)


def test_handles_extra_whitespace():
    result = parse_block_result("  15   15  15   18  ", BLOCK_A)
    assert result == BlockLog(working_reps=(15, 15, 15), max_reps=18)


def test_rejects_too_few_numbers():
    result = parse_block_result("15 15 18", BLOCK_A)
    assert isinstance(result, ParseError)
    assert "3" in result.message  # получено 3, ожидалось 4


def test_rejects_too_many_numbers():
    result = parse_block_result("15 15 15 15 18", BLOCK_A)
    assert isinstance(result, ParseError)


def test_rejects_non_numeric_token():
    result = parse_block_result("15 пятнадцать 15 18", BLOCK_A)
    assert isinstance(result, ParseError)
    assert "пятнадцать" in result.message


def test_rejects_negative_number():
    result = parse_block_result("15 -5 15 18", BLOCK_A)
    assert isinstance(result, ParseError)


def test_rejects_unreasonably_large_number():
    result = parse_block_result("15 15 15 999", BLOCK_A)
    assert isinstance(result, ParseError)


def test_accepts_zero():
    result = parse_block_result("0 0 0 0", BLOCK_A)
    assert result == BlockLog(working_reps=(0, 0, 0), max_reps=0)
