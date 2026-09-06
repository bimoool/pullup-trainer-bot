from datetime import date

from app.domain.gto import (
    MALE,
    GtoRank,
    calculate_gto_status,
    resolve_gto_age_step,
)

TODAY = date(2026, 9, 6)


def _birth_date_for_exact_age(years: int) -> date:
    return date(TODAY.year - years, TODAY.month, TODAY.day)


def test_resolve_age_step_under_18_is_none():
    assert resolve_gto_age_step(17) is None


def test_resolve_age_step_boundaries():
    assert resolve_gto_age_step(18).number == 7
    assert resolve_gto_age_step(19).number == 7
    assert resolve_gto_age_step(20).number == 8
    assert resolve_gto_age_step(24).number == 8
    assert resolve_gto_age_step(69).number == 17
    assert resolve_gto_age_step(70).number == 18
    assert resolve_gto_age_step(120).number == 18


def test_calculate_status_not_male():
    status = calculate_gto_status(
        gender="female", birth_date=_birth_date_for_exact_age(25), best_max_reps=20, today=TODAY,
    )
    assert status.applicable is False
    assert status.reason == "only_male"


def test_calculate_status_missing_birth_date():
    status = calculate_gto_status(gender=MALE, birth_date=None, best_max_reps=20, today=TODAY)
    assert status.applicable is False
    assert status.reason == "missing_birth_date"


def test_calculate_status_under_18():
    status = calculate_gto_status(
        gender=MALE, birth_date=_birth_date_for_exact_age(17), best_max_reps=20, today=TODAY,
    )
    assert status.applicable is False
    assert status.reason == "age_out_of_range"
    assert status.age == 17


def test_calculate_status_norm_data_missing_for_step_16():
    status = calculate_gto_status(
        gender=MALE, birth_date=_birth_date_for_exact_age(62), best_max_reps=20, today=TODAY,
    )
    assert status.applicable is False
    assert status.reason == "norm_data_missing"
    assert status.step_number == 16


def test_calculate_status_no_workouts():
    status = calculate_gto_status(
        gender=MALE, birth_date=_birth_date_for_exact_age(22), best_max_reps=None, today=TODAY,
    )
    assert status.applicable is False
    assert status.reason == "no_workouts"
    assert status.step_number == 8


def test_calculate_status_step_8_rank_boundaries():
    # 8 ступень (20-24 года): золото=16, серебро=13, бронза=9 — подтверждено
    # автором issue #71 напрямую с gto.ru.
    birth_date = _birth_date_for_exact_age(22)

    below_bronze = calculate_gto_status(gender=MALE, birth_date=birth_date, best_max_reps=8, today=TODAY)
    assert below_bronze.rank == GtoRank.NONE
    assert below_bronze.next_rank == GtoRank.BRONZE
    assert below_bronze.reps_to_next_rank == 1

    bronze = calculate_gto_status(gender=MALE, birth_date=birth_date, best_max_reps=9, today=TODAY)
    assert bronze.rank == GtoRank.BRONZE
    assert bronze.next_rank == GtoRank.SILVER
    assert bronze.reps_to_next_rank == 4

    silver = calculate_gto_status(gender=MALE, birth_date=birth_date, best_max_reps=13, today=TODAY)
    assert silver.rank == GtoRank.SILVER
    assert silver.next_rank == GtoRank.GOLD
    assert silver.reps_to_next_rank == 3

    gold = calculate_gto_status(gender=MALE, birth_date=birth_date, best_max_reps=16, today=TODAY)
    assert gold.rank == GtoRank.GOLD
    assert gold.next_rank is None
    assert gold.reps_to_next_rank is None

    above_gold = calculate_gto_status(gender=MALE, birth_date=birth_date, best_max_reps=30, today=TODAY)
    assert above_gold.rank == GtoRank.GOLD
