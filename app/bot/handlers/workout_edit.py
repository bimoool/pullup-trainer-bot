from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import (
    format_anomaly_message,
    format_block_result,
    format_equipment_from_result,
    format_equipment_label,
    format_reps_example,
    format_sets_word,
)
from app.bot.keyboards import (
    anomaly_confirm_keyboard,
    back_cancel_keyboard,
    bottom_menu_keyboard,
    cancel_keyboard,
    edit_equipment_band_keyboard,
    edit_equipment_weight_keyboard,
    edit_workout_picker_keyboard,
)
from app.bot.parsing import ParseError, parse_reps
from app.bot.states import EditWorkoutStates
from app.config import settings
from app.db.models import BlockType
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.anomalies import detect_anomalies
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.session import BlockLog

router = Router()

_BLOCK_LABELS = {"a": "блоке на объём", "b": "блоке на силу"}


def _is_editable(workout) -> bool:
    # Внесённые задним числом не входят в цепочку каскада — редактировать
    # их через этот сценарий нельзя (см. WorkoutRepository.edit_workout).
    return workout.sequence_number is not None and workout.participates_in_cascade


def _format_block_a_prompt(target: int, work_sets: int) -> str:
    example_a = format_reps_example(target, work_sets)
    return texts.BLOCK_A_PROMPT.format(example=example_a, work_sets=work_sets, sets_word=format_sets_word(work_sets))


def _block_equipment_result(block) -> dict[str, str | None]:
    """Снаряд ИСТОРИЧЕСКОЙ записи (не переспрашивается при вводе новых
    чисел — правка веса/резины отдельным шагом после, см. ниже) в форме
    equipment_results[block_key] (см. app/bot/handlers/equipment.py), чтобы
    показать его в приглашениях через format_equipment_from_result (пакет
    #7 — снаряд не был виден при вводе результата, реальный пробел)."""
    return {
        "type": block.equipment_type.value,
        "value": str(block.equipment_value) if block.equipment_value is not None else None,
    }


@router.callback_query(F.data == "edit_workout_menu")
async def handle_edit_workout_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Выбор ЛЮБОЙ прошлой тренировки для редактирования (не только
    последней) — теперь через календарь, не плоский список кнопок-дат
    (Часть 10, пакет #2, п.17: список неизбежно растёт вместе с историей)."""
    from app.bot.handlers.history import (
        render_calendar_month,  # деферред — см. комментарий в history.py
    )

    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    if not any(_is_editable(w) for w in history):
        await callback.answer(texts.EDIT_NOTHING_TO_EDIT, show_alert=True)
        return

    now = datetime.now(UTC)
    await render_calendar_month(
        callback, session, year=now.year, month=now.month, edit=False, mode="edit", history_filter=_is_editable,
    )
    await callback.answer()


async def handle_calendar_workout_picked(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, picked_date: date,
) -> None:
    """Вызывается из history.py при тапе по дню в режиме "edit" (Часть 10,
    пакет #2, п.17). Обычно на дату приходится ровно одна редактируемая
    тренировка — сразу переходим к вводу правки; в редком случае нескольких
    за день — короткий саб-список только на этот день (те же кнопки
    edit_pick:, что и раньше, просто с меткой по времени, не по дате —
    дата у всех в списке одинаковая)."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    day_workouts = [w for w in history if w.performed_at.date() == picked_date]
    day_editable = [w for w in day_workouts if _is_editable(w)]

    if not day_editable:
        # Пакет #3, баг 2 — день без единой редактируемой тренировки бывает
        # двух разных случаев: либо тренировок в этот день вообще не было
        # (EDIT_NOTHING_TO_EDIT), либо они есть, но все внесены задним
        # числом (не участвуют в каскаде — редактировать через этот сценарий
        # нельзя принципиально, см. _is_editable). Раньше оба случая
        # показывали один и тот же неинформативный текст — из "Истории"/
        # календаря бэкдейта такой день виден отмеченным ✅, и генеричное
        # "нечего редактировать" выглядело как рассинхрон, хотя оба
        # календаря на самом деле смотрят на один и тот же _is_editable.
        text = texts.EDIT_NOT_EDITABLE if day_workouts else texts.EDIT_NOTHING_TO_EDIT
        await callback.answer(text, show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)

    if len(day_editable) == 1:
        await _start_editing(callback.message, state, session, workout_id=day_editable[0].id)
        await callback.answer()
        return

    await callback.message.answer(
        texts.EDIT_PICK_WORKOUT,
        reply_markup=edit_workout_picker_keyboard(day_editable, label_format="%H:%M"),
    )
    await callback.answer()


async def _start_editing(message: Message, state: FSMContext, session: AsyncSession, *, workout_id: int) -> None:
    """target_a/target_b кладутся в FSM здесь один раз — не текущая цель
    пользователя, а target_before ИМЕННО этой редактируемой тренировки
    (Часть 10, пакет #2, п.10): именно против неё вводился реальный
    результат, это и есть корректный пример формата ввода."""
    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    # work_sets_before — NULL для исторических записей до ревизии формулы
    # прогрессии (см. миграцию e2c7a4f19d3b) — тогда число рабочих подходов
    # ещё было фиксированным VOLUME_BLOCK.work_sets.
    work_sets_a = block_a.work_sets_before if block_a.work_sets_before is not None else VOLUME_BLOCK.work_sets

    await state.update_data(
        edit_workout_id=workout_id, target_a=block_a.target_before, target_b=block_b.target_before,
        work_sets_a=work_sets_a,
        # Для проверки "резкого скачка" (пакет #4) сравнивать нужно с тем,
        # что было ДО этой записи, а не с глобально последней тренировкой —
        # редактируется может быть старая запись, после которой уже
        # случилось что-то ещё.
        edit_workout_performed_at=workout.performed_at.isoformat(),
        edit_block_a_equipment=_block_equipment_result(block_a),
        edit_block_b_equipment=_block_equipment_result(block_b),
    )
    await state.set_state(EditWorkoutStates.waiting_for_block_a)
    prompt = _format_block_a_prompt(block_a.target_before, work_sets_a) + texts.BLOCK_EQUIPMENT_NOTE.format(
        equipment=format_equipment_from_result(_block_equipment_result(block_a), instrumental=True),
    )
    await message.answer(prompt, reply_markup=cancel_keyboard())


@router.callback_query(F.data.startswith("edit_pick:"))
async def handle_edit_pick(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    workout_id = int(callback.data.removeprefix("edit_pick:"))
    await callback.message.edit_reply_markup(reply_markup=None)
    await _start_editing(callback.message, state, session, workout_id=workout_id)
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

    await _start_editing(callback.message, state, session, workout_id=last.id)
    await callback.answer()


async def _previous_avg_for_edit(session: AsyncSession, user_id: int, block_type: BlockType, data: dict) -> float | None:
    before = datetime.fromisoformat(data["edit_workout_performed_at"])
    return await WorkoutRepository(session).get_previous_avg_working(user_id, block_type, before=before)


@router.message(EditWorkoutStates.waiting_for_block_a)
async def handle_edit_block_a(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_reps(message.text or "")
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    data = await state.get_data()
    previous_avg = await _previous_avg_for_edit(session, user.id, BlockType.A, data)
    anomaly_text = format_anomaly_message(
        detect_anomalies(
            result, previous_avg_working=previous_avg,
            expected_work_sets=data.get("work_sets_a", VOLUME_BLOCK.work_sets),
        ),
    )
    if anomaly_text is not None:
        await state.update_data(anomaly_working_reps=list(result.working_reps), anomaly_max_reps=result.max_reps)
        await state.set_state(EditWorkoutStates.waiting_for_block_a_confirm)
        await message.answer(anomaly_text, reply_markup=anomaly_confirm_keyboard())
        return

    await _apply_edit_block_a(message, state, result)


async def _apply_edit_block_a(message: Message, state: FSMContext, result: BlockLog) -> None:
    data = await state.get_data()
    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(EditWorkoutStates.waiting_for_block_b)
    example_b = format_reps_example(data["target_b"], STRENGTH_BLOCK.work_sets)
    prompt = texts.BLOCK_B_PROMPT.format(example=example_b) + texts.BLOCK_EQUIPMENT_NOTE.format(
        equipment=format_equipment_from_result(data["edit_block_b_equipment"], instrumental=True),
    )
    await message.answer(prompt, reply_markup=back_cancel_keyboard("edit_back:block_a"))


@router.callback_query(EditWorkoutStates.waiting_for_block_a_confirm, F.data == "anomaly:confirm")
async def handle_edit_block_a_anomaly_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    result = BlockLog(working_reps=tuple(data["anomaly_working_reps"]), max_reps=data["anomaly_max_reps"])
    await callback.message.edit_reply_markup(reply_markup=None)
    await _apply_edit_block_a(callback.message, state, result)
    await callback.answer()


@router.callback_query(EditWorkoutStates.waiting_for_block_a_confirm, F.data == "anomaly:reenter")
async def handle_edit_block_a_anomaly_reenter(callback: CallbackQuery, state: FSMContext) -> None:
    await _resend_edit_block_a_prompt(callback, state)


@router.callback_query(F.data == "edit_back:block_a")
async def handle_edit_back_to_block_a(callback: CallbackQuery, state: FSMContext) -> None:
    await _resend_edit_block_a_prompt(callback, state)


async def _resend_edit_block_a_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(EditWorkoutStates.waiting_for_block_a)
    await callback.message.edit_reply_markup(reply_markup=None)
    work_sets_a = data.get("work_sets_a", VOLUME_BLOCK.work_sets)
    prompt = _format_block_a_prompt(data["target_a"], work_sets_a) + texts.BLOCK_EQUIPMENT_NOTE.format(
        equipment=format_equipment_from_result(data["edit_block_a_equipment"], instrumental=True),
    )
    await callback.message.answer(prompt, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(EditWorkoutStates.waiting_for_block_b)
async def handle_edit_block_b(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_reps(message.text or "")
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    data = await state.get_data()
    previous_avg = await _previous_avg_for_edit(session, user.id, BlockType.B, data)
    anomaly_text = format_anomaly_message(
        detect_anomalies(result, previous_avg_working=previous_avg, expected_work_sets=STRENGTH_BLOCK.work_sets),
    )
    if anomaly_text is not None:
        await state.update_data(anomaly_working_reps=list(result.working_reps), anomaly_max_reps=result.max_reps)
        await state.set_state(EditWorkoutStates.waiting_for_block_b_confirm)
        await message.answer(anomaly_text, reply_markup=anomaly_confirm_keyboard())
        return

    await _apply_edit_block_b(message, state, session, result, telegram_id=message.from_user.id)


@router.callback_query(EditWorkoutStates.waiting_for_block_b_confirm, F.data == "anomaly:confirm")
async def handle_edit_block_b_anomaly_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    result = BlockLog(working_reps=tuple(data["anomaly_working_reps"]), max_reps=data["anomaly_max_reps"])
    await callback.message.edit_reply_markup(reply_markup=None)
    await _apply_edit_block_b(callback.message, state, session, result, telegram_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(EditWorkoutStates.waiting_for_block_b_confirm, F.data == "anomaly:reenter")
async def handle_edit_block_b_anomaly_reenter(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(EditWorkoutStates.waiting_for_block_b)
    await callback.message.edit_reply_markup(reply_markup=None)
    example_b = format_reps_example(data["target_b"], STRENGTH_BLOCK.work_sets)
    prompt = texts.BLOCK_B_PROMPT.format(example=example_b) + texts.BLOCK_EQUIPMENT_NOTE.format(
        equipment=format_equipment_from_result(data["edit_block_b_equipment"], instrumental=True),
    )
    await callback.message.answer(prompt, reply_markup=back_cancel_keyboard("edit_back:block_a"))
    await callback.answer()


async def _apply_edit_block_b(
    message: Message, state: FSMContext, session: AsyncSession, result: BlockLog, *, telegram_id: int,
) -> None:
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
            a_result=format_block_result(block_a.working_reps, block_a.max_reps), a_target=block_a.target_after,
            b_result=format_block_result(block_b.working_reps, block_b.max_reps), b_target=block_b.target_after,
            equipment_a=format_equipment_label(block_a.equipment_type, block_a.equipment_value),
            equipment_b=format_equipment_label(block_b.equipment_type, block_b.equipment_value),
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
        await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard(is_admin=settings.is_admin(telegram_id)))
        return

    await state.update_data(equipment_correction_queue=correction_queue)
    await _advance_equipment_correction(message, state, session, telegram_id=telegram_id)


async def _advance_equipment_correction(
    message: Message, state: FSMContext, session: AsyncSession, *, telegram_id: int,
) -> None:
    data = await state.get_data()
    queue: list[str] = data["equipment_correction_queue"]

    if not queue:
        await state.clear()
        await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard(is_admin=settings.is_admin(telegram_id)))
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
        await _advance_past_current_equipment_block(message, state, session, telegram_id=telegram_id)
        return

    current_item = next((item for item in items if item.id == block.equipment_item_id), None)
    await state.set_state(EditWorkoutStates.waiting_for_equipment_band)
    prompt = texts.EDIT_EQUIPMENT_BAND_PROMPT.format(
        block_label=_BLOCK_LABELS[block_key], name=current_item.name if current_item else "?",
    )
    await message.answer(prompt, reply_markup=edit_equipment_band_keyboard(items))


async def _advance_past_current_equipment_block(
    message: Message, state: FSMContext, session: AsyncSession, *, telegram_id: int,
) -> None:
    data = await state.get_data()
    queue = data["equipment_correction_queue"][1:]
    await state.update_data(equipment_correction_queue=queue)
    await _advance_equipment_correction(message, state, session, telegram_id=telegram_id)


@router.callback_query(F.data == "edit_equipment_skip")
async def handle_edit_equipment_skip(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await _advance_past_current_equipment_block(callback.message, state, session, telegram_id=callback.from_user.id)
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
    await _advance_past_current_equipment_block(message, state, session, telegram_id=message.from_user.id)


@router.callback_query(EditWorkoutStates.waiting_for_equipment_band, F.data.startswith("edit_band_item:"))
async def handle_edit_equipment_band(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    item_id = int(callback.data.removeprefix("edit_band_item:"))
    data = await state.get_data()
    block_key = data["equipment_correction_queue"][0]
    block_type = BlockType.A if block_key == "a" else BlockType.B
    await WorkoutRepository(session).correct_block_equipment(
        workout_id=data["edit_workout_id"], block_type=block_type, equipment_item_id=item_id,
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.EDIT_EQUIPMENT_UPDATED)
    await _advance_past_current_equipment_block(callback.message, state, session, telegram_id=callback.from_user.id)
    await callback.answer()
