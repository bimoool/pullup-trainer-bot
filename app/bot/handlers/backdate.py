from datetime import UTC, date, datetime
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import (
    format_anomaly_message,
    format_block_result,
    format_equipment_label,
    format_reps_example,
    format_sets_word,
)
from app.bot.handlers.equipment import _begin_equipment_setup
from app.bot.keyboards import (
    anomaly_confirm_keyboard,
    back_cancel_keyboard,
    backdate_date_keyboard,
    bottom_menu_keyboard,
)
from app.bot.parsing import ParseError, parse_reps
from app.bot.states import BackdateStates
from app.config import settings
from app.db.models import BlockType
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.anomalies import detect_anomalies
from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService, ensure_active_workout_set

router = Router()


def _format_block_a_prompt(target: int, work_sets: int) -> str:
    example_a = format_reps_example(target, work_sets)
    return texts.BLOCK_A_PROMPT.format(example=example_a, work_sets=work_sets, sets_word=format_sets_word(work_sets))


@router.callback_query(F.data == "backdate_workout")
async def handle_backdate_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    # Текущие цели считаются один раз здесь и кладутся в FSM — используются
    # только как пример формата ввода на следующих шагах (Часть 10, пакет
    # #2, п.10), не как реальная цель ЭТОЙ конкретной прошлой тренировки.
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    target_a_state, target_b_state = await WorkoutRepository(session).resolve_next_targets(user.id)

    await state.set_state(BackdateStates.waiting_for_date)
    await state.update_data(
        target_a=target_a_state.target, target_b=target_b_state.target, work_sets_a=target_a_state.work_sets,
    )
    await callback.message.answer(texts.BACKDATE_INTRO)
    await callback.message.answer(texts.BACKDATE_DATE_PROMPT, reply_markup=backdate_date_keyboard())
    await callback.answer()


@router.callback_query(F.data == "backdate_open_calendar")
async def handle_backdate_open_calendar(callback: CallbackQuery, session: AsyncSession) -> None:
    from app.bot.handlers.history import (
        render_calendar_month,  # деферред — см. комментарий в history.py
    )

    now = datetime.now(UTC)
    await render_calendar_month(callback, session, year=now.year, month=now.month, edit=False, mode="backdate")
    await callback.answer()


async def _proceed_with_backdate_date(message: Message, state: FSMContext, parsed_date: datetime) -> None:
    """Общий хвост после того, как дата бэкдейта известна и уже проверена
    (не будущая) — не важно, пришла она текстом (handle_backdate_date) или
    тапом по календарю (handle_calendar_date_picked, Часть 10, пакет #2,
    п.17): дальше сценарий один и тот же."""
    data = await state.get_data()
    await state.update_data(backdate_performed_at=parsed_date.isoformat())
    await state.set_state(BackdateStates.waiting_for_block_a)
    work_sets_a = data.get("work_sets_a", VOLUME_BLOCK.work_sets)
    await message.answer(
        _format_block_a_prompt(data["target_a"], work_sets_a), reply_markup=back_cancel_keyboard("backdate_back:date"),
    )


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

    await _proceed_with_backdate_date(message, state, parsed_date)


async def handle_calendar_date_picked(callback: CallbackQuery, state: FSMContext, picked_date: date) -> None:
    """Вызывается из history.py при тапе по дню в режиме "backdate" (Часть
    10, пакет #2, п.17) — та же проверка и переход, что при ручном вводе
    даты текстом (см. _proceed_with_backdate_date), источник даты другой."""
    if picked_date > datetime.now(UTC).date():
        await callback.answer(texts.BACKDATE_FUTURE_DATE, show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    parsed_date = datetime(picked_date.year, picked_date.month, picked_date.day, tzinfo=UTC)
    await _proceed_with_backdate_date(callback.message, state, parsed_date)
    await callback.answer()


@router.callback_query(F.data == "backdate_back:date")
async def handle_backdate_back_to_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackdateStates.waiting_for_date)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.BACKDATE_DATE_PROMPT, reply_markup=backdate_date_keyboard())
    await callback.answer()


async def _previous_avg_for_backdate(session: AsyncSession, telegram_id: int, block_type: BlockType, data: dict) -> float | None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)
    before = datetime.fromisoformat(data["backdate_performed_at"])
    return await WorkoutRepository(session).get_previous_avg_working(user.id, block_type, before=before)


@router.message(BackdateStates.waiting_for_block_a)
async def handle_backdate_block_a(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_reps(message.text or "")
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()
    previous_avg = await _previous_avg_for_backdate(session, message.from_user.id, BlockType.A, data)
    anomaly_text = format_anomaly_message(
        detect_anomalies(
            result, previous_avg_working=previous_avg,
            expected_work_sets=data.get("work_sets_a", VOLUME_BLOCK.work_sets),
        ),
    )
    if anomaly_text is not None:
        await state.update_data(anomaly_working_reps=list(result.working_reps), anomaly_max_reps=result.max_reps)
        await state.set_state(BackdateStates.waiting_for_block_a_confirm)
        await message.answer(anomaly_text, reply_markup=anomaly_confirm_keyboard())
        return

    await _apply_backdate_block_a(message, state, result)


async def _apply_backdate_block_a(message: Message, state: FSMContext, result: BlockLog) -> None:
    data = await state.get_data()
    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(BackdateStates.waiting_for_block_b)
    example_b = format_reps_example(data["target_b"], STRENGTH_BLOCK.work_sets)
    await message.answer(
        texts.BLOCK_B_PROMPT.format(example=example_b), reply_markup=back_cancel_keyboard("backdate_back:block_a"),
    )


@router.callback_query(BackdateStates.waiting_for_block_a_confirm, F.data == "anomaly:confirm")
async def handle_backdate_block_a_anomaly_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    result = BlockLog(working_reps=tuple(data["anomaly_working_reps"]), max_reps=data["anomaly_max_reps"])
    await callback.message.edit_reply_markup(reply_markup=None)
    await _apply_backdate_block_a(callback.message, state, result)
    await callback.answer()


@router.callback_query(BackdateStates.waiting_for_block_a_confirm, F.data == "anomaly:reenter")
async def handle_backdate_block_a_anomaly_reenter(callback: CallbackQuery, state: FSMContext) -> None:
    await _resend_backdate_block_a_prompt(callback, state)


@router.callback_query(F.data == "backdate_back:block_a")
async def handle_backdate_back_to_block_a(callback: CallbackQuery, state: FSMContext) -> None:
    await _resend_backdate_block_a_prompt(callback, state)


async def _resend_backdate_block_a_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(BackdateStates.waiting_for_block_a)
    await callback.message.edit_reply_markup(reply_markup=None)
    work_sets_a = data.get("work_sets_a", VOLUME_BLOCK.work_sets)
    await callback.message.answer(
        _format_block_a_prompt(data["target_a"], work_sets_a),
        reply_markup=back_cancel_keyboard("backdate_back:date"),
    )
    await callback.answer()


@router.message(BackdateStates.waiting_for_block_b)
async def handle_backdate_block_b(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = parse_reps(message.text or "")
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()
    previous_avg = await _previous_avg_for_backdate(session, message.from_user.id, BlockType.B, data)
    anomaly_text = format_anomaly_message(
        detect_anomalies(result, previous_avg_working=previous_avg, expected_work_sets=STRENGTH_BLOCK.work_sets),
    )
    if anomaly_text is not None:
        await state.update_data(anomaly_working_reps=list(result.working_reps), anomaly_max_reps=result.max_reps)
        await state.set_state(BackdateStates.waiting_for_block_b_confirm)
        await message.answer(anomaly_text, reply_markup=anomaly_confirm_keyboard())
        return

    await _apply_backdate_block_b(message, state, session, result, telegram_id=message.from_user.id)


async def _apply_backdate_block_b(
    message: Message, state: FSMContext, session: AsyncSession, result: BlockLog, *, telegram_id: int,
) -> None:
    data = await state.get_data()

    # Снаряд на момент прошлой (пропущенной) тренировки теперь спрашивается
    # явно, той же очередью, что и в живой тренировке (Часть 8) — раньше
    # тихо наследовался последний известный, что путало пользователей,
    # которые реально меняли снаряд между тренировками.
    await _begin_equipment_setup(
        message, state, session,
        flow="backdate",
        target_a_state=None, target_b_state=None,
        telegram_id=telegram_id,
        baseline_reps=None,
        extra_data={
            "backdate_performed_at": data["backdate_performed_at"],
            "block_a_working_reps": data["block_a_working_reps"],
            "block_a_max_reps": data["block_a_max_reps"],
            "block_b_working_reps": list(result.working_reps),
            "block_b_max_reps": result.max_reps,
        },
    )


@router.callback_query(BackdateStates.waiting_for_block_b_confirm, F.data == "anomaly:confirm")
async def handle_backdate_block_b_anomaly_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    result = BlockLog(working_reps=tuple(data["anomaly_working_reps"]), max_reps=data["anomaly_max_reps"])
    await callback.message.edit_reply_markup(reply_markup=None)
    # telegram_id — явно от callback.from_user, НЕ от callback.message.from_user
    # (это бот, см. критический баг Части 10 — тот же источник ошибки,
    # здесь предотвращён заранее, а не найден постфактум в проде).
    await _apply_backdate_block_b(callback.message, state, session, result, telegram_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(BackdateStates.waiting_for_block_b_confirm, F.data == "anomaly:reenter")
async def handle_backdate_block_b_anomaly_reenter(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(BackdateStates.waiting_for_block_b)
    await callback.message.edit_reply_markup(reply_markup=None)
    example_b = format_reps_example(data["target_b"], STRENGTH_BLOCK.work_sets)
    await callback.message.answer(
        texts.BLOCK_B_PROMPT.format(example=example_b), reply_markup=back_cancel_keyboard("backdate_back:block_a"),
    )
    await callback.answer()


async def finalize_backdated_workout(
    message: Message, state: FSMContext, session: AsyncSession, data: dict, *, telegram_id: int,
) -> None:
    """Вызывается из equipment.py, когда очередь снаряда для бэкдейта
    опустела (см. _complete_equipment_queue) — здесь уже есть и повторения
    обоих блоков, и выбранный снаряд, можно записывать.

    telegram_id передаётся явно от исходного вызова _begin_equipment_setup
    (см. комментарий там) — message здесь почти всегда callback.message
    (последний шаг очереди снаряда почти всегда завершается кнопкой), а у
    него from_user — бот, не пользователь."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)

    active_set = await ensure_active_workout_set(session, user.id)
    if active_set is None:
        await message.answer(texts.NO_ACTIVE_SET_SUPPORT)
        await state.clear()
        return

    equipment_results = data["equipment_results"]
    block_a_equipment_type = EquipmentType(equipment_results["a"]["type"])
    block_a_equipment_value = Decimal(equipment_results["a"]["value"]) if equipment_results["a"]["value"] else None
    block_a_equipment_item_id = equipment_results["a"]["item_id"]
    block_b_equipment_type = EquipmentType(equipment_results["b"]["type"])
    block_b_equipment_value = Decimal(equipment_results["b"]["value"]) if equipment_results["b"]["value"] else None
    block_b_equipment_item_id = equipment_results["b"]["item_id"]

    block_a_reps = BlockLog(working_reps=tuple(data["block_a_working_reps"]), max_reps=data["block_a_max_reps"])
    block_b_reps = BlockLog(working_reps=tuple(data["block_b_working_reps"]), max_reps=data["block_b_max_reps"])
    performed_at = datetime.fromisoformat(data["backdate_performed_at"])

    log_service = WorkoutLogService(session)
    workout = await log_service.record_backdated_workout(
        user_id=user.id,
        workout_set_id=active_set.id,
        performed_at=performed_at,
        block_a_reps=block_a_reps,
        block_b_reps=block_b_reps,
        block_a_equipment_type=block_a_equipment_type,
        block_a_equipment_value=block_a_equipment_value,
        block_b_equipment_type=block_b_equipment_type,
        block_b_equipment_value=block_b_equipment_value,
        block_a_equipment_item_id=block_a_equipment_item_id,
        block_b_equipment_item_id=block_b_equipment_item_id,
    )

    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    await state.clear()
    await message.answer(
        texts.BACKDATE_DONE.format(
            result_a=format_block_result(block_a.working_reps, block_a.max_reps),
            result_b=format_block_result(block_b.working_reps, block_b.max_reps),
            equipment_a=format_equipment_label(block_a.equipment_type, block_a.equipment_value),
            equipment_b=format_equipment_label(block_b.equipment_type, block_b.equipment_value),
        ),
    )
    await message.answer(texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard(is_admin=settings.is_admin(telegram_id)))
