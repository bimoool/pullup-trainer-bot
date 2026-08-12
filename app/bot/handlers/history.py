import calendar
from collections.abc import Callable
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_kg
from app.bot.keyboards import bottom_menu_keyboard, calendar_keyboard, progress_section_keyboard
from app.db.models import Block, BlockType, EquipmentType, Workout
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository

router = Router()

HISTORY_LIMIT = 10

_MONTH_NAMES_RU = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)

_EQUIPMENT_LABELS = {
    EquipmentType.BAND: "резина",
    EquipmentType.BODYWEIGHT: "свой вес",
    EquipmentType.WEIGHT: "отягощение",
    EquipmentType.AUSTRALIAN: "австралийские",
}


def _format_equipment(block: Block) -> str:
    label = _EQUIPMENT_LABELS[block.equipment_type]
    if block.equipment_value is None:
        return label
    return f"{label} {format_kg(block.equipment_value)} кг"


def format_history_entry(workout: Workout, *, is_latest: bool = True) -> str:
    """Один читаемый блок на тренировку — переиспользуется списком истории
    и деталями дня в календаре (Часть 10, п. 26: "тап по дню показывает
    детали в существующем формате истории").

    is_latest=False (Часть 10, пакет #2, п.15) — "следующая цель" убирается
    из более ранних записей: это число становится неактуальным после
    следующей тренировки и вводит в заблуждение, особенно когда за один
    день записано несколько тренировок подряд (например, задним числом)."""
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    comment = texts.HISTORY_COMMENT_LINE.format(comment=workout.comment) if workout.comment else ""
    date = workout.performed_at.strftime("%d.%m.%Y")
    backdated_mark = texts.HISTORY_BACKDATED_MARK if not workout.participates_in_cascade else ""

    if is_latest:
        return texts.HISTORY_ENTRY.format(
            date=date, backdated_mark=backdated_mark,
            equipment_a=_format_equipment(block_a), max_a=block_a.max_reps, target_a=block_a.target_after,
            equipment_b=_format_equipment(block_b), max_b=block_b.max_reps, target_b=block_b.target_after,
            comment=comment,
        )
    return texts.HISTORY_ENTRY_NO_TARGET.format(
        date=date, backdated_mark=backdated_mark,
        equipment_a=_format_equipment(block_a), max_a=block_a.max_reps,
        equipment_b=_format_equipment(block_b), max_b=block_b.max_reps,
        comment=comment,
    )


@router.callback_query(F.data == "show_history")
async def handle_show_history(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)

    if not history:
        await callback.message.answer(texts.HISTORY_EMPTY, reply_markup=progress_section_keyboard())
        await callback.answer()
        return

    shown = history[-HISTORY_LIMIT:]
    entries = [format_history_entry(workout, is_latest=workout is history[-1]) for workout in shown]
    await callback.message.answer("\n\n".join(entries), reply_markup=progress_section_keyboard())
    await callback.answer()


async def render_calendar_month(
    callback: CallbackQuery, session: AsyncSession, *, year: int, month: int, edit: bool,
    mode: str = "view", history_filter: Callable[[Workout], bool] | None = None,
) -> None:
    """Переиспользуемый рендер сетки месяца (Часть 10, пакет #2, п.16-17) —
    публичная, вызывается и из backdate.py/workout_edit.py, не только
    отсюда. history_filter — какие тренировки считаются "отмеченными"
    (по умолчанию любая; режим "edit" передаёт только редактируемые —
    иначе навигация по календарю вела бы на дни, где нечего редактировать)."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    marked_source = [w for w in history if history_filter(w)] if history_filter is not None else history
    marked_days = {
        w.performed_at.date().day for w in marked_source
        if w.performed_at.year == year and w.performed_at.month == month
    }

    weeks = calendar.monthcalendar(year, month)
    header = texts.CALENDAR_HEADER.format(month_name=_MONTH_NAMES_RU[month - 1], year=year)
    keyboard = calendar_keyboard(year, month, weeks, marked_days, mode=mode)

    if edit:
        await callback.message.edit_text(header, reply_markup=keyboard)
    else:
        await callback.message.answer(header, reply_markup=keyboard)


@router.callback_query(F.data == "show_calendar")
async def handle_show_calendar(callback: CallbackQuery, session: AsyncSession) -> None:
    now = datetime.now(UTC)
    # Открывается новым сообщением — предыдущее (меню "Прогресс") не сетка
    # календаря, редактировать нечего.
    await render_calendar_month(callback, session, year=now.year, month=now.month, edit=False, mode="view")
    await callback.answer()


@router.callback_query(F.data.startswith("cal_month:"))
async def handle_calendar_month_nav(callback: CallbackQuery, session: AsyncSession) -> None:
    # ◀️/▶️ жмут по уже открытой сетке — редактируем её же (Часть 10, п. 12:
    # не плодить новое сообщение на каждое переключение месяца).
    mode, date_part = callback.data.removeprefix("cal_month:").split(":", 1)
    year_str, month_str = date_part.split("-")

    history_filter = None
    if mode == "edit":
        from app.bot.handlers.workout_edit import (
            _is_editable,  # деферред — см. комментарий выше про циклы импортов
        )
        history_filter = _is_editable

    await render_calendar_month(
        callback, session, year=int(year_str), month=int(month_str), edit=True,
        mode=mode, history_filter=history_filter,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cal_day:"))
async def handle_calendar_day(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    mode, date_part = callback.data.removeprefix("cal_day:").split(":", 1)
    year, month, day = (int(part) for part in date_part.split("-"))
    picked_date = datetime(year, month, day, tzinfo=UTC).date()

    if mode == "backdate":
        # Деферред-импорт — history.py и backdate.py взаимно переиспользуют
        # функции друг друга (render_calendar_month / обработка выбора
        # дня), прямой импорт на верхнем уровне зациклился бы.
        from app.bot.handlers.backdate import handle_calendar_date_picked

        await handle_calendar_date_picked(callback, state, picked_date)
        return

    if mode == "edit":
        from app.bot.handlers.workout_edit import handle_calendar_workout_picked

        await handle_calendar_workout_picked(callback, session, state, picked_date)
        return

    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    day_workouts = [w for w in history if w.performed_at.date() == picked_date]

    if not day_workouts:
        await callback.answer(texts.CALENDAR_NO_WORKOUT_TOAST, show_alert=True)
        return

    latest = history[-1] if history else None
    entries = [format_history_entry(workout, is_latest=workout is latest) for workout in day_workouts]
    await callback.message.answer("\n\n".join(entries))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_close:"))
async def handle_calendar_close(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка выхода прямо в компоненте (Часть 10, пакет #2, п.16) — режим
    "view" ни от чего не отменяет (у экрана истории нет FSM-состояния),
    для "backdate"/"edit" — полноценная отмена сценария, тот же паттерн,
    что и у остальных кнопок "Отмена" в боте."""
    mode = callback.data.removeprefix("cal_close:")
    if mode == "view":
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        return

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.CANCELLED)
    await callback.message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard())
    await callback.answer()
