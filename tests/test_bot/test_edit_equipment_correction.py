"""Правка веса/резины "в этом же отчёте" после редактирования тренировки
(Часть 10) — реальным aiogram-роутингом."""

from datetime import UTC, datetime
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import EditWorkoutStates
from app.db.models import BlockType, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog


def _callback_update(*, telegram_id: int, data: str) -> Update:
    message = Message(
        message_id=100, date=datetime.now(UTC),
        chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
        text="stub",
    )
    return Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="1",
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            chat_instance="1",
            data=data,
            message=message,
        ),
    )


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
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EditWorkoutStates.waiting_for_block_a)
    await fsm.update_data(edit_workout_id=workout_id)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="11 11 11 12"), session=session)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="4 4 4 4 5"), session=session)


async def test_no_correctable_blocks_skips_straight_to_done(session, user: User, bot: Bot, dispatcher: Dispatcher):
    workout_id = await _make_workout(
        session, user, block_a_type=EquipmentType.BODYWEIGHT, block_b_type=EquipmentType.BODYWEIGHT,
    )
    await _enter_edit_flow(session, user, bot, dispatcher, workout_id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() is None


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
