"""app/domain/program_access.py — единое решение «можно ли тренироваться по программе» (правило 2026-10-07)."""

import pytest

from app.domain.program_access import (
    DEFAULT_PROGRAM_ACCESS_LEVEL,
    LEGACY_PULLUP_CASCADE_ACCESS_LEVEL,
    ProgramAccessLevel,
    program_training_allowed,
    programs_training_allowed,
)


@pytest.mark.parametrize("entitled", [True, False])
def test_free_program_is_allowed_regardless_of_entitlement(entitled: bool):
    assert program_training_allowed(ProgramAccessLevel.FREE, entitled=entitled) is True
    assert program_training_allowed("free", entitled=entitled) is True


def test_premium_and_missing_level_need_entitlement():
    for level in (ProgramAccessLevel.PREMIUM, "premium", None):
        assert program_training_allowed(level, entitled=True) is True
        assert program_training_allowed(level, entitled=False) is False


def test_mixed_request_needs_every_program_allowed():
    assert programs_training_allowed(["free", "free"], entitled=False) is True
    assert programs_training_allowed(["free", "premium"], entitled=False) is False
    assert programs_training_allowed(["free", None], entitled=False) is False
    assert programs_training_allowed(["free", "premium"], entitled=True) is True


def test_defaults_new_programs_premium_and_legacy_cascade_free():
    assert DEFAULT_PROGRAM_ACCESS_LEVEL is ProgramAccessLevel.PREMIUM
    assert LEGACY_PULLUP_CASCADE_ACCESS_LEVEL is ProgramAccessLevel.FREE
