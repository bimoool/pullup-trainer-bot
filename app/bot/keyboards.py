from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.bot import texts
from app.domain.electives import ElectiveType

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


def baseline_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="baseline_confirm")
    builder.button(text="✏️ Ввести заново", callback_data="baseline_reenter")
    builder.adjust(2)
    return builder.as_markup()


def gender_keyboard(back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.GENDER_LABEL_MALE, callback_data="gender:male")
    builder.button(text=texts.GENDER_LABEL_FEMALE, callback_data="gender:female")
    if back_callback is not None:
        builder.button(text="← Назад", callback_data=back_callback)
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def workout_section_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💪 Начать тренировку", callback_data="start_workout")
    builder.button(text="📋 Текущий план", callback_data="show_plan")
    builder.button(text="🔁 Внести пропущенную тренировку", callback_data="backdate_workout")
    builder.button(text="➕ Внести свободные подтягивания", callback_data="free_workout_start")
    builder.button(text=texts.ELECTIVE_MENU_BUTTON, callback_data="electives_start")
    builder.button(text="✏️ Изменить тренировку", callback_data="edit_workout_menu")
    builder.adjust(1)
    return builder.as_markup()


def electives_offer_keyboard() -> InlineKeyboardMarkup:
    """Кнопка предложения факультатива в TOO_EARLY (пакет #6) — тот же
    callback_data, что и в workout_section_keyboard, один общий хендлер
    (app/bot/handlers/electives.py::handle_electives_start)."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.TOO_EARLY_ELECTIVE_BUTTON, callback_data="electives_start")
    return builder.as_markup()


def elective_type_keyboard(available: frozenset[ElectiveType]) -> InlineKeyboardMarkup:
    _labels = {
        ElectiveType.MAX_REPS_LADDER: texts.ELECTIVE_LABEL_MAX_REPS_LADDER,
        ElectiveType.W_LADDER: texts.ELECTIVE_LABEL_W_LADDER,
        ElectiveType.THREE_MINUTES: texts.ELECTIVE_LABEL_THREE_MINUTES,
        ElectiveType.VOLUME_TARGET: texts.ELECTIVE_LABEL_VOLUME_TARGET,
    }
    builder = InlineKeyboardBuilder()
    # Порядок enum, не set (порядок множества не гарантирован) — стабильный
    # порядок кнопок между показами.
    for elective_type in ElectiveType:
        if elective_type in available:
            builder.button(text=_labels[elective_type], callback_data=f"elective:{elective_type.value}")
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


def progress_section_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 История тренировок", callback_data="show_history")
    builder.button(text="📅 Календарь", callback_data="show_calendar")
    builder.button(text="📊 Отчёт за неделю", callback_data="show_progress_report")
    builder.button(text="📈 Аналитика по всем циклам", callback_data="show_all_cycles_analytics")
    builder.button(text="⬇️ Экспорт в .xlsx", callback_data="export_xlsx")
    builder.adjust(1)
    return builder.as_markup()


_CALENDAR_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def calendar_keyboard(
    year: int, month: int, weeks: list[list[int]], marked_days: set[int], *, mode: str = "view",
) -> InlineKeyboardMarkup:
    """weeks — вывод calendar.monthcalendar(year, month) (недели с
    понедельника, 0 — день не в этом месяце). marked_days — числа месяца,
    в которые была хотя бы одна тренировка (или редактируемая — зависит от
    режима, см. вызывающий код).

    mode (Часть 10, пакет #2, п.16-17) — переиспользуемый компонент теперь
    открывается из трёх разных сценариев ("Прогресс" → "Календарь", ввод
    даты для бэкдейта, "Изменить тренировку"), зашивается в callback_data
    каждой кнопки, чтобы общие хендлеры (app/bot/handlers/history.py)
    знали, куда вести тап по дню/закрытию, не заводя три копии клавиатуры."""
    builder = InlineKeyboardBuilder()
    builder.row(*(InlineKeyboardButton(text=label, callback_data="noop") for label in _CALENDAR_WEEKDAY_LABELS))

    for week in weeks:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
                continue
            label = f"✅{day}" if day in marked_days else str(day)
            row.append(
                InlineKeyboardButton(text=label, callback_data=f"cal_day:{mode}:{year:04d}-{month:02d}-{day:02d}"),
            )
        builder.row(*row)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    builder.row(
        InlineKeyboardButton(text="◀️", callback_data=f"cal_month:{mode}:{prev_year:04d}-{prev_month:02d}"),
        InlineKeyboardButton(text=f"{year:04d}-{month:02d}", callback_data="noop"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_month:{mode}:{next_year:04d}-{next_month:02d}"),
    )
    # Кнопка выхода прямо в компоненте (Часть 10, пакет #2, п.16) — раньше
    # покинуть календарь можно было только тапом по другой кнопке нижнего
    # меню, что нелогично.
    builder.row(InlineKeyboardButton(text="✖️ Закрыть", callback_data=f"cal_close:{mode}"))
    return builder.as_markup()


def feedback_admin_reply_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Часть 10, п. 23 — под уведомлением админу о фидбеке: ведёт прямо в
    уже существующий флоу личного сообщения (admin.py::handle_admin_dm_start),
    отдельного механизма ответа заводить не нужно."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ Ответить", callback_data=f"admin_dm:{user_id}")
    return builder.as_markup()


def help_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.HELP_DETAILED_BUTTON, callback_data="help_detailed")
    builder.button(text="💬 Сообщить о проблеме", callback_data="report_problem")
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


def backdate_date_keyboard() -> InlineKeyboardMarkup:
    """Ввод даты бэкдейта — календарь ИЛИ текст, обе опции сразу (Часть 10,
    пакет #2, п.17), не одна вместо другой."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Открыть календарь", callback_data="backdate_open_calendar")
    builder.button(text="❌ Отмена", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


def anomaly_confirm_keyboard() -> InlineKeyboardMarkup:
    """Уточнение по подозрительно введённому результату (пакет #4) —
    callback_data одинаков для всех точек входа (живая тренировка/
    бэкдейт/правка/свободные подтягивания), гейтится конкретным
    FSM-состоянием на стороне каждого хендлера, см. app/domain/anomalies.py."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.ANOMALY_CONFIRM_BUTTON, callback_data="anomaly:confirm")
    builder.button(text=texts.ANOMALY_REENTER_BUTTON, callback_data="anomaly:reenter")
    builder.adjust(1)
    return builder.as_markup()


def bands_empty_offer_keyboard(*, yes_callback: str, no_callback: str) -> InlineKeyboardMarkup:
    """Пакет #5 — "Ещё нет резин, заведём? Как назовём" было одним
    сообщением, слитно спрашивающим два разных вопроса сразу. Явное
    да/нет здесь, имя — отдельным сообщением только после согласия."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.MY_BANDS_EMPTY_OFFER_YES_BUTTON, callback_data=yes_callback)
    builder.button(text=texts.MY_BANDS_EMPTY_OFFER_NO_BUTTON, callback_data=no_callback)
    builder.adjust(1)
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


def band_name_keyboard(back_callback: str | None) -> InlineKeyboardMarkup:
    """Ввод имени резины — та же пара "← Назад"/"❌ Отмена", что и
    back_cancel_keyboard, плюс справка по запросу (не показывается сама,
    чтобы не грузить тех, кому и так понятно — см. реальный пробел из
    фокус-группы: новичок без резины не понимает, где тренироваться и что
    покупать). back_callback=None — для отдельного захода "🎗 Мои резины",
    там нет предыдущего шага в этом сценарии."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.EQUIPMENT_BAND_HELP_BUTTON, callback_data="band_name_help")
    if back_callback is not None:
        builder.button(text="← Назад", callback_data=back_callback)
        builder.button(text="❌ Отмена", callback_data="cancel_flow")
        builder.adjust(1, 2)
    else:
        builder.button(text="❌ Отмена", callback_data="cancel_flow")
        builder.adjust(1, 1)
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
    вверх/вниз у каждого пункта, свап с соседом за один тап.

    "➕ Добавить резину" (Часть 10, п. 22) — заводить снаряд заранее, не
    только по ходу тренировки; показывается всегда, даже при пустом списке."""
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
    builder.row(InlineKeyboardButton(text="➕ Добавить резину", callback_data="band_add_standalone"))
    builder.row(InlineKeyboardButton(text="✅ Готово", callback_data="band_reorder_done"))
    return builder.as_markup()


def optional_exercise_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.OPTIONAL_EXERCISE_WANT_BUTTON, callback_data="optional_exercise:want")
    builder.button(text=texts.OPTIONAL_EXERCISE_SKIP_BUTTON, callback_data="optional_exercise:skip")
    builder.adjust(2)
    return builder.as_markup()


def warmup_reminder_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.WARMUP_SHOW_BUTTON, callback_data="warmup:show")
    return builder.as_markup()


def edit_equipment_weight_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.EDIT_EQUIPMENT_SKIP, callback_data="edit_equipment_skip")
    return builder.as_markup()


def edit_equipment_band_keyboard(items: list) -> InlineKeyboardMarkup:
    """items — EquipmentItem пользователя. Без "Добавить новую" (в отличие
    от band_item_picker_keyboard) — это точечная правка ошибки ввода в уже
    записанной тренировке, не подбор нового снаряда."""
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=item.name, callback_data=f"edit_band_item:{item.id}")
    builder.button(text=texts.EDIT_EQUIPMENT_SKIP, callback_data="edit_equipment_skip")
    builder.adjust(1)
    return builder.as_markup()


def edit_workout_picker_keyboard(workouts: list, *, label_format: str = "%d.%m.%Y") -> InlineKeyboardMarkup:
    """workouts — Workout ORM-объекты (не импортируем тип напрямую, чтобы
    не тянуть app.db.models в клавиатурный модуль лишний раз); нужны только
    .id и .performed_at. Основной вход "Изменить тренировку" теперь ведёт
    через календарь (Часть 10, пакет #2, п.17) — этот список остался только
    для редкого случая нескольких редактируемых тренировок за один день
    (label_format="%H:%M", даты у всех в списке одинаковые)."""
    builder = InlineKeyboardBuilder()
    for workout in reversed(workouts):
        builder.button(text=workout.performed_at.strftime(label_format), callback_data=f"edit_pick:{workout.id}")
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
    builder.button(text="✏️ Изменить профиль", callback_data="profile_edit_open")
    builder.button(text="🎗 Мои резины", callback_data="equipment_list_open")
    builder.button(text="🔄 Завершить цикл и начать заново", callback_data="end_cycle_prompt")
    if is_admin:
        builder.button(text="🧪 Полный сброс (админ)", callback_data="admin_reset_prompt")
    builder.adjust(1)
    return builder.as_markup()


def profile_edit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.PROFILE_EDIT_BUTTON_WEIGHT, callback_data="profile_edit:weight")
    builder.button(text=texts.PROFILE_EDIT_BUTTON_HEIGHT, callback_data="profile_edit:height")
    builder.button(text=texts.PROFILE_EDIT_BUTTON_GENDER, callback_data="profile_edit:gender")
    builder.button(text=texts.PROFILE_EDIT_BUTTON_BIRTH_DATE, callback_data="profile_edit:birth_date")
    builder.button(text=texts.PROFILE_EDIT_BUTTON_TIMEZONE, callback_data="profile_edit:timezone")
    builder.button(text="← Назад", callback_data="profile_edit_close")
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
