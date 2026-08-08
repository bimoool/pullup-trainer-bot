from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.handlers.subscription import send_paywall
from app.bot.keyboards import main_menu_keyboard, skip_comment_keyboard, workout_result_keyboard
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import NewBandStates, WorkoutStates
from app.db.models import BlockType
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import BLOCK_A, BLOCK_B
from app.domain.progression import next_weight_kg
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.services.workout_log import WorkoutLogService

router = Router()


@router.callback_query(F.data == "start_workout")
async def handle_start_workout(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    now = datetime.now(UTC)

    subscriptions = SubscriptionService(session)
    if not await subscriptions.has_access(user.id, now=now):
        await send_paywall(callback.message, user)
        await callback.answer()
        return

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)

    if history:
        last = history[-1]
        readiness = check_training_readiness(last.performed_at.date(), now.date())
        if readiness.status == TrainingReadiness.TOO_EARLY:
            await callback.message.answer(texts.TOO_EARLY_FOR_WORKOUT.format(ready_at=readiness.ready_at))
            await callback.answer()
            return
        if readiness.status in (TrainingReadiness.GAP_ROLLBACK, TrainingReadiness.GAP_RETEST_REQUIRED):
            # Откат/просрочка замера после долгого перерыва: domain.rules уже
            # умеет это определить, но применение отката к плану — отдельная
            # незакрытая задача (см. отчёт), сознательно не гадаю с ней здесь.
            await callback.message.answer(
                "Заметили большой перерыв — для такого случая пересчёт плана "
                "пока не подключен автоматически. Напишите в поддержку.",
            )
            await callback.answer()
            return

        last_block_a = next(b for b in last.blocks if b.block_type == BlockType.A)
        last_block_b = next(b for b in last.blocks if b.block_type == BlockType.B)
        target_a, target_b = last_block_a.target_after, last_block_b.target_after
        band_thickness_mm = last_block_a.band_thickness_mm
        weight_kg = last_block_b.weight_kg
        band_changed = last_block_a.equipment_changed
        weight_changed = last_block_b.equipment_changed
    else:
        target_a, target_b = BLOCK_A.base_target, BLOCK_B.base_target
        band_thickness_mm, weight_kg = None, Decimal(0)
        band_changed, weight_changed = False, False

    workout_sets = WorkoutSetRepository(session)
    active_set = await workout_sets.get_active_for_user(user.id)
    if active_set is None:
        await callback.message.answer("Нет активного сета — нужен новый замер. Напишите в поддержку.")
        await callback.answer()
        return

    if weight_changed and weight_kg is not None:
        weight_kg = Decimal(str(next_weight_kg(float(weight_kg))))

    await state.update_data(
        workout_set_id=active_set.id,
        target_a=target_a,
        target_b=target_b,
        band_thickness_mm=str(band_thickness_mm) if band_thickness_mm is not None else None,
        weight_kg=str(weight_kg),
    )

    if band_changed or band_thickness_mm is None:
        await state.set_state(NewBandStates.waiting_for_band_thickness)
        prompt = texts.NEW_BAND_THICKNESS_PROMPT if band_changed else texts.BAND_THICKNESS_PROMPT
        await callback.message.answer(prompt)
        await callback.answer()
        return

    await _send_plan(callback.message, state, target_a, target_b)
    await callback.answer()


async def _send_plan(message: Message, state: FSMContext, target_a: int, target_b: int) -> None:
    await message.answer(texts.WORKOUT_PLAN.format(target_a=target_a, target_b=target_b))
    await state.set_state(WorkoutStates.waiting_for_block_a)


@router.message(NewBandStates.waiting_for_band_thickness)
async def handle_new_band_thickness(message: Message, state: FSMContext) -> None:
    try:
        band_thickness_mm = Decimal((message.text or "").strip().replace(",", "."))
    except InvalidOperation:
        await message.answer(texts.BAND_THICKNESS_INVALID)
        return

    await state.update_data(band_thickness_mm=str(band_thickness_mm))
    data = await state.get_data()
    await _send_plan(message, state, data["target_a"], data["target_b"])


@router.message(WorkoutStates.waiting_for_block_a)
async def handle_block_a_result(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", BLOCK_A)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(WorkoutStates.waiting_for_block_b)
    await message.answer(texts.BLOCK_B_PROMPT)


@router.message(WorkoutStates.waiting_for_block_b)
async def handle_block_b_result(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", BLOCK_B)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_b_working_reps=list(result.working_reps), block_b_max_reps=result.max_reps)
    await state.set_state(WorkoutStates.waiting_for_comment)
    await message.answer(texts.COMMENT_PROMPT, reply_markup=skip_comment_keyboard())


@router.message(WorkoutStates.waiting_for_comment)
async def handle_comment_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _finalize_workout(message, state, session, comment=message.text)


@router.callback_query(WorkoutStates.waiting_for_comment, F.data == "skip_comment")
async def handle_skip_comment(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _finalize_workout(callback.message, state, session, comment=None)
    await callback.answer()


async def _finalize_workout(
    message: Message, state: FSMContext, session: AsyncSession, *, comment: str | None,
) -> None:
    data = await state.get_data()
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    block_a_reps = BlockLog(working_reps=tuple(data["block_a_working_reps"]), max_reps=data["block_a_max_reps"])
    block_b_reps = BlockLog(working_reps=tuple(data["block_b_working_reps"]), max_reps=data["block_b_max_reps"])

    log_service = WorkoutLogService(session)
    workout = await log_service.record_workout(
        user_id=user.id,
        workout_set_id=data["workout_set_id"],
        performed_at=datetime.now(UTC),
        block_a_reps=block_a_reps,
        block_b_reps=block_b_reps,
        band_thickness_mm=Decimal(data["band_thickness_mm"]),
        weight_kg=Decimal(data["weight_kg"]),
        comment=comment,
    )

    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    await message.answer(texts.BLOCK_RESULT_SUMMARY.format(max_reps=block_a.max_reps, new_target=block_a.target_after))
    if block_a.equipment_changed:
        await message.answer(texts.EQUIPMENT_CHANGED_BAND.format(new_target=block_a.target_after))
    await message.answer(texts.BLOCK_RESULT_SUMMARY.format(max_reps=block_b.max_reps, new_target=block_b.target_after))
    if block_b.equipment_changed:
        await message.answer(texts.EQUIPMENT_CHANGED_WEIGHT.format(new_target=block_b.target_after))

    await state.clear()
    await message.answer(texts.WORKOUT_DONE, reply_markup=workout_result_keyboard())
    await message.answer("Что дальше?", reply_markup=main_menu_keyboard())
