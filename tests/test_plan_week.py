"""Checkpoint 1 (issue #188): plan_week_number/plan_week_start_date —
чистые функции, без БД. Покрывает ровно то, что требовал preflight:
явное начало недели (понедельник), без времени суток, обратимость."""

from datetime import date

from app.domain.multi_program import plan_week_number, plan_week_start_date


def test_same_day_is_week_1():
    assert plan_week_number(date(2026, 9, 21), date(2026, 9, 21)) == 1  # понедельник


def test_created_mid_week_still_week_1_until_next_monday():
    # Плана создан в четверг — до следующего понедельника всё ещё неделя 1.
    created = date(2026, 9, 17)  # четверг
    assert plan_week_number(created, date(2026, 9, 17)) == 1
    assert plan_week_number(created, date(2026, 9, 20)) == 1  # воскресенье той же недели


def test_next_monday_is_week_2():
    created = date(2026, 9, 17)  # четверг
    assert plan_week_number(created, date(2026, 9, 21)) == 2  # понедельник следующей недели


def test_week_number_grows_by_calendar_weeks_not_days():
    created = date(2026, 9, 21)  # понедельник
    assert plan_week_number(created, date(2026, 10, 5)) == 3  # +14 дней = +2 недели


def test_start_date_is_always_a_monday():
    created = date(2026, 9, 17)  # четверг
    start = plan_week_start_date(created, 1)
    assert start.weekday() == 0
    assert start == date(2026, 9, 14)


def test_week_number_and_start_date_are_inverse():
    created = date(2026, 9, 17)
    for week in range(1, 6):
        start = plan_week_start_date(created, week)
        assert plan_week_number(created, start) == week
        assert plan_week_number(created, start.replace(day=start.day)) == week
