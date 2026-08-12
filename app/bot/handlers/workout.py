import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_equipment_label, format_reps_example, format_set_close_report
from app.bot.handlers.equipment import _begin_equipment_setup
from app.bot.handlers.subscription import send_paywall
from app.bot.keyboards import (
    back_cancel_keyboard,
    cancel_keyboard,
    end_cycle_confirm_keyboard,
    optional_exercise_keyboard,
    skip_comment_keyboard,
    workout_result_keyboard,
)
from app.bot.parsing import ParseError, parse_block_result
from app.bot.states import RetestStates, WorkoutStates
from app.config import settings
from app.db.models import Block, BlockType, WorkoutSet, WorkoutSetStatus
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import NextBlockState, WorkoutRepository
from app.domain.constants import (
    MIN_REST_DAYS,
    SET_LENGTH,
    STRENGTH_BLOCK,
    VOLUME_BLOCK,
    EquipmentType,
)
from app.domain.progression import initial_volume_target, rollback_signed_load, rollback_target
from app.domain.reports import set_close_summary
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.services.workout_log import WorkoutLogService

router = Router()


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


@router.callback_query(F.data == "end_cycle_prompt")
async def handle_end_cycle_prompt(callback: CallbackQuery, session: AsyncSession) -> None:
    """Добровольное завершение цикла раньше 12 тренировок — доступно из
    «Профиль» в любой момент. Ничего не меняем здесь, только предупреждаем;
    реальное действие — только после явного подтверждения ниже."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    active_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    if active_set is None:
        await callback.answer(texts.END_CYCLE_NOTHING_ACTIVE, show_alert=True)
        return

    await callback.message.answer(texts.END_CYCLE_WARNING, reply_markup=end_cycle_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data == "end_cycle_cancel")
async def handle_end_cycle_cancel(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(texts.CANCELLED)


@router.callback_query(F.data == "end_cycle_confirm")
async def handle_end_cycle_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Закрывает активный WorkoutSet статусом ABANDONED (тот же статус и
    метод, что уже существовали для этого случая — WorkoutSetRepository.
    mark_abandoned, просто раньше не был подключён ни к одному сценарию) и
    переиспользует ретест-флоу: то же состояние RetestStates и тот же
    handle_retest_baseline, что и при просроченном замере — он сам заведёт
    новый Baseline, новый WorkoutSet (см. _ensure_active_workout_set) и
    сбросит цели/снаряд на стартовые. Старые тренировки никуда не деваются
    и не архивируются отдельно — они уже физически отделены от нового
    цикла через workout_set_id закрытого сета; История/Прогресс/Отчёты
    продолжают показывать полную непрерывную историю пользователя, как и
    раньше — это не отдельные "циклы" для них, а один и тот же трекинг."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workout_sets = WorkoutSetRepository(session)
    active_set = await workout_sets.get_active_for_user(user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    if active_set is None:
        await callback.answer(texts.END_CYCLE_NOTHING_ACTIVE, show_alert=True)
        return

    await workout_sets.mark_abandoned(active_set.id, abandoned_at=datetime.now(UTC))

    await state.set_state(RetestStates.waiting_for_baseline_reps)
    await callback.message.answer(texts.END_CYCLE_DONE)
    await callback.message.answer(texts.BASELINE_GUIDE)
    await callback.answer()


@router.callback_query(F.data == "show_plan")
async def handle_show_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    """Посмотреть текущий план, не начиная тренировку. Снаряд показывается
    сразу (Часть 10, пакет #2, п.9) — это уже закреплённый за пользователем
    снаряд с прошлой тренировки, не новый выбор, человек может заранее
    подготовить инвентарь."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    workouts = WorkoutRepository(session)
    is_admin = settings.is_admin(callback.from_user.id)
    target_a_state, target_b_state = await workouts.resolve_next_targets(
        user.id, bypass_transition_wait=is_admin,
    )

    # Для ещё ни разу не тренировавшегося пользователя resolve_next_targets
    # флэтом отдаёт VOLUME_BLOCK.base_target — не учитывает "замер минус
    # 25%" (Часть 10, пакет #2, п.14), которое реально применится при
    # старте (см. handle_start_workout). Показываем ту же скорректированную
    # цифру здесь, иначе "Текущий план" разойдётся с тем, что будет на деле.
    target_a = target_a_state.target
    if not await workouts.list_for_user(user.id):
        baseline = await BaselineRepository(session).get_latest_for_user(user.id)
        if baseline is not None:
            target_a = initial_volume_target(baseline.reps)

    await callback.message.answer(
        texts.CURRENT_PLAN.format(
            target_a=target_a, target_b=target_b_state.target,
            equipment_a=format_equipment_label(target_a_state.equipment_type, target_a_state.equipment_value),
            equipment_b=format_equipment_label(target_b_state.equipment_type, target_b_state.equipment_value),
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "start_workout")
async def handle_start_workout(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    now = datetime.now(UTC)
    is_admin = settings.is_admin(callback.from_user.id)

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
        # Обход минимального отдыха — только для admin_ids (Часть 9),
        # ускоряет ручное тестирование; check_training_readiness (домен)
        # не меняется и продолжает считать TOO_EARLY как обычно.
        if readiness.status == TrainingReadiness.TOO_EARLY and not is_admin:
            # Таймер + дата/время (Часть 10, пакет #2, п.23) — домен считает
            # только по date (check_training_readiness), а тут для реального
            # "сколько ждать" в часах нужна полная дата-время последней
            # тренировки, поэтому здесь, не в домене (презентационный расчёт,
            # не влияет на саму логику готовности).
            ready_at_dt = history[-1].performed_at + timedelta(days=MIN_REST_DAYS)
            hours_left = max(0, math.ceil((ready_at_dt - now).total_seconds() / 3600))
            await callback.message.answer(
                texts.TOO_EARLY_FOR_WORKOUT.format(
                    hours_left=hours_left,
                    ready_date=ready_at_dt.strftime("%d.%m"),
                    ready_time=ready_at_dt.strftime("%H:%M"),
                ),
            )
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

    target_a_state, target_b_state = await workouts.resolve_next_targets(user.id, bypass_transition_wait=is_admin)
    target_a_override: int | None = None

    if readiness is not None and readiness.status == TrainingReadiness.GAP_ROLLBACK:
        target_a_override = rollback_target(target_a_state.target)
        load_hint = await _rolled_back_load_hint(session, target_b_state)
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
        # "Замер минус 25%" (Часть 10, пакет #2, п.14) — только при первом
        # старте (target_a_override иначе не выставлен вовсе, target_a_state
        # уже даёт VOLUME_BLOCK.base_target флэтом из _resolve_next_state
        # для пустой истории — здесь его переопределяем).
        target_a_override = initial_volume_target(baseline_reps)

    target_a_for_display = target_a_override if target_a_override is not None else target_a_state.target
    await _begin_equipment_setup(
        callback.message, state, session,
        flow="live",
        target_a_state=target_a_state, target_b_state=target_b_state,
        telegram_id=callback.from_user.id,
        baseline_reps=baseline_reps,
        extra_data={
            "workout_set_id": active_set.id,
            "target_a": target_a_for_display, "target_b": target_b_state.target,
            "target_a_override": target_a_override, "target_b_override": None,
        },
    )
    await callback.answer()


async def _rolled_back_load_hint(session: AsyncSession, target_b_state: NextBlockState) -> tuple[str, str] | None:
    """Только подсказка в тексте — пользователь всё равно вводит фактически
    использованный снаряд сам на этапе EquipmentStates. Направление считает
    rollback_signed_load (через знаковую шкалу — для резины "легче" значит
    БОЛЬШЕ кг сопротивления, для веса МЕНЬШЕ, наивное умножение модуля на
    0.9 в обе стороны было ошибкой, см. историю). None — снаряд без числа
    вообще (свой вес/австралийские) или резина с неизвестным кг — подсказывать
    нечего.

    Для резины equipment_value на Block больше не хранится (Часть 8 —
    личный список), реальное кг (если известно) нужно достать через
    equipment_item_id из EquipmentItemRepository — просто NextBlockState.
    equipment_value тут всегда None для BAND."""
    if target_b_state.equipment_type == EquipmentType.BAND:
        if target_b_state.equipment_item_id is None:
            return None
        item = await EquipmentItemRepository(session).get_by_id(target_b_state.equipment_item_id)
        previous_value = item.resistance_kg if item is not None else None
    else:
        previous_value = target_b_state.equipment_value

    if previous_value is None:
        return None
    suggested = rollback_signed_load(target_b_state.equipment_type, previous_value)
    return f"{suggested:.1f}", f"{previous_value:.1f}"


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
    # "Замер минус 25%" (Часть 10, пакет #2, п.14) — та же логика, что при
    # первой тренировке нового пользователя, см. handle_start_workout.
    target_a = initial_volume_target(reps)
    await _begin_equipment_setup(
        message, state, session,
        flow="live",
        target_a_state=None, target_b_state=None,
        telegram_id=message.from_user.id,
        baseline_reps=reps,
        extra_data={
            "workout_set_id": active_set.id,
            "target_a": target_a, "target_b": STRENGTH_BLOCK.base_target,
            "target_a_override": target_a, "target_b_override": STRENGTH_BLOCK.base_target,
        },
    )


async def _send_plan(message: Message, state: FSMContext, target_a: int, target_b: int) -> None:
    example_a = format_reps_example(target_a, VOLUME_BLOCK.work_sets)
    await message.answer(
        texts.WORKOUT_PLAN.format(target_a=target_a, target_b=target_b, example_a=example_a),
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(WorkoutStates.waiting_for_block_a)


@router.message(WorkoutStates.waiting_for_block_a)
async def handle_block_a_result(message: Message, state: FSMContext) -> None:
    result = parse_block_result(message.text or "", VOLUME_BLOCK)
    if isinstance(result, ParseError):
        await message.answer(result.message)
        return

    data = await state.get_data()
    await state.update_data(block_a_working_reps=list(result.working_reps), block_a_max_reps=result.max_reps)
    await state.set_state(WorkoutStates.waiting_for_block_b)
    # Предложение факультативной нагрузки на отдыхе — перед приглашением к
    # блоку на силу (Часть 10, п. 20), не блокирует переход дальше.
    await message.answer(texts.OPTIONAL_EXERCISE_OFFER, reply_markup=optional_exercise_keyboard())
    example_b = format_reps_example(data["target_b"], STRENGTH_BLOCK.work_sets)
    await message.answer(
        texts.BLOCK_B_PROMPT.format(example=example_b), reply_markup=back_cancel_keyboard("wk_back:block_a"),
    )


@router.callback_query(F.data == "optional_exercise:want")
async def handle_optional_exercise_want(callback: CallbackQuery) -> None:
    # Баг из живого тестирования (Часть 10, пакет #2, п.24): раньше здесь
    # был только тост callback.answer(show_alert=True) — он подтверждал
    # нажатие, но реально не присылал упражнения. Настоящее сообщение.
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.OPTIONAL_EXERCISE_DETAILS)
    await callback.answer()


@router.callback_query(F.data == "optional_exercise:skip")
async def handle_optional_exercise_skip(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(texts.OPTIONAL_EXERCISE_SKIPPED_TOAST)


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
    await callback.message.edit_reply_markup(reply_markup=None)
    await _send_plan(callback.message, state, data["target_a"], data["target_b"])
    await callback.answer()


@router.callback_query(F.data == "wk_back:block_b")
async def handle_back_to_block_b(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(WorkoutStates.waiting_for_block_b)
    await callback.message.edit_reply_markup(reply_markup=None)
    example_b = format_reps_example(data["target_b"], STRENGTH_BLOCK.work_sets)
    await callback.message.answer(
        texts.BLOCK_B_PROMPT.format(example=example_b), reply_markup=back_cancel_keyboard("wk_back:block_a"),
    )
    await callback.answer()


@router.message(WorkoutStates.waiting_for_comment)
async def handle_comment_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _finalize_workout(message, state, session, comment=message.text, telegram_id=message.from_user.id)


@router.callback_query(WorkoutStates.waiting_for_comment, F.data == "skip_comment")
async def handle_skip_comment(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _finalize_workout(
        callback.message, state, session, comment=None, clear_keyboard=True, telegram_id=callback.from_user.id,
    )
    await callback.answer()


async def _finalize_workout(
    message: Message, state: FSMContext, session: AsyncSession, *,
    comment: str | None, telegram_id: int, clear_keyboard: bool = False,
) -> None:
    data = await state.get_data()
    # Очищаем состояние ДО записи в БД (Часть 10, диагностика бага с
    # "Пропустить"): запись тренировки — это await, и пока он выполняется,
    # повторный тап (двойной клик/медленная сеть) по той же кнопке успевал
    # снова пройти фильтр WorkoutStates.waiting_for_comment (состояние ещё
    # не очищено) и мог записать ту же тренировку дважды. Теперь второй тап
    # просто не находит подходящий хендлер — тихий no-op вместо гонки.
    await state.clear()
    # clear_keyboard — только для callback-варианта (skip_comment): убираем
    # клавиатуру ПОСЛЕ state.clear(), чтобы не расширять то самое гоночное
    # окно двойного тапа, которое clear() выше и закрывает; для
    # message-варианта (handle_comment_text) message — это сообщение
    # пользователя, редактировать его клавиатуру нельзя и не нужно.
    if clear_keyboard:
        await message.edit_reply_markup(reply_markup=None)
    # telegram_id передаётся явно, а не берётся из message.from_user.id —
    # НАСТОЯЩАЯ причина бага "тренировка не пишется при 'Пропустить'"
    # (Часть 10, повторное всплытие): для callback-варианта message —
    # это callback.message, а у него from_user — БОТ, не человек, нажавший
    # кнопку. get_by_telegram_id(bot_id) возвращал None, user.id падал с
    # AttributeError ПОСЛЕ state.clear() — тренировка терялась молча, без
    # сообщения об ошибке (аиогram проглатывает необработанное исключение
    # в хендлере). Подтверждено трассировкой в логах прод-бота.
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)

    block_a_reps = BlockLog(working_reps=tuple(data["block_a_working_reps"]), max_reps=data["block_a_max_reps"])
    block_b_reps = BlockLog(working_reps=tuple(data["block_b_working_reps"]), max_reps=data["block_b_max_reps"])
    equipment_results = data["equipment_results"]
    block_a_equipment_type = EquipmentType(equipment_results["a"]["type"])
    block_a_equipment_value = Decimal(equipment_results["a"]["value"]) if equipment_results["a"]["value"] else None
    block_a_equipment_item_id = equipment_results["a"]["item_id"]
    block_b_equipment_type = EquipmentType(equipment_results["b"]["type"])
    block_b_equipment_value = Decimal(equipment_results["b"]["value"]) if equipment_results["b"]["value"] else None
    block_b_equipment_item_id = equipment_results["b"]["item_id"]

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
        block_a_equipment_item_id=block_a_equipment_item_id,
        block_b_equipment_item_id=block_b_equipment_item_id,
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
        if block.equipment_type == EquipmentType.BAND:
            return texts.TRANSITION_FAILED_BAND_SUFFIX
        return texts.TRANSITION_FAILED_SUFFIX
    if block.equipment_changed:
        return texts.EQUIPMENT_CHANGED_SUFFIX
    if block.equipment_type == EquipmentType.BODYWEIGHT and block.target_after == VOLUME_BLOCK.bodyweight_ceiling:
        return texts.CEILING_REACHED_SUFFIX
    return ""
