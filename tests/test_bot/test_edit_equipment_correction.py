"""Правка веса/резины "в этом же отчёте" после редактирования тренировки
(Часть 10) — реальным aiogram-роутингом."""

from datetime import UTC, datetime
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import EditWorkoutStates
from app.db.models import BlockType, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from tests.test_bot.conftest import make_callback_update as _callback_update


def _message_update(*, telegram_id: int, text: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=text,
        ),
    )


async def _make_workout(
    session, user: User, *, block_a_type=EquipmentType.BAND, block_b_type=EquipmentType.WEIGHT,
    block_a_item_id=None,
) -> int:
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workout = await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=block_a_type,
        block_a_equipment_value=None if block_a_item_id else Decimal("20.0"),
        block_a_equipment_item_id=block_a_item_id,
        block_b_equipment_type=block_b_type, block_b_equipment_value=Decimal("20.0"),
    )
    return workout.id


async def _enter_edit_flow(session, user: User, bot: Bot, dispatcher: Dispatcher, workout_id: int) -> None:
    # target_a/target_b — как их выставляет _start_editing в проде: target_before
    # именно этой редактируемой тренировки (Часть 10, пакет #2, п.10).
    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EditWorkoutStates.waiting_for_block_a)
    await fsm.update_data(
        edit_workout_id=workout_id, target_a=block_a.target_before, target_b=block_b.target_before,
        edit_workout_performed_at=workout.performed_at.isoformat(),
        # То же, что реально кладёт _start_editing — снаряд исторической
        # записи, показывается в приглашениях блока A/B (пакет #7).
        edit_block_a_equipment={
            "type": block_a.equipment_type.value,
            "value": str(block_a.equipment_value) if block_a.equipment_value is not None else None,
        },
        edit_block_b_equipment={
            "type": block_b.equipment_type.value,
            "value": str(block_b.equipment_value) if block_b.equipment_value is not None else None,
        },
    )
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="11 11 11 12"), session=session)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="4 4 4 4 5"), session=session)


async def test_block_prompts_show_historical_equipment_before_correction(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Пакет #7 — снаряд ИСТОРИЧЕСКОЙ записи должен быть виден ещё ДО ввода
    новых чисел, не только на отдельном шаге правки после."""
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BAND, block_b_type=EquipmentType.WEIGHT,
    )
    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EditWorkoutStates.waiting_for_block_a)
    await fsm.update_data(
        edit_workout_id=workout_id, target_a=block_a.target_before, target_b=block_b.target_before,
        edit_workout_performed_at=workout.performed_at.isoformat(),
        edit_block_a_equipment={"type": "band", "value": None},
        edit_block_b_equipment={"type": "weight", "value": "20.0"},
    )
    await dispatcher.feed_update(
        bot, Update(
            update_id=1,
            message=Message(
                message_id=101, date=datetime.now(UTC),
                chat=Chat(id=user.telegram_id, type="private"),
                from_user=TgUser(id=user.telegram_id, is_bot=False, first_name="Tester"),
                text="11 11 11 12",
            ),
        ),
        session=session,
    )

    [prompt] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and m.text.startswith("Теперь блок на силу")
    ]
    assert "Работаем с отягощением +20 кг." in prompt


async def test_no_correctable_blocks_skips_straight_to_done(session, user: User, bot: Bot, dispatcher: Dispatcher):
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BODYWEIGHT, block_b_type=EquipmentType.BODYWEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() is None


async def test_edit_done_shows_working_reps_alongside_max(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Пакет #4 — тот же принцип, что и в WORKOUT_SUMMARY: после правки
    нужно свериться с фактически введёнными числами, не только с макс."""
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BODYWEIGHT, block_b_type=EquipmentType.BODYWEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)

    [done] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and m.text.startswith(texts.EDIT_DONE.split("{")[0])
    ]
    assert "11, 11, 11, максимум 12" in done
    assert "4, 4, 4, 4, максимум 5" in done


async def test_edit_done_shows_equipment_used_per_block(session, user: User, bot: Bot, dispatcher: Dispatcher):
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BAND, block_b_type=EquipmentType.BODYWEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)

    [done] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and m.text.startswith(texts.EDIT_DONE.split("{")[0])
    ]
    assert "Блок на объём (резина):" in done
    assert "Блок на силу (собственный вес):" in done


async def test_weight_correction_updates_value_and_advances(session, user: User, bot: Bot, dispatcher: Dispatcher):
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BODYWEIGHT, block_b_type=EquipmentType.WEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_equipment_weight.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="22.5"), session=session)

    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    assert block_b.equipment_value == Decimal("22.5")
    assert await fsm.get_state() is None  # единственный корректируемый блок -> сразу готово


async def test_skip_weight_correction_leaves_value_unchanged(session, user: User, bot: Bot, dispatcher: Dispatcher):
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BODYWEIGHT, block_b_type=EquipmentType.WEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="edit_equipment_skip"), session=session,
    )

    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    assert block_b.equipment_value == Decimal("20.0")  # исходное значение


async def test_band_correction_updates_item_id(session, user: User, bot: Bot, dispatcher: Dispatcher):
    repo = EquipmentItemRepository(session)
    original = await repo.create(user_id=user.id, name="старая")
    other = await repo.create(user_id=user.id, name="новая")
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BAND, block_a_item_id=original.id,
        block_b_type=EquipmentType.BODYWEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_equipment_band.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"edit_band_item:{other.id}"), session=session,
    )

    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    assert block_a.equipment_item_id == other.id


async def test_both_blocks_correctable_processed_in_sequence(session, user: User, bot: Bot, dispatcher: Dispatcher):
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.WEIGHT, block_b_type=EquipmentType.WEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_equipment_weight.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="21"), session=session)
    # блок B тоже корректируемый -> состояние остаётся тем же (снова weight-промпт)
    assert await fsm.get_state() == EditWorkoutStates.waiting_for_equipment_weight.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="15"), session=session)
    assert await fsm.get_state() is None

    workout = await WorkoutRepository(session).get_by_id(workout_id)
    block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)
    assert block_a.equipment_value == Decimal(21)
    assert block_b.equipment_value == Decimal(15)
