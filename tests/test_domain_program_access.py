"""app/domain/program_access.py — единое решение «можно ли тренироваться по программе» (правило 2026-10-07)."""

import pytest

from app.domain.program_access import (
    DEFAULT_PROGRAM_ACCESS_LEVEL,
    EXTRA_TRAINING_ACCESS_LEVEL,
    LEGACY_PULLUP_CASCADE_ACCESS_LEVEL,
    ProgramAccessLevel,
    premium_feature_allowed,
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


def test_extra_training_and_premium_features_need_entitlement_2026_10_17():
    """Решение 2026-10-17: доп. часть тренировки (без программы) и свой контент — Premium; смешанный старт
    «Подтягивания» + доп. часть без подписки отклоняется целиком."""
    assert EXTRA_TRAINING_ACCESS_LEVEL is ProgramAccessLevel.PREMIUM
    assert premium_feature_allowed(entitled=True) is True
    assert premium_feature_allowed(entitled=False) is False
    assert programs_training_allowed(["free", EXTRA_TRAINING_ACCESS_LEVEL], entitled=False) is False
    assert programs_training_allowed(["free", EXTRA_TRAINING_ACCESS_LEVEL], entitled=True) is True
