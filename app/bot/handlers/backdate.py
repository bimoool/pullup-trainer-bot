from datetime import UTC, date, datetime
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_reps_example
from app.bot.handlers.equipment import _begin_equipment_setup
from app.bot.handlers.workout import _ensure_active_workout_set
from app.bot.keyboards import back_cancel_keyboard, backdate_date_keyboard, bottom_menu_keyboard
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import BackdateStates
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService

router = Router()


@router.callback_query(F.data == "backdate_workout")
async def handle_backdate_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    # Текущие цели считаются один раз здесь и кладутся в FSM — используются
    # только как пример формата ввода на следующих шагах (Часть 10, пакет
    # #2, п.10), не как реальная цель ЭТОЙ конкретной прошлой тренировки.
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    target_a_state, target_b_state = await WorkoutRepository(session).resolve_next_targets(user.id)

    await state.set_state(BackdateStates.waiting_for_date)
    await state.update_data(target_a=target_a_state.target, target_b=target_b_state.target)
    await callback.message.answer(texts.BACKDATE_INTRO)
    await callback.message.answer(texts.BACKDATE_DATE_PROMPT, reply_markup=backdate_date_keyboard())
    await callback.answer()


@router.callback_query(F.data == "backdate_open_calendar")
async def handle_backdate_open_calendar(callback: CallbackQuery, session: AsyncSession) -> None:
    from app.bot.handlers.history import (
        render_calendar_month,  # деферред — см. комментарий в history.py
    )

    now = datetime.now(UTC)
    await render_calendar_month(callback, session, year=now.year, month=now.month, edit=False, mode="backdate")
    await callback.answer()


async def _proceed_with_backdate_date(message: Message, state: FSMContext, parsed_date: datetime) -> None:
    """Общий хвост после того, как дата бэкдейта известна и уже проверена
    (не будущая) — не важно, пришла она текстом (handle_backdate_date) или
    тапом по календарю (handle_calendar_date_picked, Часть 10, пакет #2,
    п.17): дальше сценарий один и тот же."""
    data = await state.get_data()
    await state.update_data(backdate_performed_at=parsed_date.isoformat())
    await state.set_state(BackdateStates.waiting_for_block_a)
    example_a = format_reps_example(data["target_a"], VOLUME_BLOCK.work_sets)
    await message.answer(
        texts.BLOCK_A_PROMPT.format(example=example_a), reply_markup=back_cancel_keyboard("backdate_back:date"),
    )


@router.message(BackdateStates.waiting_for_date)
async def handle_backdate_date(message: Message, state: FSMContext) -> None:
    try:
        parsed_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").replace(tzinfo=UTC)
    except ValueError:
        await message.answer(texts.BACKDATE_DATE_INVALID)
        return

    if parsed_date.date() > datetime.now(UTC).date():
        await message.answer(texts.BACKDATE_FUTURE_DATE)
        return

    await _proceed_with_backdate_date(message, state, parsed_date)


async def handle_calendar_date_picked(callback: CallbackQuery, state: FSMContext, picked_date: date) -> None:
    """Вызывается из history.py при тапе по дню в режиме "backdate" (Часть
    10, пакет #2, п.17) — та же проверка и переход, что при ручном вводе
    даты текстом (см. _proceed_with_backdate_date), источник даты другой."""
    if picked_date > datetime.now(UTC).date():
        await callback.answer(texts.BACKDATE_FUTURE_DATE, show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    parsed_date = datetime(picked_date.year, picked_date.month, picked_date.day, tzinfo=UTC)
    await _proceed_with_backdate_date(callback.message, state, parsed_date)
    await callback.answer()


@router.callback_query(F.data == "backdate_back:date")
async def handle_backdate_back_to_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackdateStates.waiting_for_date)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.BACKDATE_DATE_PROMPT, reply_markup=backdate_date_keyboard())
    await callback.answer()


@router.message(BackdateStates.waiting_for_block_a)
async def handle_backdate_block_a(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", VOLUME_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()
    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(BackdateStates.waiting_for_block_b)
    example_b = format_reps_example(data["target_b"], STRENGTH_BLOCK.work_sets)
    await message.answer(
        texts.BLOCK_B_PROMPT.format(example=example_b), reply_markup=back_cancel_keyboard("backdate_back:block_a"),
    )


@router.callback_query(F.data == "backdate_back:block_a")
async def handle_backdate_back_to_block_a(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(BackdateStates.waiting_for_block_a)
    await callback.message.edit_reply_markup(reply_markup=None)
    example_a = format_reps_example(data["target_a"], VOLUME_BLOCK.work_sets)
    await callback.message.answer(
        texts.BLOCK_A_PROMPT.format(example=example_a), reply_markup=back_cancel_keyboard("backdate_back:date"),
    )
    await callback.answer()


@router.message(BackdateStates.waiting_for_block_b)
async def handle_backdate_block_b(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_block_result(message.text or "", STRENGTH_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()

    # Снаряд на момент прошлой (пропущенной) тренировки теперь спрашивается
    # явно, той же очередью, что и в живой тренировке (Часть 8) — раньше
    # тихо наследовался последний известный, что путало пользователей,
    # которые реально меняли снаряд между тренировками.
    await _begin_equipment_setup(
        message, state, session,
        flow="backdate",
        target_a_state=None, target_b_state=None,
        telegram_id=message.from_user.id,
        baseline_reps=None,
        extra_data={
            "backdate_performed_at": data["backdate_performed_at"],
            "block_a_working_reps": data["block_a_working_reps"],
            "block_a_max_reps": data["block_a_max_reps"],
            "block_b_working_reps": list(result.working_reps),
            "block_b_max_reps": result.max_reps,
        },
    )


async def finalize_backdated_workout(
    message: Message, state: FSMContext, session: AsyncSession, data: dict, *, telegram_id: int,
) -> None:
    """Вызывается из equipment.py, когда очередь снаряда для бэкдейта
    опустела (см. _complete_equipment_queue) — здесь уже есть и повторения
    обоих блоков, и выбранный снаряд, можно записывать.

    telegram_id передаётся явно от исходного вызова _begin_equipment_setup
    (см. комментарий там) — message здесь почти всегда callback.message
    (последний шаг очереди снаряда почти всегда завершается кнопкой), а у
    него from_user — бот, не пользователь."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)

    active_set = await _ensure_active_workout_set(session, user.id)
    if active_set is None:
        await message.answer(texts.NO_ACTIVE_SET_SUPPORT)
        await state.clear()
        return

    equipment_results = data["equipment_results"]
    block_a_equipment_type = EquipmentType(equipment_results["a"]["type"])
    block_a_equipment_value = Decimal(equipment_results["a"]["value"]) if equipment_results["a"]["value"] else None
    block_a_equipment_item_id = equipment_results["a"]["item_id"]
    block_b_equipment_type = EquipmentType(equipment_results["b"]["type"])
    block_b_equipment_value = Decimal(equipment_results["b"]["value"]) if equipment_results["b"]["value"] else None
    block_b_equipment_item_id = equipment_results["b"]["item_id"]

    block_a_reps = BlockLog(working_reps=tuple(data["block_a_working_reps"]), max_reps=data["block_a_max_reps"])
    block_b_reps = BlockLog(working_reps=tuple(data["block_b_working_reps"]), max_reps=data["block_b_max_reps"])
    performed_at = datetime.fromisoformat(data["backdate_performed_at"])

    log_service = WorkoutLogService(session)
    await log_service.record_backdated_workout(
        user_id=user.id,
        workout_set_id=active_set.id,
        performed_at=performed_at,
        block_a_reps=block_a_reps,
        block_b_reps=block_b_reps,
        block_a_equipment_type=block_a_equipment_type,
        block_a_equipment_value=block_a_equipment_value,
        block_b_equipment_type=block_b_equipment_type,
        block_b_equipment_value=block_b_equipment_value,
        block_a_equipment_item_id=block_a_equipment_item_id,
        block_b_equipment_item_id=block_b_equipment_item_id,
    )

    await state.clear()
    await message.answer(texts.BACKDATE_DONE)
    await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard())
