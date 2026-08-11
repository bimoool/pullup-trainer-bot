from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import (
    back_cancel_keyboard,
    bottom_menu_keyboard,
    cancel_keyboard,
    edit_equipment_band_keyboard,
    edit_equipment_weight_keyboard,
    edit_workout_picker_keyboard,
)
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import EditWorkoutStates
from app.db.models import BlockType
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.session import BlockLog

router = Router()

EDIT_PICKER_LIMIT = 10
_BLOCK_LABELS = {"a": "блоке на объём", "b": "блоке на силу"}


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
    await message.answer(
        texts.EDIT_DONE.format(
            a_max=block_a.max_reps, a_target=block_a.target_after,
            b_max=block_b.max_reps, b_target=block_b.target_after,
        ),
    )

    # Правка веса/резины "в этом же отчёте" (Часть 10) — только для блоков
    # с корректируемым значением (WEIGHT/BAND); если оба на bodyweight/
    # australian, корректировать нечего, сразу заканчиваем как раньше.
    correction_queue = [
        key for key, block in (("a", block_a), ("b", block_b))
        if block.equipment_type in (EquipmentType.WEIGHT, EquipmentType.BAND)
    ]
    if not correction_queue:
        await state.clear()
        await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard())
        return

    await state.update_data(equipment_correction_queue=correction_queue)
    await _advance_equipment_correction(message, state, session)


async def _advance_equipment_correction(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    queue: list[str] = data["equipment_correction_queue"]

    if not queue:
        await state.clear()
        await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard())
        return

    block_key = queue[0]
    block_type = BlockType.A if block_key == "a" else BlockType.B
    workout = await WorkoutRepository(session).get_by_id(data["edit_workout_id"])
    block = next(b for b in workout.blocks if b.block_type == block_type)

    if block.equipment_type == EquipmentType.WEIGHT:
        await state.set_state(EditWorkoutStates.waiting_for_equipment_weight)
        prompt = texts.EDIT_EQUIPMENT_WEIGHT_PROMPT.format(
            block_label=_BLOCK_LABELS[block_key], value=block.equipment_value,
        )
        await message.answer(prompt, reply_markup=edit_equipment_weight_keyboard())
        return

    # BAND
    items = await EquipmentItemRepository(session).list_for_user(workout.user_id)
    if not items or block.equipment_item_id is None:
        # Нечего показать взамен (личный список пуст или запись старее
        # Части 8, без ссылки на него) — пропускаем блок молча.
        await _advance_past_current_equipment_block(message, state, session)
        return

    current_item = next((item for item in items if item.id == block.equipment_item_id), None)
    await state.set_state(EditWorkoutStates.waiting_for_equipment_band)
    prompt = texts.EDIT_EQUIPMENT_BAND_PROMPT.format(
        block_label=_BLOCK_LABELS[block_key], name=current_item.name if current_item else "?",
    )
    await message.answer(prompt, reply_markup=edit_equipment_band_keyboard(items))


async def _advance_past_current_equipment_block(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    queue = data["equipment_correction_queue"][1:]
    await state.update_data(equipment_correction_queue=queue)
    await _advance_equipment_correction(message, state, session)


@router.callback_query(F.data == "edit_equipment_skip")
async def handle_edit_equipment_skip(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _advance_past_current_equipment_block(callback.message, state, session)
    await callback.answer()


@router.message(EditWorkoutStates.waiting_for_equipment_weight)
async def handle_edit_equipment_weight(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        value = Decimal((message.text or "").strip().replace(",", "."))
    except InvalidOperation:
        await message.answer(texts.EQUIPMENT_VALUE_INVALID)
        return
    if value <= 0:
        await message.answer(texts.EQUIPMENT_VALUE_INVALID)
        return

    data = await state.get_data()
    block_key = data["equipment_correction_queue"][0]
    block_type = BlockType.A if block_key == "a" else BlockType.B
    await WorkoutRepository(session).correct_block_equipment(
        workout_id=data["edit_workout_id"], block_type=block_type, equipment_value=value,
    )
    await message.answer(texts.EDIT_EQUIPMENT_UPDATED)
    await _advance_past_current_equipment_block(message, state, session)


@router.callback_query(EditWorkoutStates.waiting_for_equipment_band, F.data.startswith("edit_band_item:"))
async def handle_edit_equipment_band(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    item_id = int(callback.data.removeprefix("edit_band_item:"))
    data = await state.get_data()
    block_key = data["equipment_correction_queue"][0]
    block_type = BlockType.A if block_key == "a" else BlockType.B
    await WorkoutRepository(session).correct_block_equipment(
        workout_id=data["edit_workout_id"], block_type=block_type, equipment_item_id=item_id,
    )
    await callback.message.answer(texts.EDIT_EQUIPMENT_UPDATED)
    await _advance_past_current_equipment_block(callback.message, state, session)
    await callback.answer()
