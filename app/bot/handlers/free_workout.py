"""«➕ Внести свободные подтягивания» (Часть 10, п. 18) — произвольная
тренировка вне схемы: не в плане и не в цикле из 12, но попадает в
статистику/объём (см. WorkoutRepository.record_free_workout)."""

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.handlers.workout import _ensure_active_workout_set
from app.bot.keyboards import bottom_menu_keyboard, cancel_keyboard
from app.bot.states import FreeWorkoutStates
from app.db.repositories.users import UserRepository
from app.services.workout_log import WorkoutLogService

router = Router()

MAX_REASONABLE_REPS = 200


@router.callback_query(F.data == "free_workout_start")
async def handle_free_workout_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FreeWorkoutStates.waiting_for_reps)
    await callback.message.answer(texts.FREE_WORKOUT_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(FreeWorkoutStates.waiting_for_reps)
async def handle_free_workout_reps(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) > MAX_REASONABLE_REPS:
        await message.answer(texts.FREE_WORKOUT_INVALID)
        return
    reps = int(text)

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    active_set = await _ensure_active_workout_set(session, user.id)
    if active_set is None:
        await message.answer(texts.NO_ACTIVE_SET_SUPPORT)
        await state.clear()
        return

    await WorkoutLogService(session).record_free_workout(
        user_id=user.id, workout_set_id=active_set.id, performed_at=datetime.now(UTC), reps=reps,
    )

    await state.clear()
    await message.answer(texts.FREE_WORKOUT_DONE.format(reps=reps))
    await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard())
