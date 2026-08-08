from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Часовой пояс выбирается кнопкой из фиксированного списка, а не парсингом
# свободного текста ("напиши город") — без города-в-IANA-таймзону словаря
# (и его неизбежных дыр на редких городах/опечатках) это надёжнее.
# Один город-ориентир на каждый часовой пояс РФ (UTC+2..UTC+12).
TIMEZONE_CHOICES: list[tuple[str, str]] = [
    ("Калининград (UTC+2)", "Europe/Kaliningrad"),
    ("Москва (UTC+3)", "Europe/Moscow"),
    ("Самара (UTC+4)", "Europe/Samara"),
    ("Екатеринбург (UTC+5)", "Asia/Yekaterinburg"),
    ("Омск (UTC+6)", "Asia/Omsk"),
    ("Красноярск (UTC+7)", "Asia/Krasnoyarsk"),
    ("Иркутск (UTC+8)", "Asia/Irkutsk"),
    ("Якутск (UTC+9)", "Asia/Yakutsk"),
    ("Владивосток (UTC+10)", "Asia/Vladivostok"),
    ("Магадан (UTC+11)", "Asia/Magadan"),
    ("Камчатка (UTC+12)", "Asia/Kamchatsky"),
]


def timezone_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, iana_name in TIMEZONE_CHOICES:
        builder.button(text=label, callback_data=f"tz:{iana_name}")
    builder.adjust(1)
    return builder.as_markup()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💪 Начать тренировку", callback_data="start_workout")
    builder.button(text="📖 История", callback_data="show_history")
    builder.button(text="🔁 Внести пропущенную тренировку", callback_data="backdate_workout")
    builder.adjust(1)
    return builder.as_markup()


def workout_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить результат", callback_data="edit_last_workout")
    builder.adjust(1)
    return builder.as_markup()


def paywall_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Оплатить Stars", callback_data="pay_stars")
    builder.button(text="💳 Оплатить картой", callback_data="pay_tribute")
    builder.adjust(1)
    return builder.as_markup()


def payment_link_keyboard(url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Перейти к оплате", url=url)
    return builder.as_markup()
