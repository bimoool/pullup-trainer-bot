from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
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

# callback_data этих кнопок обязаны совпадать со значениями EquipmentType —
# хендлер разбирает "equip:<value>" напрямую через EquipmentType(value).
# Выбор типа снаряда должен быть явным всегда (Часть 8 респека) — раньше
# "0" в поле числа означало "без резины", это путало пользователей.
EQUIPMENT_TYPE_CHOICES: list[tuple[str, str]] = [
    ("Резина", "band"),
    ("Свой вес", "bodyweight"),
    ("Отягощение", "weight"),
    ("Австралийские", "australian"),
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


def baseline_start_keyboard() -> InlineKeyboardMarkup:
    """Явная кнопка-CTA под последним сообщением онбординга — раньше три
    сообщения подряд заканчивались без единой кнопки, и человек должен был
    сам догадаться, что от него ждут числа в чат (тот же тупиковый паттерн,
    что уже чинили в других местах, см. Часть 2)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Начать замер →", callback_data="start_baseline_measurement")
    return builder.as_markup()


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
    builder.button(text="📈 Аналитика по всем циклам", callback_data="show_all_cycles_analytics")
    builder.button(text="⬇️ Экспорт в .xlsx", callback_data="export_xlsx")
    builder.adjust(1)
    return builder.as_markup()


def help_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Сообщить о проблеме", callback_data="report_problem")
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


def band_item_picker_keyboard(items: list, back_callback: str) -> InlineKeyboardMarkup:
    """items — EquipmentItem ORM-объекты пользователя, уже в порядке
    position (см. EquipmentItemRepository.list_for_user). "Добавить новую"
    — всегда последней кнопкой перед навигацией (Часть 8: список растёт по
    мере надобности, не предзаполняется)."""
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=item.name, callback_data=f"band_item:{item.id}")
    builder.button(text="➕ Добавить новую резину", callback_data="band_item:new")
    builder.button(text="← Назад", callback_data=back_callback)
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


def equipment_kg_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    """Кг резины — необязательное поле (в залах резины часто без
    маркировки), поэтому кнопка "Пропустить" рядом с обычной навигацией."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить", callback_data="skip_item_kg")
    builder.button(text="← Назад", callback_data=back_callback)
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1, 2)
    return builder.as_markup()


def band_reorder_keyboard(items: list) -> InlineKeyboardMarkup:
    """Реордер личного списка резин — порядок (не кг) определяет "следующий
    снаряд" при переходах (Часть 8), поэтому пользователь должен уметь его
    менять. Telegram не даёт drag-and-drop, поэтому реордер — стрелки
    вверх/вниз у каждого пункта, свап с соседом за один тап."""
    builder = InlineKeyboardBuilder()
    for index, item in enumerate(items):
        builder.row(InlineKeyboardButton(text=f"{index + 1}. {item.name}", callback_data="noop"))
        row = []
        if index > 0:
            row.append(InlineKeyboardButton(text="⬆️", callback_data=f"band_move:{item.id}:up"))
        if index < len(items) - 1:
            row.append(InlineKeyboardButton(text="⬇️", callback_data=f"band_move:{item.id}:down"))
        if row:
            builder.row(*row)
    builder.row(InlineKeyboardButton(text="✅ Готово", callback_data="band_reorder_done"))
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


def admin_menu_keyboard(sheet_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Воронка", callback_data="admin_funnel")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="📢 Рассылка всем", callback_data="admin_broadcast")
    if sheet_url:
        builder.button(text="📈 Google-таблица", url=sheet_url)
    builder.adjust(1)
    return builder.as_markup()


def admin_user_list_keyboard(users: list) -> InlineKeyboardMarkup:
    """users — User ORM-объекты, нужны только .id/.username/.telegram_id."""
    builder = InlineKeyboardBuilder()
    for user in users:
        label = f"@{user.username}" if user.username else f"id {user.telegram_id}"
        builder.button(text=label, callback_data=f"admin_user:{user.id}")
    builder.button(text="← Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_user_card_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ Написать", callback_data=f"admin_dm:{user_id}")
    builder.button(text="🎁 Выдать подписку", callback_data=f"admin_grant_days:{user_id}")
    builder.button(text="🪙 Начислить монеты", callback_data=f"admin_grant_coins:{user_id}")
    builder.button(text="← К списку", callback_data="admin_users")
    builder.adjust(1)
    return builder.as_markup()


def profile_keyboard(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎗 Мои резины", callback_data="equipment_list_open")
    builder.button(text="🔄 Завершить цикл и начать заново", callback_data="end_cycle_prompt")
    if is_admin:
        builder.button(text="🧪 Полный сброс (админ)", callback_data="admin_reset_prompt")
    builder.adjust(1)
    return builder.as_markup()


def admin_reset_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="admin_reset_confirm")
    builder.button(text="❌ Отмена", callback_data="admin_reset_cancel")
    builder.adjust(2)
    return builder.as_markup()


def end_cycle_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="end_cycle_confirm")
    builder.button(text="❌ Отмена", callback_data="end_cycle_cancel")
    builder.adjust(2)
    return builder.as_markup()
