from datetime import date

from app.domain.leaderboard import age_bucket

TODAY = date(2026, 9, 6)


def _birth_date_for_exact_age(years: int) -> date:
    return date(TODAY.year - years, TODAY.month, TODAY.day)


def test_age_bucket_none_for_missing_birth_date():
    assert age_bucket(None, TODAY) is None


def test_age_bucket_none_for_under_18():
    assert age_bucket(_birth_date_for_exact_age(17), TODAY) is None


def test_age_bucket_boundaries():
    assert age_bucket(_birth_date_for_exact_age(18), TODAY) == "18_29"
    assert age_bucket(_birth_date_for_exact_age(29), TODAY) == "18_29"
    assert age_bucket(_birth_date_for_exact_age(30), TODAY) == "30_39"
    assert age_bucket(_birth_date_for_exact_age(39), TODAY) == "30_39"
    assert age_bucket(_birth_date_for_exact_age(40), TODAY) == "40_49"
    assert age_bucket(_birth_date_for_exact_age(49), TODAY) == "40_49"
    assert age_bucket(_birth_date_for_exact_age(50), TODAY) == "50_59"
    assert age_bucket(_birth_date_for_exact_age(59), TODAY) == "50_59"
    assert age_bucket(_birth_date_for_exact_age(60), TODAY) == "60_69"
    assert age_bucket(_birth_date_for_exact_age(69), TODAY) == "60_69"
    assert age_bucket(_birth_date_for_exact_age(70), TODAY) == "70_plus"
    assert age_bucket(_birth_date_for_exact_age(100), TODAY) == "70_plus"


def test_age_bucket_birthday_not_yet_occurred_this_year():
    # Родился 2008-09-07, "сегодня" 2026-09-06 — день рождения ещё не
    # наступил в этом году, реальный возраст 17, не 18.
    assert age_bucket(date(2008, 9, 7), TODAY) is None


def test_age_bucket_birthday_already_occurred_this_year():
    # Родился 2008-09-05 — день рождения уже прошёл, реальный возраст 18.
    assert age_bucket(date(2008, 9, 5), TODAY) == "18_29"
