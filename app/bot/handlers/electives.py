"""Факультативная нагрузка вне плана (пакет #6, app/domain/electives.py) —
4 самостоятельных формата, ротация без повтора (цикл из 4, свободный
порядок выбора) + не чаще раза в неделю. Снаряд не выбирается — всегда тот
же, что закреплён за пользователем в блоке на объём на момент выполнения
(WorkoutRepository.resolve_next_targets), поэтому вход сюда возможен
только при непустой истории (иначе снаряда ещё нет)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_elective_result, format_equipment_label
from app.bot.keyboards import bottom_menu_keyboard, cancel_keyboard, elective_type_keyboard
from app.bot.parsing import ParseError, parse_int_sequence
from app.bot.states import ElectiveStates
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import (
    ELECTIVE_WEEK_WINDOW_DAYS,
    THREE_MINUTES_MAX_INTERVALS,
    W_LADDER,
    ElectiveType,
    available_elective_types,
    is_elective_allowed,
    volume_target_goal,
)
from app.services.elective_log import ElectiveLogService

router = Router()

_LABELS = {
    ElectiveType.MAX_REPS_LADDER: texts.ELECTIVE_LABEL_MAX_REPS_LADDER,
    ElectiveType.W_LADDER: texts.ELECTIVE_LABEL_W_LADDER,
    ElectiveType.THREE_MINUTES: texts.ELECTIVE_LABEL_THREE_MINUTES,
    ElectiveType.VOLUME_TARGET: texts.ELECTIVE_LABEL_VOLUME_TARGET,
}
_PROMPTS = {
    ElectiveType.MAX_REPS_LADDER: texts.ELECTIVE_PROMPT_MAX_REPS_LADDER,
    ElectiveType.W_LADDER: texts.ELECTIVE_PROMPT_W_LADDER,
    ElectiveType.THREE_MINUTES: texts.ELECTIVE_PROMPT_THREE_MINUTES,
    ElectiveType.VOLUME_TARGET: texts.ELECTIVE_PROMPT_VOLUME_TARGET,
}
# (мин, макс) чисел в последовательности — max_reps_ladder всегда ровно 4
# подхода (не останавливаются раньше по дизайну, в отличие от двух других).
_SEQUENCE_LIMITS: dict[ElectiveType, tuple[int, int]] = {
    ElectiveType.MAX_REPS_LADDER: (4, 4),
    ElectiveType.W_LADDER: (1, len(W_LADDER)),
    ElectiveType.THREE_MINUTES: (1, THREE_MINUTES_MAX_INTERVALS),
}


@router.callback_query(F.data == "electives_start")
async def handle_electives_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    if not history:
        await callback.answer(texts.ELECTIVE_NEEDS_FIRST_WORKOUT_TOAST, show_alert=True)
        return

    electives = ElectiveWorkoutRepository(session)
    week_ago = datetime.now(UTC) - timedelta(days=ELECTIVE_WEEK_WINDOW_DAYS)
    count_this_week = await electives.count_since(user.id, week_ago)
    if not is_elective_allowed(count_this_week):
        await callback.answer(texts.ELECTIVE_LIMIT_REACHED_TOAST, show_alert=True)
        return

    types_history = await electives.list_types_for_user(user.id)
    available = available_elective_types(types_history)

    await state.set_state(ElectiveStates.waiting_for_type)
    await callback.message.answer(texts.ELECTIVE_MENU_INTRO, reply_markup=elective_type_keyboard(available))
    await callback.answer()


@router.callback_query(ElectiveStates.waiting_for_type, F.data.startswith("elective:"))
async def handle_elective_type_choice(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    elective_type = ElectiveType(callback.data.removeprefix("elective:"))
    await callback.message.edit_reply_markup(reply_markup=None)

    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    target_a_state, _ = await WorkoutRepository(session).resolve_next_targets(user.id)

    await state.update_data(
        elective_type=elective_type.value,
        equipment_type=target_a_state.equipment_type.value,
        equipment_value=str(target_a_state.equipment_value) if target_a_state.equipment_value is not None else None,
        equipment_item_id=target_a_state.equipment_item_id,
    )
    equipment_label = format_equipment_label(target_a_state.equipment_type, target_a_state.equipment_value)
    label = _LABELS[elective_type]

    if elective_type == ElectiveType.VOLUME_TARGET:
        goal = volume_target_goal(target_a_state.target)
        await state.set_state(ElectiveStates.waiting_for_total)
        prompt = _PROMPTS[elective_type].format(label=label, equipment=equipment_label, goal=goal)
    else:
        await state.set_state(ElectiveStates.waiting_for_reps)
        prompt = _PROMPTS[elective_type].format(label=label, equipment=equipment_label)

    await callback.message.answer(prompt, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(ElectiveStates.waiting_for_reps)
async def handle_elective_reps(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    elective_type = ElectiveType(data["elective_type"])

    result = parse_int_sequence(message.text or "")
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    min_count, max_count = _SEQUENCE_LIMITS[elective_type]
    if len(result) < min_count or len(result) > max_count:
        if min_count == max_count:
            await message.answer(texts.ELECTIVE_SEQUENCE_COUNT_INVALID_EXACT.format(min=min_count))
        else:
            await message.answer(texts.ELECTIVE_SEQUENCE_COUNT_INVALID_RANGE.format(max=max_count))
        return

    await _finalize_elective(
        message, state, session, telegram_id=message.from_user.id,
        reps_sequence=result, total_reps=sum(result),
    )


@router.message(ElectiveStates.waiting_for_total)
async def handle_elective_total(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer(texts.ELECTIVE_TOTAL_INVALID)
        return

    await _finalize_elective(
        message, state, session, telegram_id=message.from_user.id,
        reps_sequence=None, total_reps=int(text),
    )


async def _finalize_elective(
    message: Message, state: FSMContext, session: AsyncSession, *,
    telegram_id: int, reps_sequence: list[int] | None, total_reps: int,
) -> None:
    data = await state.get_data()
    elective_type = ElectiveType(data["elective_type"])

    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)

    equipment_type = EquipmentType(data["equipment_type"])
    equipment_value = Decimal(data["equipment_value"]) if data.get("equipment_value") else None
    equipment_item_id = data.get("equipment_item_id")

    await ElectiveLogService(session).record(
        user_id=user.id, elective_type=elective_type, performed_at=datetime.now(UTC),
        total_reps=total_reps, reps_sequence=reps_sequence,
        equipment_type=equipment_type, equipment_value=equipment_value, equipment_item_id=equipment_item_id,
    )

    await state.clear()
    await message.answer(
        texts.ELECTIVE_DONE.format(
            label=_LABELS[elective_type],
            result=format_elective_result(reps_sequence, total_reps),
            equipment=format_equipment_label(equipment_type, equipment_value),
        ),
    )
    await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard())
