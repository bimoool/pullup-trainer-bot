from datetime import UTC, datetime
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.handlers.equipment import _begin_equipment_setup
from app.bot.handlers.workout import _ensure_active_workout_set
from app.bot.keyboards import back_cancel_keyboard, bottom_menu_keyboard, cancel_keyboard
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import BackdateStates
from app.db.repositories.users import UserRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService

router = Router()


@router.callback_query(F.data == "backdate_workout")
async def handle_backdate_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackdateStates.waiting_for_date)
    await callback.message.answer(texts.BACKDATE_INTRO)
    await callback.message.answer(texts.BACKDATE_DATE_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


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

    await state.update_data(backdate_performed_at=parsed_date.isoformat())
    await state.set_state(BackdateStates.waiting_for_block_a)
    await message.answer(texts.BLOCK_A_PROMPT, reply_markup=back_cancel_keyboard("backdate_back:date"))


@router.callback_query(F.data == "backdate_back:date")
async def handle_backdate_back_to_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackdateStates.waiting_for_date)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.BACKDATE_DATE_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(BackdateStates.waiting_for_block_a)
async def handle_backdate_block_a(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", VOLUME_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(BackdateStates.waiting_for_block_b)
    await message.answer(texts.BLOCK_B_PROMPT, reply_markup=back_cancel_keyboard("backdate_back:block_a"))


@router.callback_query(F.data == "backdate_back:block_a")
async def handle_backdate_back_to_block_a(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackdateStates.waiting_for_block_a)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.BLOCK_A_PROMPT, reply_markup=back_cancel_keyboard("backdate_back:date"))
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
    message: Message, state: FSMContext, session: AsyncSession, data: dict,
) -> None:
    """Вызывается из equipment.py, когда очередь снаряда для бэкдейта
    опустела (см. _complete_equipment_queue) — здесь уже есть и повторения
    обоих блоков, и выбранный снаряд, можно записывать."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

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
