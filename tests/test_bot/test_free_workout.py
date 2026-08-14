"""«➕ Внести свободные подтягивания» (Часть 10, п. 18, пакет #2, п.21) —
реальным aiogram-роутингом: снаряд + произвольное количество подходов, вне
плана и вне сета из 12, попадает в статистику."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import FreeWorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
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


async def test_free_workout_start_asks_for_equipment_first(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="free_workout_start"), session=session,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_equipment_type.state


async def test_bodyweight_choice_goes_straight_to_reps_prompt(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_equipment_type)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )

    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps.state


async def test_reps_prompt_shows_just_chosen_equipment(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Снаряд для свободных подтягиваний и так явно выбирается перед вводом
    чисел (в отличие от живой тренировки) — но не был виден в самом
    приглашении к вводу, только на предыдущем шаге выбора (пакет #7)."""
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_equipment_type)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )

    [prompt] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and m.text.startswith("Сколько подходов")
    ]
    assert "Работаем с собственным весом." in prompt


async def test_arbitrary_set_count_is_recorded_with_equipment(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_data({"equipment_type": "bodyweight", "equipment_value": None, "equipment_item_id": None})
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="8 6 5 4"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1
    workout = history[0]
    assert workout.is_free_entry is True
    block_a = next(b for b in workout.blocks if b.block_type.value == "a")
    assert block_a.working_reps == [8, 6, 5]
    assert block_a.max_reps == 4
    assert block_a.equipment_type == EquipmentType.BODYWEIGHT

    workout_sets = await WorkoutSetRepository(session).list_for_user(user.id)
    assert len(workout_sets) == 1
    assert workout_sets[0].workouts_completed == 0  # не входит в сет из 12

    assert await fsm.get_state() is None


async def test_single_number_still_works_like_before(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_data({"equipment_type": "bodyweight", "equipment_value": None, "equipment_item_id": None})
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="8"), session=session)

    history = await WorkoutRepository(session).list_for_user(user.id)
    block_a = next(b for b in history[0].blocks if b.block_type.value == "a")
    assert block_a.working_reps == []
    assert block_a.max_reps == 8


async def test_free_workout_invalid_input_does_not_advance(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_data({"equipment_type": "bodyweight", "equipment_value": None, "equipment_item_id": None})
    await fsm.set_state(FreeWorkoutStates.waiting_for_reps)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="не число"), session=session,
    )

    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps.state
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_weight_choice_asks_for_value_then_records_it(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_equipment_type)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:weight"), session=session,
    )
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_equipment_value.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="20"), session=session)
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="5 4 3"), session=session)

    history = await WorkoutRepository(session).list_for_user(user.id)
    block_a = next(b for b in history[0].blocks if b.block_type.value == "a")
    assert block_a.equipment_type == EquipmentType.WEIGHT
    assert block_a.equipment_value == 20


async def test_band_choice_with_empty_list_offers_yes_no_before_name(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Пакет #5 — да/нет и имя теперь два отдельных шага, не одно слитное
    сообщение "заведём? как назовём"."""
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_equipment_type)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:band"), session=session,
    )
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_equipment_type.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="free_workout_band_offer:yes"), session=session,
    )
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_new_item_name.state


async def test_band_choice_creates_item_and_records_workout(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_equipment_type)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:band"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="free_workout_band_offer:yes"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="зелёная"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_item_kg"), session=session,
    )
    assert await fsm.get_state() == FreeWorkoutStates.waiting_for_reps.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 8"), session=session)

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert len(items) == 1

    history = await WorkoutRepository(session).list_for_user(user.id)
    block_a = next(b for b in history[0].blocks if b.block_type.value == "a")
    assert block_a.equipment_type == EquipmentType.BAND
    assert block_a.equipment_item_id == items[0].id


async def test_band_name_prompt_offers_help_button_in_free_workout_flow(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(FreeWorkoutStates.waiting_for_equipment_type)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:band"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="free_workout_band_offer:yes"), session=session,
    )

    [name_prompt] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.EQUIPMENT_BAND_NAME_PROMPT
    ]
    buttons = {b.text: b.callback_data for row in name_prompt.reply_markup.inline_keyboard for b in row}
    assert buttons[texts.EQUIPMENT_BAND_HELP_BUTTON] == "band_name_help"
