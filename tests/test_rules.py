from datetime import date, timedelta

from app.domain.rules import (
    TrainingReadiness,
    check_training_readiness,
    is_baseline_expired,
    is_set_complete,
)

LAST_WORKOUT = date(2026, 1, 1)


def _check(days: int):
    return check_training_readiness(LAST_WORKOUT, LAST_WORKOUT + timedelta(days=days))


# --- check_training_readiness: базовые статусы -----------------------------

def test_readiness_zero_days_is_too_early():
    result = _check(0)
    assert result.status == TrainingReadiness.TOO_EARLY
    assert result.ready_at == LAST_WORKOUT + timedelta(days=2)


def test_readiness_one_day_is_too_early():
    assert _check(1).status == TrainingReadiness.TOO_EARLY


def test_readiness_mid_range_is_ready():
    assert _check(10).status == TrainingReadiness.READY


# --- граница MIN_REST_DAYS (2) ----------------------------------------------

def test_readiness_at_min_rest_days_is_ready():
    assert _check(2).status == TrainingReadiness.READY


# --- граница GAP_ROLLBACK_DAYS (21) -----------------------------------------

def test_readiness_day_20_is_still_ready():
    assert _check(20).status == TrainingReadiness.READY


def test_readiness_day_21_is_gap_rollback():
    assert _check(21).status == TrainingReadiness.GAP_ROLLBACK


# --- граница GAP_RETEST_DAYS (35) -------------------------------------------

def test_readiness_day_35_is_still_gap_rollback():
    # день 35 — последний день отката, а не триггер нового замера
    assert _check(35).status == TrainingReadiness.GAP_ROLLBACK


def test_readiness_day_36_requires_retest():
    assert _check(36).status == TrainingReadiness.GAP_RETEST_REQUIRED


def test_readiness_reports_days_since_last_workout():
    assert _check(21).days_since_last_workout == 21


# --- is_baseline_expired: другая точка отсчёта, >= верно --------------------

def test_baseline_not_expired_at_34_days():
    baseline = date(2026, 1, 1)
    assert is_baseline_expired(baseline, baseline + timedelta(days=34)) is False


def test_baseline_expired_at_35_days():
    baseline = date(2026, 1, 1)
    assert is_baseline_expired(baseline, baseline + timedelta(days=35)) is True


def test_baseline_expired_well_past_35_days():
    baseline = date(2026, 1, 1)
    assert is_baseline_expired(baseline, baseline + timedelta(days=60)) is True


# --- is_set_complete ----------------------------------------------------------

def test_set_not_complete_at_eleven():
    assert is_set_complete(11) is False


def test_set_complete_at_twelve():
    assert is_set_complete(12) is True


def test_set_complete_beyond_twelve():
    assert is_set_complete(13) is True
