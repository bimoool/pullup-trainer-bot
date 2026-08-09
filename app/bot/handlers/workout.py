from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_set_close_report
from app.bot.handlers.subscription import send_paywall
from app.bot.keyboards import (
    back_cancel_keyboard,
    cancel_keyboard,
    equipment_type_keyboard,
    skip_comment_keyboard,
    workout_result_keyboard,
)
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import EquipmentStates, RetestStates, WorkoutStates
from app.db.models import Block, BlockType, WorkoutSet, WorkoutSetStatus
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import NextBlockState, WorkoutRepository
from app.domain.constants import SET_LENGTH, STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.progression import rollback_signed_load, rollback_target, suggest_starting_equipment
from app.domain.reports import set_close_summary
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.services.workout_log import WorkoutLogService

router = Router()

_BLOCK_LABELS = {"a": "блоке на объём", "b": "блоке на силу"}


async def _ensure_active_workout_set(session: AsyncSession, user_id: int) -> WorkoutSet | None:
    """Сет закрывается автоматически по достижении SET_LENGTH тренировок
    (WorkoutSetRepository.increment_completed) — раньше это означало тупик
    "нет активного сета, напишите в поддержку". Сеты — это просто окно
    отчётности на 12 тренировок, они не должны блокировать тренировки,
    поэтому следующий сет открывается автоматически от последнего замера."""
    workout_sets = WorkoutSetRepository(session)
    active = await workout_sets.get_active_for_user(user_id)
    if active is not None:
        return active

    baseline = await BaselineRepository(session).get_latest_for_user(user_id)
    if baseline is None:
        return None
    return await workout_sets.create(user_id=user_id, started_from_baseline_id=baseline.id)


@router.callback_query(F.data == "show_plan")
async def handle_show_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    """Посмотреть текущий план, не начиная тренировку — снаряд здесь не
    уточняем (это делает сама тренировка), только цели по повторениям."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    target_a_state, target_b_state = await workouts.resolve_next_targets(user.id)

    await callback.message.answer(
        texts.CURRENT_PLAN.format(target_a=target_a_state.target, target_b=target_b_state.target),
    )
    await callback.answer()


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

    readiness = None
    if history:
        readiness = check_training_readiness(history[-1].performed_at.date(), now.date())
        if readiness.status == TrainingReadiness.TOO_EARLY:
            await callback.message.answer(texts.TOO_EARLY_FOR_WORKOUT.format(ready_at=readiness.ready_at))
            await callback.answer()
            return
        if readiness.status == TrainingReadiness.GAP_RETEST_REQUIRED:
            await state.set_state(RetestStates.waiting_for_baseline_reps)
            await callback.message.answer(
                texts.RETEST_REQUIRED.format(days_since=readiness.days_since_last_workout),
                reply_markup=cancel_keyboard(),
            )
            await callback.answer()
            return

    active_set = await _ensure_active_workout_set(session, user.id)
    if active_set is None:
        await callback.message.answer(texts.NO_ACTIVE_SET_SUPPORT)
        await callback.answer()
        return

    target_a_state, target_b_state = await workouts.resolve_next_targets(user.id)
    target_a_override: int | None = None

    if readiness is not None and readiness.status == TrainingReadiness.GAP_ROLLBACK:
        target_a_override = rollback_target(target_a_state.target)
        load_hint = _rolled_back_load_hint(target_b_state)
        if load_hint is None:
            notice = texts.GAP_ROLLBACK_NOTICE_NO_LOAD.format(days_since=readiness.days_since_last_workout)
        else:
            suggested_load, previous_load = load_hint
            notice = texts.GAP_ROLLBACK_NOTICE.format(
                days_since=readiness.days_since_last_workout,
                suggested_load=suggested_load, previous_load=previous_load,
            )
        await callback.message.answer(notice)

    baseline_reps = None
    if not history:
        baseline = await BaselineRepository(session).get_latest_for_user(user.id)
        baseline_reps = baseline.reps if baseline is not None else 0

    await _begin_equipment_setup(
        callback.message, state,
        workout_set_id=active_set.id,
        target_a=target_a_state.target, target_b=target_b_state.target,
        target_a_override=target_a_override, target_b_override=None,
        target_a_state=target_a_state, target_b_state=target_b_state,
        baseline_reps=baseline_reps,
    )
    await callback.answer()


def _rolled_back_load_hint(target_b_state: NextBlockState) -> tuple[str, str] | None:
    """Только подсказка в тексте — пользователь всё равно вводит фактически
    использованный снаряд сам на этапе EquipmentStates. Направление считает
    rollback_signed_load (через знаковую шкалу — для резины "легче" значит
    БОЛЬШЕ кг сопротивления, для веса МЕНЬШЕ, наивное умножение модуля на
    0.9 в обе стороны было ошибкой, см. историю). None — снаряд без числа
    (свой вес), подсказывать нечего."""
    if target_b_state.equipment_value is None:
        return None
    previous = target_b_state.equipment_value
    suggested = rollback_signed_load(target_b_state.equipment_type, previous)
    return f"{suggested:.1f}", f"{previous:.1f}"


@router.message(RetestStates.waiting_for_baseline_reps)
async def handle_retest_baseline(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(texts.BASELINE_INVALID)
        return
    reps = int(text)

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=reps)

    active_set = await _ensure_active_workout_set(session, user.id)
    if active_set is None:
        await message.answer(texts.NO_ACTIVE_SET_SUPPORT)
        await state.clear()
        return

    await message.answer(texts.RETEST_DONE.format(reps=reps))
    await _begin_equipment_setup(
        message, state,
        workout_set_id=active_set.id,
        target_a=VOLUME_BLOCK.base_target, target_b=STRENGTH_BLOCK.base_target,
        target_a_override=VOLUME_BLOCK.base_target, target_b_override=STRENGTH_BLOCK.base_target,
        target_a_state=None, target_b_state=None,
        baseline_reps=reps,
    )


async def _begin_equipment_setup(
    message: Message,
    state: FSMContext,
    *,
    workout_set_id: int,
    target_a: int,
    target_b: int,
    target_a_override: int | None,
    target_b_override: int | None,
    target_a_state: NextBlockState | None,
    target_b_state: NextBlockState | None,
    baseline_reps: int | None,
) -> None:
    """target_*_state=None форсирует переспрос снаряда для обоих блоков
    (первая тренировка / ретест) — иначе очередь строится по
    needs_new_equipment каждого блока (обычное продолжение)."""
    equipment_queue: list[str] = []
    equipment_results: dict[str, dict[str, str | None]] = {}

    for key, block_state in (("a", target_a_state), ("b", target_b_state)):
        if block_state is None or block_state.needs_new_equipment:
            equipment_queue.append(key)
        else:
            equipment_results[key] = {
                "type": block_state.equipment_type.value,
                "value": str(block_state.equipment_value) if block_state.equipment_value is not None else None,
            }

    await state.update_data(
        workout_set_id=workout_set_id,
        target_a=target_a, target_b=target_b,
        target_a_override=target_a_override, target_b_override=target_b_override,
        equipment_queue=equipment_queue, equipment_results=equipment_results,
        baseline_reps=baseline_reps,
    )
    await _advance_equipment_queue(message, state)


async def _advance_equipment_queue(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    queue: list[str] = data["equipment_queue"]

    if not queue:
        await _send_plan(message, state, data["target_a"], data["target_b"])
        return

    block_key = queue[0]
    await state.set_state(EquipmentStates.waiting_for_type)

    # baseline_reps выставлен только для самой первой тренировки/ретеста
    # (см. _begin_equipment_setup) — во всех остальных случаях None, и
    # подсказка снаряда по замеру не показывается.
    if data.get("baseline_reps") is not None:
        suggested_a, suggested_b = suggest_starting_equipment(data["baseline_reps"])
        suggested = suggested_a if block_key == "a" else suggested_b
        suggested_label = "свой вес" if suggested == EquipmentType.BODYWEIGHT else "резина"
        prompt = texts.EQUIPMENT_TYPE_PROMPT_FIRST.format(
            block_label=_BLOCK_LABELS[block_key], baseline_reps=data["baseline_reps"], suggested=suggested_label,
        )
    else:
        prompt = texts.EQUIPMENT_TYPE_PROMPT_CHANGE.format(block_label=_BLOCK_LABELS[block_key])

    await message.answer(prompt, reply_markup=equipment_type_keyboard())


@router.callback_query(EquipmentStates.waiting_for_type, F.data.startswith("equip:"))
async def handle_equipment_type_choice(callback: CallbackQuery, state: FSMContext) -> None:
    equipment_type = EquipmentType(callback.data.removeprefix("equip:"))
    data = await state.get_data()
    block_key = data["equipment_queue"][0]

    if equipment_type == EquipmentType.BODYWEIGHT:
        results = data["equipment_results"]
        results[block_key] = {"type": equipment_type.value, "value": None}
        queue = data["equipment_queue"][1:]
        await state.update_data(equipment_results=results, equipment_queue=queue)
        await _advance_equipment_queue(callback.message, state)
        await callback.answer()
        return

    await state.update_data(pending_equipment_type=equipment_type.value)
    await state.set_state(EquipmentStates.waiting_for_value)
    prompt = texts.EQUIPMENT_VALUE_PROMPT_BAND if equipment_type == EquipmentType.BAND else texts.EQUIPMENT_VALUE_PROMPT_WEIGHT
    await callback.message.answer(prompt, reply_markup=back_cancel_keyboard("equip_back:type"))
    await callback.answer()


@router.callback_query(F.data == "equip_back:type")
async def handle_equipment_back_to_type(callback: CallbackQuery, state: FSMContext) -> None:
    # Очередь не изменялась при переходе type -> value (позиция в
    # equipment_queue снимается только после успешного выбора) — повторный
    # вызов _advance_equipment_queue просто переспрашивает тип для того же
    # блока, ничего дополнительно восстанавливать не нужно.
    await _advance_equipment_queue(callback.message, state)
    await callback.answer()


@router.message(EquipmentStates.waiting_for_value)
async def handle_equipment_value(message: Message, state: FSMContext) -> None:
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
    results[block_key] = {"type": data["pending_equipment_type"], "value": str(value)}
    queue = data["equipment_queue"][1:]

    await state.update_data(equipment_results=results, equipment_queue=queue)
    await _advance_equipment_queue(message, state)


async def _send_plan(message: Message, state: FSMContext, target_a: int, target_b: int) -> None:
    await message.answer(texts.WORKOUT_PLAN.format(target_a=target_a, target_b=target_b), reply_markup=cancel_keyboard())
    await state.set_state(WorkoutStates.waiting_for_block_a)


@router.message(WorkoutStates.waiting_for_block_a)
async def handle_block_a_result(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", VOLUME_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(WorkoutStates.waiting_for_block_b)
    await message.answer(texts.BLOCK_B_PROMPT, reply_markup=back_cancel_keyboard("wk_back:block_a"))


@router.message(WorkoutStates.waiting_for_block_b)
async def handle_block_b_result(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", STRENGTH_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    await state.update_data(block_b_working_reps=list(result.working_reps), block_b_max_reps=result.max_reps)
    await state.set_state(WorkoutStates.waiting_for_comment)
    await message.answer(texts.COMMENT_PROMPT, reply_markup=skip_comment_keyboard("wk_back:block_b"))


@router.callback_query(F.data == "wk_back:block_a")
async def handle_back_to_block_a(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await _send_plan(callback.message, state, data["target_a"], data["target_b"])
    await callback.answer()


@router.callback_query(F.data == "wk_back:block_b")
async def handle_back_to_block_b(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WorkoutStates.waiting_for_block_b)
    await callback.message.answer(texts.BLOCK_B_PROMPT, reply_markup=back_cancel_keyboard("wk_back:block_a"))
    await callback.answer()


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
    equipment_results = data["equipment_results"]
    block_a_equipment_type = EquipmentType(equipment_results["a"]["type"])
    block_a_equipment_value = Decimal(equipment_results["a"]["value"]) if equipment_results["a"]["value"] else None
    block_b_equipment_type = EquipmentType(equipment_results["b"]["type"])
    block_b_equipment_value = Decimal(equipment_results["b"]["value"]) if equipment_results["b"]["value"] else None

    log_service = WorkoutLogService(session)
    workout = await log_service.record_workout(
        user_id=user.id,
        workout_set_id=data["workout_set_id"],
        performed_at=datetime.now(UTC),
        block_a_reps=block_a_reps,
        block_b_reps=block_b_reps,
        block_a_equipment_type=block_a_equipment_type,
        block_a_equipment_value=block_a_equipment_value,
        block_b_equipment_type=block_b_equipment_type,
        block_b_equipment_value=block_b_equipment_value,
        target_a_override=data.get("target_a_override"),
        target_b_override=data.get("target_b_override"),
        comment=comment,
    )

    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    # Одно сообщение вместо разбора по блокам (см. Часть 4 респека) —
    # статистика и подробности ушли в «Прогресс», здесь только
    # подбадривание и цели на следующую тренировку.
    summary = texts.WORKOUT_SUMMARY.format(target_a=block_a.target_after, target_b=block_b.target_after)
    summary += _block_outcome_suffix(block_a) + _block_outcome_suffix(block_b)

    await state.clear()
    await message.answer(summary, reply_markup=workout_result_keyboard())

    # "По закрытии сета (12 тренировок) — большой отчёт" (Часть 5 респека).
    # increment_completed переводит сет в COMPLETED ровно на этой тренировке
    # (12-й) — новые тренировки уходят уже в следующий сет, поэтому этот
    # флаг не сработает повторно на будущих записях.
    workout_set = await WorkoutSetRepository(session).get_by_id(workout.workout_set_id)
    if workout_set.status == WorkoutSetStatus.COMPLETED:
        await _send_set_close_report(message, session, user.id, workout.workout_set_id)


async def _send_set_close_report(message: Message, session: AsyncSession, user_id: int, workout_set_id: int) -> None:
    workouts = WorkoutRepository(session)
    workout_sets = WorkoutSetRepository(session)

    records_in_set = await workouts.list_records_for_set(workout_set_id)
    all_sets = await workout_sets.list_for_user(user_id)
    position = next(i for i, s in enumerate(all_sets) if s.id == workout_set_id)

    previous_set_volume = None
    if position > 0:
        previous_records = await workouts.list_records_for_set(all_sets[position - 1].id)
        previous_set_volume = sum(r.block_a.log.volume + r.block_b.log.volume for r in previous_records)

    summary = set_close_summary(records_in_set, previous_set_volume)
    await message.answer(format_set_close_report(summary, SET_LENGTH))


def _block_outcome_suffix(block: Block) -> str:
    if block.transition_failed:
        return texts.TRANSITION_FAILED_SUFFIX
    if block.equipment_changed:
        return texts.EQUIPMENT_CHANGED_SUFFIX
    if block.equipment_type == EquipmentType.BODYWEIGHT and block.target_after == VOLUME_BLOCK.bodyweight_ceiling:
        return texts.CEILING_REACHED_SUFFIX
    return ""
