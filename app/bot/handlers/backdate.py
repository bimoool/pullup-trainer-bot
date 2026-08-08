from datetime import UTC, datetime
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import main_menu_keyboard
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import BackdateStates
from app.db.models import BlockType
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import BLOCK_A, BLOCK_B
from app.domain.rules import is_backdate_allowed
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService

router = Router()

BACKDATE_DATE_PROMPT = "На какую дату внести тренировку? Формат: ДД.ММ.ГГГГ (не глубже 7 дней назад)."
BACKDATE_DATE_INVALID = "Не понял дату — формат ДД.ММ.ГГГГ, например: 05.01.2026"
BACKDATE_TOO_OLD = "Эту дату внести нельзя — задним числом можно не глубже 7 дней."
BACKDATE_NO_ACTIVE_SET = "Нет активного сета — напишите в поддержку."
BACKDATE_DONE = "Тренировка внесена задним числом. Более поздние тренировки пересчитаны при необходимости."


@router.callback_query(F.data == "backdate_workout")
async def handle_backdate_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackdateStates.waiting_for_date)
    await callback.message.answer(BACKDATE_DATE_PROMPT)
    await callback.answer()


@router.message(BackdateStates.waiting_for_date)
async def handle_backdate_date(message: Message, state: FSMContext) -> None:
    try:
        parsed_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").replace(tzinfo=UTC)
    except ValueError:
        await message.answer(BACKDATE_DATE_INVALID)
        return

    today = datetime.now(UTC)
    if not is_backdate_allowed(parsed_date.date(), today.date()):
        await message.answer(BACKDATE_TOO_OLD)
        return

    await state.update_data(backdate_performed_at=parsed_date.isoformat())
    await state.set_state(BackdateStates.waiting_for_block_a)
    await message.answer(texts.BLOCK_A_PROMPT)


@router.message(BackdateStates.waiting_for_block_a)
async def handle_backdate_block_a(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", BLOCK_A)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(BackdateStates.waiting_for_block_b)
    await message.answer(texts.BLOCK_B_PROMPT)


@router.message(BackdateStates.waiting_for_block_b)
async def handle_backdate_block_b(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_block_result(message.text or "", BLOCK_B)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    workout_sets = WorkoutSetRepository(session)
    active_set = await workout_sets.get_active_for_user(user.id)
    if active_set is None:
        await message.answer(BACKDATE_NO_ACTIVE_SET)
        await state.clear()
        return

    # Снаряд на момент прошлой (пропущенной) тренировки отдельно не
    # спрашиваем — берём последний известный. Для типичного окна бэкдейта
    # (до 7 дней) снаряд почти наверняка не менялся; если менялся — это
    # известное упрощение, а не забытый случай.
    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    if history:
        last = history[-1]
        last_block_a = next(b for b in last.blocks if b.block_type == BlockType.A)
        last_block_b = next(b for b in last.blocks if b.block_type == BlockType.B)
        band_thickness_mm = last_block_a.band_thickness_mm or Decimal(0)
        weight_kg = last_block_b.weight_kg or Decimal(0)
    else:
        band_thickness_mm, weight_kg = Decimal(0), Decimal(0)

    block_a_reps = BlockLog(working_reps=tuple(data["block_a_working_reps"]), max_reps=data["block_a_max_reps"])
    performed_at = datetime.fromisoformat(data["backdate_performed_at"])

    log_service = WorkoutLogService(session)
    await log_service.record_workout(
        user_id=user.id,
        workout_set_id=active_set.id,
        performed_at=performed_at,
        block_a_reps=block_a_reps,
        block_b_reps=result,
        band_thickness_mm=band_thickness_mm,
        weight_kg=weight_kg,
    )

    await state.clear()
    await message.answer(BACKDATE_DONE)
    await message.answer("Что дальше?", reply_markup=main_menu_keyboard())
