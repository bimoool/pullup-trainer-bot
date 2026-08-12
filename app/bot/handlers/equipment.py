from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_equipment_label
from app.bot.keyboards import (
    back_cancel_keyboard,
    band_item_picker_keyboard,
    band_reorder_keyboard,
    cancel_keyboard,
    equipment_kg_keyboard,
    equipment_type_keyboard,
    profile_keyboard,
)
from app.bot.states import EquipmentStates
from app.config import settings
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.progression import suggest_starting_equipment

router = Router()

_BLOCK_LABELS = {"a": "блоке на объём", "b": "блоке на силу"}


def _target_hint(block_key: str) -> str:
    target = VOLUME_BLOCK.base_target if block_key == "a" else STRENGTH_BLOCK.base_target
    return texts.EQUIPMENT_TARGET_HINT.format(target=target)

# Личный список резин растёт по мере надобности (Часть 8 респека) — этот
# модуль общий для живой тренировки (workout.py), бэкдейта (backdate.py) и
# ретеста: все три сценария используют одну и ту же очередь снарядов
# (equipment_queue/equipment_results в FSM-данных). Кто именно продолжает
# после того, как очередь опустела, определяет флаг equipment_flow — см.
# _complete_equipment_queue. Импорт workout.py/backdate.py внутри неё, а не
# на верхнем уровне модуля — иначе цикл импортов (оба файла импортируют
# _begin_equipment_setup отсюда).


async def _begin_equipment_setup(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    *,
    flow: str,
    target_a_state,
    target_b_state,
    telegram_id: int,
    baseline_reps: int | None = None,
    extra_data: dict | None = None,
) -> None:
    """target_*_state=None форсирует переспрос снаряда для обоих блоков
    (первая тренировка / ретест / бэкдейт — там снаряд теперь тоже всегда
    явный, см. Часть 8) — иначе очередь строится по needs_new_equipment
    каждого блока (обычное продолжение живой тренировки).

    extra_data — то, что уже накоплено в FSM до вызова (например, реально
    введённые повторения бэкдейта) и должно пережить сбор снаряда, чтобы
    _complete_equipment_queue могло собрать финальную запись.

    telegram_id — сохраняется в FSM явно и передаётся до самого конца
    очереди (см. _complete_equipment_queue), а не берётся на месте записи
    из message.from_user.id: очередь снаряда почти всегда завершается
    callback-шагом (выбор своего веса/резины из списка), а у сообщения,
    привязанного к CallbackQuery, from_user — это БОТ, а не человек,
    который нажал кнопку. Ровно это было причиной бага "тренировка не
    записывается при 'Пропустить' у комментария" (Часть 10) — то же самое
    молча ждало здесь для бэкдейта."""
    equipment_queue: list[str] = []
    equipment_results: dict[str, dict[str, str | int | None]] = {}

    for key, block_state in (("a", target_a_state), ("b", target_b_state)):
        if block_state is None or block_state.needs_new_equipment:
            equipment_queue.append(key)
        else:
            equipment_results[key] = {
                "type": block_state.equipment_type.value,
                "value": str(block_state.equipment_value) if block_state.equipment_value is not None else None,
                "item_id": block_state.equipment_item_id,
            }

    await state.update_data(
        equipment_flow=flow,
        equipment_queue=equipment_queue,
        equipment_results=equipment_results,
        baseline_reps=baseline_reps,
        telegram_id=telegram_id,
        **(extra_data or {}),
    )
    await _advance_equipment_queue(message, state, session)


async def _advance_equipment_queue(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    queue: list[str] = data["equipment_queue"]

    if not queue:
        await _complete_equipment_queue(message, state, session, data)
        return

    block_key = queue[0]
    await state.set_state(EquipmentStates.waiting_for_type)

    # baseline_reps выставлен только для самой первой тренировки/ретеста —
    # во всех остальных случаях None, и рекомендации снаряда по замеру нет
    # (домен ничего не советует при смене снаряда по порогу прогрессии,
    # см. EQUIPMENT_TYPE_PROMPT_CHANGE — там по-прежнему открытый вопрос).
    #
    # План формулируется фактом, одним сообщением на оба блока сразу, без
    # кнопок подтверждения/замены (Часть 10, пакет #2, п.6-7) — снаряд
    # применяется сразу, без промежуточного шага. equipment_plan_announced
    # в FSM гарантирует ровно одно объявление на весь заход, даже если
    # пользователь потом тапнет "Назад" с шага ввода веса/резины и вернётся
    # сюда повторно для того же блока.
    if data.get("baseline_reps") is not None:
        suggested_a, suggested_b = suggest_starting_equipment(data["baseline_reps"])
        if not data.get("equipment_plan_announced"):
            announcement = texts.EQUIPMENT_PLAN_ANNOUNCEMENT.format(
                equipment_a=format_equipment_label(suggested_a, instrumental=True),
                equipment_b=format_equipment_label(suggested_b, instrumental=True),
            )
            await message.answer(announcement)
            await state.update_data(equipment_plan_announced=True)
        suggested = suggested_a if block_key == "a" else suggested_b
        await _apply_equipment_type_choice(suggested, message, state, session, data["telegram_id"])
        return

    prompt = texts.EQUIPMENT_TYPE_PROMPT_CHANGE.format(block_label=_BLOCK_LABELS[block_key])
    await message.answer(prompt, reply_markup=equipment_type_keyboard())


async def _complete_equipment_queue(message: Message, state: FSMContext, session: AsyncSession, data: dict) -> None:
    from app.bot.handlers import (  # деферред-импорт — см. комментарий в шапке файла
        backdate,
        workout,
    )

    if data["equipment_flow"] == "backdate":
        await backdate.finalize_backdated_workout(message, state, session, data, telegram_id=data["telegram_id"])
    else:
        await workout._send_plan(
            message, state, data["target_a"], data["target_b"],
            is_first_workout=data.get("is_first_workout", False),
        )


async def _apply_equipment_type_choice(
    equipment_type: EquipmentType, message: Message, state: FSMContext, session: AsyncSession, telegram_id: int,
) -> None:
    """Общая ветка для обычного выбора (handle_equipment_type_choice) и
    автоприменённой рекомендации (_advance_equipment_queue, п.6-7 пакета
    #2) — оба в итоге применяют один и тот же тип снаряда к текущему блоку."""
    data = await state.get_data()
    block_key = data["equipment_queue"][0]

    if equipment_type in (EquipmentType.BODYWEIGHT, EquipmentType.AUSTRALIAN):
        results = data["equipment_results"]
        results[block_key] = {"type": equipment_type.value, "value": None, "item_id": None}
        queue = data["equipment_queue"][1:]
        await state.update_data(equipment_results=results, equipment_queue=queue)
        await _advance_equipment_queue(message, state, session)
        return

    if equipment_type == EquipmentType.WEIGHT:
        await state.update_data(pending_equipment_type=equipment_type.value)
        await state.set_state(EquipmentStates.waiting_for_value)
        # Конкретная рекомендация вместо общего принципа (Часть 10, пакет
        # #2, п.7) — только когда это первый старт блока на силу на
        # отягощении по замеру; иначе обычная подсказка "около N повторений".
        is_first_strength_weight = block_key == "b" and data.get("baseline_reps") is not None
        hint = texts.EQUIPMENT_STRENGTH_WEIGHT_START_HINT if is_first_strength_weight else _target_hint(block_key)
        await message.answer(
            texts.EQUIPMENT_VALUE_PROMPT_WEIGHT + hint,
            reply_markup=back_cancel_keyboard("equip_back:type"),
        )
        return

    # BAND — личный список пользователя вместо свободного ввода кг.
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)
    items = await EquipmentItemRepository(session).list_for_user(user.id)

    if not items:
        # Явное предложение завести резину (Часть 10, пакет #2, п.22) —
        # не молчаливый переход к вводу имени, человек может не понять,
        # что происходит, если бот без объяснений сразу спрашивает "как
        # назвать".
        await state.set_state(EquipmentStates.waiting_for_new_item_name)
        await message.answer(
            texts.MY_BANDS_EMPTY_INLINE_OFFER + _target_hint(block_key),
            reply_markup=back_cancel_keyboard("equip_back:type"),
        )
        return

    await state.set_state(EquipmentStates.waiting_for_band_choice)
    prompt = texts.EQUIPMENT_BAND_PICKER_PROMPT.format(block_label=_BLOCK_LABELS[block_key]) + _target_hint(block_key)
    await message.answer(prompt, reply_markup=band_item_picker_keyboard(items, "equip_back:type"))


@router.callback_query(EquipmentStates.waiting_for_type, F.data.startswith("equip:"))
async def handle_equipment_type_choice(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    equipment_type = EquipmentType(callback.data.removeprefix("equip:"))
    await callback.message.edit_reply_markup(reply_markup=None)
    await _apply_equipment_type_choice(equipment_type, callback.message, state, session, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "equip_back:type")
async def handle_equipment_back_to_type(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    # Очередь не изменялась при переходе type -> value/band (позиция в
    # equipment_queue снимается только после успешного выбора) — повторный
    # вызов _advance_equipment_queue просто переспрашивает тип для того же
    # блока, ничего дополнительно восстанавливать не нужно.
    await callback.message.edit_reply_markup(reply_markup=None)
    await _advance_equipment_queue(callback.message, state, session)
    await callback.answer()


@router.message(EquipmentStates.waiting_for_value)
async def handle_equipment_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        value = Decimal((message.text or "").strip().replace(",", "."))
    except InvalidOperation:
        await message.answer(texts.EQUIPMENT_VALUE_INVALID)
        return
    if value <= 0:
        await message.answer(texts.EQUIPMENT_VALUE_INVALID)
        return

    data = await state.get_data()
    block_key = data["equipment_queue"][0]
    results = data["equipment_results"]
    results[block_key] = {"type": data["pending_equipment_type"], "value": str(value), "item_id": None}
    queue = data["equipment_queue"][1:]

    await state.update_data(equipment_results=results, equipment_queue=queue)
    await _advance_equipment_queue(message, state, session)


@router.callback_query(EquipmentStates.waiting_for_band_choice, F.data.startswith("band_item:"))
async def handle_band_item_choice(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    payload = callback.data.removeprefix("band_item:")
    data = await state.get_data()
    block_key = data["equipment_queue"][0]
    await callback.message.edit_reply_markup(reply_markup=None)

    if payload == "new":
        await state.set_state(EquipmentStates.waiting_for_new_item_name)
        await callback.message.answer(
            texts.EQUIPMENT_BAND_NAME_PROMPT + _target_hint(block_key),
            reply_markup=back_cancel_keyboard("equip_back:band_list"),
        )
        await callback.answer()
        return

    item = await EquipmentItemRepository(session).get_by_id(int(payload))

    results = data["equipment_results"]
    results[block_key] = {"type": EquipmentType.BAND.value, "value": None, "item_id": item.id}
    queue = data["equipment_queue"][1:]
    await state.update_data(equipment_results=results, equipment_queue=queue)
    await _advance_equipment_queue(callback.message, state, session)
    await callback.answer()


@router.callback_query(F.data == "equip_back:band_list")
async def handle_equipment_back_to_band_list(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    # Достижимо только из шага "новая резина", куда попадают, только когда
    # список уже был непустым (иначе для пустого списка сразу открывается
    # шаг имени с back_callback="equip_back:type") — поэтому здесь список
    # гарантированно не пуст.
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    items = await EquipmentItemRepository(session).list_for_user(user.id)
    data = await state.get_data()
    block_key = data["equipment_queue"][0]

    await state.set_state(EquipmentStates.waiting_for_band_choice)
    await callback.message.edit_reply_markup(reply_markup=None)
    prompt = texts.EQUIPMENT_BAND_PICKER_PROMPT.format(block_label=_BLOCK_LABELS[block_key]) + _target_hint(block_key)
    await callback.message.answer(prompt, reply_markup=band_item_picker_keyboard(items, "equip_back:type"))
    await callback.answer()


@router.message(EquipmentStates.waiting_for_new_item_name)
async def handle_new_item_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer(texts.EQUIPMENT_BAND_NAME_INVALID)
        return

    await state.update_data(pending_item_name=name)
    await state.set_state(EquipmentStates.waiting_for_new_item_kg)
    await message.answer(texts.EQUIPMENT_BAND_KG_PROMPT, reply_markup=equipment_kg_keyboard("equip_back:new_item_name"))


@router.callback_query(F.data == "equip_back:new_item_name")
async def handle_equipment_back_to_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EquipmentStates.waiting_for_new_item_name)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.EQUIPMENT_BAND_NAME_PROMPT, reply_markup=back_cancel_keyboard("equip_back:type"))
    await callback.answer()


async def _create_band_item_and_advance(
    message: Message, state: FSMContext, session: AsyncSession, *, user_id: int, resistance_kg: Decimal | None,
) -> None:
    data = await state.get_data()
    item = await EquipmentItemRepository(session).create(
        user_id=user_id, name=data["pending_item_name"], resistance_kg=resistance_kg,
    )

    block_key = data["equipment_queue"][0]
    results = data["equipment_results"]
    results[block_key] = {"type": EquipmentType.BAND.value, "value": None, "item_id": item.id}
    queue = data["equipment_queue"][1:]
    await state.update_data(equipment_results=results, equipment_queue=queue)
    await _advance_equipment_queue(message, state, session)


@router.message(EquipmentStates.waiting_for_new_item_kg)
async def handle_new_item_kg(message: Message, state: FSMContext, session: AsyncSession) -> None:
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
    await _create_band_item_and_advance(message, state, session, user_id=user.id, resistance_kg=value)


@router.callback_query(EquipmentStates.waiting_for_new_item_kg, F.data == "skip_item_kg")
async def handle_new_item_kg_skip(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _create_band_item_and_advance(callback.message, state, session, user_id=user.id, resistance_kg=None)
    await callback.answer()


# --- "🎗 Мои резины" — реордер личного списка из Профиля ------------------------


@router.callback_query(F.data == "equipment_list_open")
async def handle_equipment_list_open(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    items = await EquipmentItemRepository(session).list_for_user(user.id)

    # "➕ Добавить резину" видна всегда (Часть 10, п. 22) — даже при пустом
    # списке, поэтому MY_BANDS_EMPTY больше не тупиковый текст без кнопок.
    title = texts.MY_BANDS_TITLE if items else texts.MY_BANDS_EMPTY
    await callback.message.answer(title, reply_markup=band_reorder_keyboard(items))
    await callback.answer()


@router.callback_query(F.data == "band_add_standalone")
async def handle_band_add_standalone_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Заведение резины заранее, вне тренировки (Часть 10, п. 22) — та же
    пара шагов имя+кг, что и в очереди снаряда, но без block-контекста:
    отдельные состояния, чтобы не путать с equipment_queue-флоу."""
    await state.set_state(EquipmentStates.waiting_for_standalone_item_name)
    await callback.message.answer(texts.EQUIPMENT_BAND_NAME_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(EquipmentStates.waiting_for_standalone_item_name)
async def handle_band_add_standalone_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer(texts.EQUIPMENT_BAND_NAME_INVALID)
        return

    await state.update_data(pending_standalone_item_name=name)
    await state.set_state(EquipmentStates.waiting_for_standalone_item_kg)
    await message.answer(texts.EQUIPMENT_BAND_KG_PROMPT, reply_markup=equipment_kg_keyboard("cancel_flow"))


async def _create_standalone_band_item(
    message: Message, state: FSMContext, session: AsyncSession, *, user_id: int, resistance_kg: Decimal | None,
) -> None:
    data = await state.get_data()
    await EquipmentItemRepository(session).create(
        user_id=user_id, name=data["pending_standalone_item_name"], resistance_kg=resistance_kg,
    )
    await state.clear()

    items = await EquipmentItemRepository(session).list_for_user(user_id)
    await message.answer(texts.MY_BANDS_TITLE, reply_markup=band_reorder_keyboard(items))


@router.message(EquipmentStates.waiting_for_standalone_item_kg)
async def handle_band_add_standalone_kg(message: Message, state: FSMContext, session: AsyncSession) -> None:
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
    await _create_standalone_band_item(message, state, session, user_id=user.id, resistance_kg=value)


@router.callback_query(EquipmentStates.waiting_for_standalone_item_kg, F.data == "skip_item_kg")
async def handle_band_add_standalone_kg_skip(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _create_standalone_band_item(callback.message, state, session, user_id=user.id, resistance_kg=None)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("band_move:"))
async def handle_band_move(callback: CallbackQuery, session: AsyncSession) -> None:
    _, item_id_raw, direction = callback.data.split(":")
    item_id = int(item_id_raw)

    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    repo = EquipmentItemRepository(session)
    items = await repo.list_for_user(user.id)
    ids = [item.id for item in items]

    position = ids.index(item_id)
    swap_with = position - 1 if direction == "up" else position + 1
    if 0 <= swap_with < len(ids):
        ids[position], ids[swap_with] = ids[swap_with], ids[position]
        items = await repo.reorder(user.id, ids)

    await callback.message.edit_text(texts.MY_BANDS_TITLE, reply_markup=band_reorder_keyboard(items))
    await callback.answer()


@router.callback_query(F.data == "band_reorder_done")
async def handle_band_reorder_done(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup()
    is_admin = settings.is_admin(callback.from_user.id)
    await callback.message.answer(texts.MY_BANDS_REORDER_DONE, reply_markup=profile_keyboard(is_admin=is_admin))
    await callback.answer()
