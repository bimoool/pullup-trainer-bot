"""«➕ Внести свободные подтягивания» (Часть 10, п. 18, пакет #2, п.21) —
произвольная тренировка вне схемы: снаряд + любое количество подходов, не
в плане и не в цикле из 12, но попадает в статистику/объём (см.
WorkoutRepository.record_free_workout)."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_anomaly_message, format_equipment_label
from app.bot.handlers.workout import _ensure_active_workout_set
from app.bot.keyboards import (
    anomaly_confirm_keyboard,
    back_cancel_keyboard,
    band_item_picker_keyboard,
    band_name_keyboard,
    bands_empty_offer_keyboard,
    bottom_menu_keyboard,
    cancel_keyboard,
    equipment_kg_keyboard,
    equipment_type_keyboard,
)
from app.bot.parsing import ParseError, parse_reps
from app.bot.states import FreeWorkoutStates
from app.config import settings
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.anomalies import detect_anomalies
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService

router = Router()

# Собственный, не разделяемый с equipment.py набор шагов выбора снаряда —
# там очередь привязана к block_key/target объёмного/силового блока
# тренировки, здесь такого контекста нет вообще (одна свободная запись,
# не блок схемы). Дублирование небольшое (имя+кг новой резины), решили не
# городить общий механизм ради него одного.


@router.callback_query(F.data == "free_workout_start")
async def handle_free_workout_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FreeWorkoutStates.waiting_for_equipment_type)
    await callback.message.answer(texts.FREE_WORKOUT_EQUIPMENT_PROMPT, reply_markup=equipment_type_keyboard())
    await callback.answer()


@router.callback_query(FreeWorkoutStates.waiting_for_equipment_type, F.data.startswith("equip:"))
async def handle_free_workout_equipment_choice(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession,
) -> None:
    equipment_type = EquipmentType(callback.data.removeprefix("equip:"))
    await callback.message.edit_reply_markup(reply_markup=None)

    if equipment_type in (EquipmentType.BODYWEIGHT, EquipmentType.AUSTRALIAN):
        await state.update_data(equipment_type=equipment_type.value, equipment_value=None, equipment_item_id=None)
        await _ask_for_reps(callback.message, state)
        await callback.answer()
        return

    if equipment_type == EquipmentType.WEIGHT:
        await state.update_data(pending_equipment_type=equipment_type.value)
        await state.set_state(FreeWorkoutStates.waiting_for_equipment_value)
        await callback.message.answer(
            texts.EQUIPMENT_VALUE_PROMPT_WEIGHT, reply_markup=back_cancel_keyboard("free_workout_back:type"),
        )
        await callback.answer()
        return

    # BAND — личный список, как и везде в боте (Часть 8).
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    items = await EquipmentItemRepository(session).list_for_user(user.id)

    if not items:
        # Явное предложение завести резину, а не молчаливый переход к вводу
        # имени (Часть 10, пакет #2, п.22) — человек может не понять, что
        # происходит, если бот без объяснений сразу спрашивает "как назвать".
        # Да/нет и имя — два отдельных шага (пакет #5), не одно слитное
        # сообщение с двумя вопросами сразу.
        await callback.message.answer(
            texts.MY_BANDS_EMPTY_INLINE_OFFER,
            reply_markup=bands_empty_offer_keyboard(
                yes_callback="free_workout_band_offer:yes", no_callback="free_workout_back:type",
            ),
        )
        await callback.answer()
        return

    await state.set_state(FreeWorkoutStates.waiting_for_band_choice)
    await callback.message.answer(
        texts.FREE_WORKOUT_BAND_PICKER_PROMPT,
        reply_markup=band_item_picker_keyboard(items, "free_workout_back:type"),
    )
    await callback.answer()


@router.callback_query(FreeWorkoutStates.waiting_for_equipment_type, F.data == "free_workout_band_offer:yes")
async def handle_free_workout_band_offer_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(FreeWorkoutStates.waiting_for_new_item_name)
    await callback.message.answer(
        texts.EQUIPMENT_BAND_NAME_PROMPT, reply_markup=band_name_keyboard("free_workout_back:type"),
    )
    await callback.answer()


@router.callback_query(F.data == "free_workout_back:type")
async def handle_free_workout_back_to_type(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FreeWorkoutStates.waiting_for_equipment_type)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.FREE_WORKOUT_EQUIPMENT_PROMPT, reply_markup=equipment_type_keyboard())
    await callback.answer()


@router.message(FreeWorkoutStates.waiting_for_equipment_value)
async def handle_free_workout_equipment_value(message: Message, state: FSMContext) -> None:
    try:
        value = Decimal((message.text or "").strip().replace(",", "."))
    except InvalidOperation:
        await message.answer(texts.EQUIPMENT_VALUE_INVALID)
        return
    if value <= 0:
        await message.answer(texts.EQUIPMENT_VALUE_INVALID)
        return

    data = await state.get_data()
    await state.update_data(
        equipment_type=data["pending_equipment_type"], equipment_value=str(value), equipment_item_id=None,
    )
    await _ask_for_reps(message, state)


@router.callback_query(FreeWorkoutStates.waiting_for_band_choice, F.data.startswith("band_item:"))
async def handle_free_workout_band_choice(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    payload = callback.data.removeprefix("band_item:")
    await callback.message.edit_reply_markup(reply_markup=None)

    if payload == "new":
        await state.set_state(FreeWorkoutStates.waiting_for_new_item_name)
        await callback.message.answer(
            texts.EQUIPMENT_BAND_NAME_PROMPT, reply_markup=band_name_keyboard("free_workout_back:band_list"),
        )
        await callback.answer()
        return

    item = await EquipmentItemRepository(session).get_by_id(int(payload))
    await state.update_data(equipment_type=EquipmentType.BAND.value, equipment_value=None, equipment_item_id=item.id)
    await _ask_for_reps(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "free_workout_back:band_list")
async def handle_free_workout_back_to_band_list(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession,
) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    items = await EquipmentItemRepository(session).list_for_user(user.id)

    await state.set_state(FreeWorkoutStates.waiting_for_band_choice)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        texts.FREE_WORKOUT_BAND_PICKER_PROMPT,
        reply_markup=band_item_picker_keyboard(items, "free_workout_back:type"),
    )
    await callback.answer()


@router.message(FreeWorkoutStates.waiting_for_new_item_name)
async def handle_free_workout_new_item_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer(texts.EQUIPMENT_BAND_NAME_INVALID)
        return
    await state.update_data(pending_item_name=name)
    await state.set_state(FreeWorkoutStates.waiting_for_new_item_kg)
    await message.answer(
        texts.EQUIPMENT_BAND_KG_PROMPT, reply_markup=equipment_kg_keyboard("free_workout_back:new_item_name"),
    )


@router.callback_query(F.data == "free_workout_back:new_item_name")
async def handle_free_workout_back_to_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FreeWorkoutStates.waiting_for_new_item_name)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        texts.EQUIPMENT_BAND_NAME_PROMPT, reply_markup=band_name_keyboard("free_workout_back:type"),
    )
    await callback.answer()


async def _create_free_workout_band_item(
    message: Message, state: FSMContext, session: AsyncSession, *, user_id: int, resistance_kg: Decimal | None,
) -> None:
    data = await state.get_data()
    item = await EquipmentItemRepository(session).create(
        user_id=user_id, name=data["pending_item_name"], resistance_kg=resistance_kg,
    )
    await state.update_data(equipment_type=EquipmentType.BAND.value, equipment_value=None, equipment_item_id=item.id)
    await _ask_for_reps(message, state)


@router.message(FreeWorkoutStates.waiting_for_new_item_kg)
async def handle_free_workout_new_item_kg(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        value = Decimal((message.text or "").strip().replace(",", "."))
    except InvalidOperation:
        await message.answer(texts.EQUIPMENT_BAND_KG_INVALID)
        return
    if value <= 0:
        await message.answer(texts.EQUIPMENT_BAND_KG_INVALID)
        return

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    await _create_free_workout_band_item(message, state, session, user_id=user.id, resistance_kg=value)


@router.callback_query(FreeWorkoutStates.waiting_for_new_item_kg, F.data == "skip_item_kg")
async def handle_free_workout_new_item_kg_skip(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession,
) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _create_free_workout_band_item(callback.message, state, session, user_id=user.id, resistance_kg=None)
    await callback.answer()


async def _ask_for_reps(message: Message, state: FSMContext) -> None:
    await state.set_state(FreeWorkoutStates.waiting_for_reps)
    await message.answer(texts.FREE_WORKOUT_REPS_PROMPT, reply_markup=cancel_keyboard())


@router.message(FreeWorkoutStates.waiting_for_reps)
async def handle_free_workout_reps(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_reps(message.text or "")
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    previous_avg = await WorkoutRepository(session).get_previous_free_avg_working(user.id)
    # expected_work_sets не передаём (пакет #4) — у свободных подтягиваний
    # структурного ожидания нет вообще, проверка количества подходов здесь
    # не имеет смысла (это и есть весь смысл "свободных").
    anomaly_text = format_anomaly_message(detect_anomalies(result, previous_avg_working=previous_avg))
    if anomaly_text is not None:
        await state.update_data(anomaly_working_reps=list(result.working_reps), anomaly_max_reps=result.max_reps)
        await state.set_state(FreeWorkoutStates.waiting_for_reps_confirm)
        await message.answer(anomaly_text, reply_markup=anomaly_confirm_keyboard())
        return

    await _apply_free_workout_reps(message, state, session, result, telegram_id=message.from_user.id)


@router.callback_query(FreeWorkoutStates.waiting_for_reps_confirm, F.data == "anomaly:confirm")
async def handle_free_workout_reps_anomaly_confirm(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession,
) -> None:
    data = await state.get_data()
    result = BlockLog(working_reps=tuple(data["anomaly_working_reps"]), max_reps=data["anomaly_max_reps"])
    await callback.message.edit_reply_markup(reply_markup=None)
    # telegram_id — явно от callback.from_user (нажавший кнопку), НЕ от
    # callback.message.from_user (это бот, см. критический баг Части 10 —
    # тот же самый источник ошибки, здесь предотвращён заранее).
    await _apply_free_workout_reps(callback.message, state, session, result, telegram_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(FreeWorkoutStates.waiting_for_reps_confirm, F.data == "anomaly:reenter")
async def handle_free_workout_reps_anomaly_reenter(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_for_reps(callback.message, state)
    await callback.answer()


async def _apply_free_workout_reps(
    message: Message, state: FSMContext, session: AsyncSession, result: BlockLog, *, telegram_id: int,
) -> None:
    data = await state.get_data()
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)

    active_set = await _ensure_active_workout_set(session, user.id)
    if active_set is None:
        await message.answer(texts.NO_ACTIVE_SET_SUPPORT)
        await state.clear()
        return

    equipment_type = EquipmentType(data["equipment_type"])
    equipment_value = Decimal(data["equipment_value"]) if data.get("equipment_value") else None
    equipment_item_id = data.get("equipment_item_id")

    await WorkoutLogService(session).record_free_workout(
        user_id=user.id, workout_set_id=active_set.id, performed_at=datetime.now(UTC),
        block_a_reps=result, equipment_type=equipment_type,
        equipment_value=equipment_value, equipment_item_id=equipment_item_id,
    )

    reps_summary = " ".join(str(r) for r in (*result.working_reps, result.max_reps))
    equipment_label = format_equipment_label(equipment_type, equipment_value)

    await state.clear()
    await message.answer(texts.FREE_WORKOUT_DONE.format(reps_summary=reps_summary, equipment=equipment_label))
    await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard(is_admin=settings.is_admin(telegram_id)))
