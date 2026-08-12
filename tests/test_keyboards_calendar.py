"""calendar_keyboard() — сетка месяца для "📅 Календарь" (Часть 10, п. 26).
Чистая функция, без БД/бота — юнит-тест на структуру клавиатуры."""

import calendar

from app.bot.keyboards import calendar_keyboard


def test_weekday_header_row_is_first_and_noop():
    weeks = calendar.monthcalendar(2026, 8)
    markup = calendar_keyboard(2026, 8, weeks, marked_days=set())

    header_row = markup.inline_keyboard[0]
    assert [button.text for button in header_row] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    assert all(button.callback_data == "noop" for button in header_row)


def test_empty_padding_cells_are_noop():
    # Август 2026 начинается в субботу — перед 1-м числом есть пустые клетки
    weeks = calendar.monthcalendar(2026, 8)
    markup = calendar_keyboard(2026, 8, weeks, marked_days=set())

    first_week_row = markup.inline_keyboard[1]
    padding_buttons = [b for b, day in zip(first_week_row, weeks[0], strict=True) if day == 0]
    assert padding_buttons  # у августа 2026 реально есть отступ в первой неделе
    assert all(button.callback_data == "noop" for button in padding_buttons)


def test_marked_day_gets_checkmark_prefix_and_real_callback():
    weeks = calendar.monthcalendar(2026, 8)
    markup = calendar_keyboard(2026, 8, weeks, marked_days={5})

    # [1:-2] — без строки дней недели, строки навигации и строки закрытия
    day_buttons = {
        button.callback_data.removeprefix("cal_day:view:"): button.text
        for row in markup.inline_keyboard[1:-2]
        for button in row
        if button.callback_data.startswith("cal_day:")
    }
    assert day_buttons["2026-08-05"] == "✅5"
    assert day_buttons["2026-08-06"] == "6"  # не отмечен — без чекмарка


def test_navigation_row_wraps_month_correctly():
    weeks = calendar.monthcalendar(2026, 8)
    markup = calendar_keyboard(2026, 8, weeks, marked_days=set())

    nav_row = markup.inline_keyboard[-2]
    assert [b.callback_data for b in nav_row] == ["cal_month:view:2026-07", "noop", "cal_month:view:2026-09"]


def test_navigation_wraps_across_year_boundary_forward():
    weeks = calendar.monthcalendar(2026, 12)
    markup = calendar_keyboard(2026, 12, weeks, marked_days=set())

    nav_row = markup.inline_keyboard[-2]
    assert nav_row[0].callback_data == "cal_month:view:2026-11"
    assert nav_row[2].callback_data == "cal_month:view:2027-01"


def test_navigation_wraps_across_year_boundary_backward():
    weeks = calendar.monthcalendar(2026, 1)
    markup = calendar_keyboard(2026, 1, weeks, marked_days=set())

    nav_row = markup.inline_keyboard[-2]
    assert nav_row[0].callback_data == "cal_month:view:2025-12"
    assert nav_row[2].callback_data == "cal_month:view:2026-02"


def test_close_button_is_last_row_and_carries_mode():
    # Часть 10, пакет #2, п.16 — кнопка выхода прямо в компоненте.
    weeks = calendar.monthcalendar(2026, 8)
    markup = calendar_keyboard(2026, 8, weeks, marked_days=set(), mode="backdate")

    close_row = markup.inline_keyboard[-1]
    assert len(close_row) == 1
    assert close_row[0].callback_data == "cal_close:backdate"


def test_mode_propagates_into_day_and_month_callbacks():
    weeks = calendar.monthcalendar(2026, 8)
    markup = calendar_keyboard(2026, 8, weeks, marked_days=set(), mode="edit")

    nav_row = markup.inline_keyboard[-2]
    assert nav_row[0].callback_data == "cal_month:edit:2026-07"

    day_buttons = [
        button.callback_data
        for row in markup.inline_keyboard[1:-2]
        for button in row
        if button.callback_data.startswith("cal_day:")
    ]
    assert all(cb.startswith("cal_day:edit:") for cb in day_buttons)
