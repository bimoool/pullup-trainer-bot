from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

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

# Постоянное нижнее меню — 4 раздела (см. Часть 3 респека). /admin сюда
# намеренно не входит — админка доступна только по команде, не кнопкой.
BOTTOM_MENU_WORKOUT = "💪 Тренировка"
BOTTOM_MENU_PROGRESS = "📊 Прогресс"
BOTTOM_MENU_PROFILE = "👤 Профиль"
BOTTOM_MENU_HELP = "❓ Помощь"


def bottom_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=BOTTOM_MENU_WORKOUT), KeyboardButton(text=BOTTOM_MENU_PROGRESS))
    builder.row(KeyboardButton(text=BOTTOM_MENU_PROFILE), KeyboardButton(text=BOTTOM_MENU_HELP))
    return builder.as_markup(resize_keyboard=True)


def timezone_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, iana_name in TIMEZONE_CHOICES:
        builder.button(text=label, callback_data=f"tz:{iana_name}")
    builder.adjust(1)
    return builder.as_markup()


def workout_section_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💪 Начать тренировку", callback_data="start_workout")
    builder.button(text="📋 Текущий план", callback_data="show_plan")
    builder.button(text="🔁 Внести пропущенную тренировку", callback_data="backdate_workout")
    builder.button(text="✏️ Изменить тренировку", callback_data="edit_workout_menu")
    builder.adjust(1)
    return builder.as_markup()


def progress_section_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 История тренировок", callback_data="show_history")
    builder.button(text="📊 Отчёт за неделю", callback_data="show_progress_report")
    builder.button(text="⬇️ Экспорт в .xlsx", callback_data="export_xlsx")
    builder.adjust(1)
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены текущего сценария — добавляется ко всем состояниям
    ввода, у которых нет осмысленного "предыдущего шага" (например, первый
    вопрос анкеты), чтобы пользователь не застревал без выхода (см.
    критический баг Части 2)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    return builder.as_markup()


def back_cancel_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    """"← Назад" возвращает к предыдущему шагу того же сценария (не
    восстанавливает то, что там было введено — просто переспрашивает),
    "❌ Отмена" выходит из сценария целиком — см. Часть 3 респека."""
    builder = InlineKeyboardBuilder()
    builder.button(text="← Назад", callback_data=back_callback)
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(2)
    return builder.as_markup()


def skip_comment_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить", callback_data="skip_comment")
    builder.button(text="← Назад", callback_data=back_callback)
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1, 2)
    return builder.as_markup()


def equipment_type_keyboard(back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, value in EQUIPMENT_TYPE_CHOICES:
        builder.button(text=label, callback_data=f"equip:{value}")
    if back_callback is not None:
        builder.button(text="← Назад", callback_data=back_callback)
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


def edit_workout_picker_keyboard(workouts: list) -> InlineKeyboardMarkup:
    """workouts — Workout ORM-объекты (не импортируем тип напрямую, чтобы
    не тянуть app.db.models в клавиатурный модуль лишний раз); нужны только
    .id и .performed_at."""
    builder = InlineKeyboardBuilder()
    for workout in reversed(workouts):
        builder.button(text=workout.performed_at.strftime("%d.%m.%Y"), callback_data=f"edit_pick:{workout.id}")
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
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
