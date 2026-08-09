from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.handlers.workout import _ensure_active_workout_set
from app.bot.keyboards import cancel_keyboard, main_menu_keyboard
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import BackdateStates
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService

router = Router()


@router.callback_query(F.data == "backdate_workout")
async def handle_backdate_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackdateStates.waiting_for_date)
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
    await message.answer(texts.BLOCK_A_PROMPT, reply_markup=cancel_keyboard())


@router.message(BackdateStates.waiting_for_block_a)
async def handle_backdate_block_a(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", VOLUME_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(BackdateStates.waiting_for_block_b)
    await message.answer(texts.BLOCK_B_PROMPT, reply_markup=cancel_keyboard())


@router.message(BackdateStates.waiting_for_block_b)
async def handle_backdate_block_b(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_block_result(message.text or "", STRENGTH_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    active_set = await _ensure_active_workout_set(session, user.id)
    if active_set is None:
        await message.answer(texts.NO_ACTIVE_SET_SUPPORT)
        await state.clear()
        return

    # Снаряд на момент прошлой (пропущенной) тренировки отдельно не
    # спрашиваем — берём последний известный (любого происхождения, включая
    # уже внесённые задним числом ранее в этом же вызове). Известное
    # упрощение: если снаряд на самом деле менялся за это время, тренировку
    # можно позже отредактировать вручную.
    workouts = WorkoutRepository(session)
    target_a_state, target_b_state = await workouts.resolve_next_targets(user.id)
    block_a_equipment_type = target_a_state.equipment_type if not target_a_state.needs_new_equipment else EquipmentType.BODYWEIGHT
    block_a_equipment_value = target_a_state.equipment_value if not target_a_state.needs_new_equipment else None
    block_b_equipment_type = target_b_state.equipment_type if not target_b_state.needs_new_equipment else EquipmentType.BODYWEIGHT
    block_b_equipment_value = target_b_state.equipment_value if not target_b_state.needs_new_equipment else None

    block_a_reps = BlockLog(working_reps=tuple(data["block_a_working_reps"]), max_reps=data["block_a_max_reps"])
    performed_at = datetime.fromisoformat(data["backdate_performed_at"])

    log_service = WorkoutLogService(session)
    await log_service.record_backdated_workout(
        user_id=user.id,
        workout_set_id=active_set.id,
        performed_at=performed_at,
        block_a_reps=block_a_reps,
        block_b_reps=result,
        block_a_equipment_type=block_a_equipment_type,
        block_a_equipment_value=block_a_equipment_value,
        block_b_equipment_type=block_b_equipment_type,
        block_b_equipment_value=block_b_equipment_value,
    )

    await state.clear()
    await message.answer(texts.BACKDATE_DONE)
    await message.answer(texts.WHAT_NEXT, reply_markup=main_menu_keyboard())
