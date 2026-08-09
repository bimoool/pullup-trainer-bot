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

# callback_data этих трёх кнопок обязаны совпадать со значениями EquipmentType
# (band/bodyweight/weight) — хендлер разбирает "equip:<value>" напрямую через
# EquipmentType(value). AUSTRALIAN сюда намеренно не входит — see
# to_signed_load(), для него нет числовой шкалы, поддержка отложена.
EQUIPMENT_TYPE_CHOICES: list[tuple[str, str]] = [
    ("Резина", "band"),
    ("Свой вес", "bodyweight"),
    ("Отягощение", "weight"),
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


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены текущего сценария — добавляется ко всем состояниям
    ввода (тренировка, анкета, снаряд, бэкдейт, редактирование), чтобы
    пользователь не застревал без выхода (см. критический баг Части 2)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    return builder.as_markup()


def skip_comment_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить", callback_data="skip_comment")
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


def equipment_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, value in EQUIPMENT_TYPE_CHOICES:
        builder.button(text=label, callback_data=f"equip:{value}")
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


def workout_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить результат", callback_data="edit_last_workout")
    builder.adjust(1)
    return builder.as_markup()


def after_history_keyboard() -> InlineKeyboardMarkup:
    """История раньше заканчивалась тупиком — без единой кнопки дальше.
    Возвращаем в главное меню, чтобы диалог не обрывался."""
    return main_menu_keyboard()


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
