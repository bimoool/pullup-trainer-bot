from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import (
    back_cancel_keyboard,
    bottom_menu_keyboard,
    cancel_keyboard,
    edit_workout_picker_keyboard,
)
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import EditWorkoutStates
from app.db.models import BlockType
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK
from app.domain.session import BlockLog

router = Router()

EDIT_PICKER_LIMIT = 10


def _is_editable(workout) -> bool:
    # Внесённые задним числом не входят в цепочку каскада — редактировать
    # их через этот сценарий нельзя (см. WorkoutRepository.edit_workout).
    return workout.sequence_number is not None and workout.participates_in_cascade


@router.callback_query(F.data == "edit_workout_menu")
async def handle_edit_workout_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Выбор ЛЮБОЙ прошлой тренировки для редактирования (не только
    последней) — см. Часть 3 респека."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    editable = [w for w in history if _is_editable(w)]
    if not editable:
        await callback.answer(texts.EDIT_NOTHING_TO_EDIT, show_alert=True)
        return

    await callback.message.answer(
        texts.EDIT_PICK_WORKOUT, reply_markup=edit_workout_picker_keyboard(editable[-EDIT_PICKER_LIMIT:]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_pick:"))
async def handle_edit_pick(callback: CallbackQuery, state: FSMContext) -> None:
    workout_id = int(callback.data.removeprefix("edit_pick:"))
    await state.update_data(edit_workout_id=workout_id)
    await state.set_state(EditWorkoutStates.waiting_for_block_a)
    await callback.message.answer(texts.BLOCK_A_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "edit_last_workout")
async def handle_edit_last_workout(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    if not history:
        await callback.answer(texts.EDIT_NOTHING_TO_EDIT, show_alert=True)
        return

    last = history[-1]
    if not _is_editable(last):
        await callback.answer(texts.EDIT_NOT_EDITABLE, show_alert=True)
        return

    await state.update_data(edit_workout_id=last.id)
    await state.set_state(EditWorkoutStates.waiting_for_block_a)
    await callback.message.answer(texts.BLOCK_A_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(EditWorkoutStates.waiting_for_block_a)
async def handle_edit_block_a(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", VOLUME_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(EditWorkoutStates.waiting_for_block_b)
    await message.answer(texts.BLOCK_B_PROMPT, reply_markup=back_cancel_keyboard("edit_back:block_a"))


@router.callback_query(F.data == "edit_back:block_a")
async def handle_edit_back_to_block_a(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditWorkoutStates.waiting_for_block_a)
    await callback.message.answer(texts.BLOCK_A_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(EditWorkoutStates.waiting_for_block_b)
async def handle_edit_block_b(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_block_result(message.text or "", STRENGTH_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()
    block_a_reps = BlockLog(working_reps=tuple(data["block_a_working_reps"]), max_reps=data["block_a_max_reps"])

    workouts = WorkoutRepository(session)
    workout = await workouts.edit_workout(
        workout_id=data["edit_workout_id"], block_a_reps=block_a_reps, block_b_reps=result,
    )

    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    await state.clear()
    await message.answer(
        texts.EDIT_DONE.format(
            a_max=block_a.max_reps, a_target=block_a.target_after,
            b_max=block_b.max_reps, b_target=block_b.target_after,
        ),
    )
    await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard())
