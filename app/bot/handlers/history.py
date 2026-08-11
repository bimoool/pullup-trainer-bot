import calendar
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_kg
from app.bot.keyboards import calendar_keyboard, progress_section_keyboard
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


def format_history_entry(workout: Workout) -> str:
    """Один читаемый блок на тренировку — переиспользуется списком истории
    и деталями дня в календаре (Часть 10, п. 26: "тап по дню показывает
    детали в существующем формате истории")."""
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    comment = texts.HISTORY_COMMENT_LINE.format(comment=workout.comment) if workout.comment else ""
    return texts.HISTORY_ENTRY.format(
        date=workout.performed_at.strftime("%d.%m.%Y"),
        backdated_mark=texts.HISTORY_BACKDATED_MARK if not workout.participates_in_cascade else "",
        equipment_a=_format_equipment(block_a), max_a=block_a.max_reps, target_a=block_a.target_after,
        equipment_b=_format_equipment(block_b), max_b=block_b.max_reps, target_b=block_b.target_after,
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

    entries = [format_history_entry(workout) for workout in history[-HISTORY_LIMIT:]]
    await callback.message.answer("\n\n".join(entries), reply_markup=progress_section_keyboard())
    await callback.answer()


async def _render_calendar_month(
    callback: CallbackQuery, session: AsyncSession, *, year: int, month: int, edit: bool,
) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    marked_days = {
        w.performed_at.date().day for w in history
        if w.performed_at.year == year and w.performed_at.month == month
    }

    weeks = calendar.monthcalendar(year, month)
    header = texts.CALENDAR_HEADER.format(month_name=_MONTH_NAMES_RU[month - 1], year=year)
    keyboard = calendar_keyboard(year, month, weeks, marked_days)

    if edit:
        await callback.message.edit_text(header, reply_markup=keyboard)
    else:
        await callback.message.answer(header, reply_markup=keyboard)


@router.callback_query(F.data == "show_calendar")
async def handle_show_calendar(callback: CallbackQuery, session: AsyncSession) -> None:
    now = datetime.now(UTC)
    # Открывается новым сообщением — предыдущее (меню "Прогресс") не сетка
    # календаря, редактировать нечего.
    await _render_calendar_month(callback, session, year=now.year, month=now.month, edit=False)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_month:"))
async def handle_calendar_month_nav(callback: CallbackQuery, session: AsyncSession) -> None:
    # ◀️/▶️ жмут по уже открытой сетке — редактируем её же (Часть 10, п. 12:
    # не плодить новое сообщение на каждое переключение месяца).
    year_str, month_str = callback.data.removeprefix("cal_month:").split("-")
    await _render_calendar_month(callback, session, year=int(year_str), month=int(month_str), edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_day:"))
async def handle_calendar_day(callback: CallbackQuery, session: AsyncSession) -> None:
    day_str = callback.data.removeprefix("cal_day:")
    year, month, day = (int(part) for part in day_str.split("-"))

    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    day_workouts = [
        w for w in history
        if w.performed_at.year == year and w.performed_at.month == month and w.performed_at.day == day
    ]

    if not day_workouts:
        await callback.answer(texts.CALENDAR_NO_WORKOUT_TOAST, show_alert=True)
        return

    entries = [format_history_entry(workout) for workout in day_workouts]
    await callback.message.answer("\n\n".join(entries))
    await callback.answer()
