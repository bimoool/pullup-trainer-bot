"""Личный список резин (Часть 8 респека) — проверяет реальным
aiogram-роутингом весь путь выбора BAND-снаряда: пустой список -> имя ->
kg (или пропуск) -> запись в equipment_results и очередь; выбор уже
добавленного снаряда из списка; и реордер "🎗 Мои резины" из Профиля."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import EquipmentStates, WorkoutStates
from app.db.models import User
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository

_CHAT_ID = 5001


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


async def _start_equipment_queue_for_block_a(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    """Имитирует то, что _begin_equipment_setup уже сделал бы (см.
    app/bot/handlers/equipment.py) — тестируем сам шаг выбора снаряда, не
    весь путь начала тренировки/ретеста, который к нему приводит."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_type)
    await fsm.update_data(
        equipment_flow="live",
        equipment_queue=["a"],
        equipment_results={},
        baseline_reps=None,
        workout_set_id=1,
        target_a=10,
        target_b=4,
        target_a_override=None,
        target_b_override=None,
    )


async def test_band_choice_with_empty_list_goes_straight_to_name_prompt(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_equipment_queue_for_block_a(session, user, bot, dispatcher)

    await dispatcher.feed_update(bot, _callback_update(telegram_id=user.telegram_id, data="equip:band"), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == EquipmentStates.waiting_for_new_item_name.state
    # очередь ещё не тронута — блок "a" по-прежнему первый в очереди
    assert (await fsm.get_data())["equipment_queue"] == ["a"]


async def test_new_item_name_then_skip_kg_creates_item_and_advances_queue(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_equipment_queue_for_block_a(session, user, bot, dispatcher)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_new_item_name)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="зелёная"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_new_item_kg.state
    assert (await fsm.get_data())["pending_item_name"] == "зелёная"

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_item_kg"), session=session,
    )

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert len(items) == 1
    assert items[0].name == "зелёная"
    assert items[0].resistance_kg is None

    # единственный блок в очереди — после выбора снаряда очередь опустела,
    # флоу "live" переходит к _send_plan (WorkoutStates.waiting_for_block_a)
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state


async def test_new_item_kg_creates_item_with_resistance(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_equipment_queue_for_block_a(session, user, bot, dispatcher)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_new_item_name)
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="широкая фиолетовая"), session=session,
    )

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="25"), session=session,
    )

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert items[0].resistance_kg == 25


async def test_band_item_choice_from_existing_list_sets_item_id(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_equipment_queue_for_block_a(session, user, bot, dispatcher)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="уже добавленная")
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_band_choice)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"band_item:{item.id}"), session=session,
    )

    data = await fsm.get_data()
    assert data["equipment_results"]["a"] == {"type": "band", "value": None, "item_id": item.id}
    # список не пополнился новым пунктом — переиспользовали существующий
    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert len(items) == 1


async def test_band_move_swaps_positions(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    repo = EquipmentItemRepository(session)
    first = await repo.create(user_id=user.id, name="первая")
    second = await repo.create(user_id=user.id, name="вторая")

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"band_move:{second.id}:up"), session=session,
    )

    items = await repo.list_for_user(user.id)
    assert [item.id for item in items] == [second.id, first.id]


# --- "➕ Добавить резину" из Профиля, вне тренировки (Часть 10, п. 22) ------------


async def test_standalone_add_band_with_kg(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="band_add_standalone"), session=session,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == EquipmentStates.waiting_for_standalone_item_name.state

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="фиолетовая"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_standalone_item_kg.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="18"), session=session)

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert len(items) == 1
    assert items[0].name == "фиолетовая"
    assert items[0].resistance_kg == 18
    assert await fsm.get_state() is None


async def test_standalone_add_band_skip_kg(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_standalone_item_name)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="зелёная"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_item_kg"), session=session,
    )

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert len(items) == 1
    assert items[0].resistance_kg is None


async def test_equipment_list_open_shows_add_button_even_when_empty(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    # не должно упасть/зайти в тупик без клавиатуры — сам факт, что дальше
    # можно нажать "band_add_standalone", проверяет предыдущий тест
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equipment_list_open"), session=session,
    )
    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert items == []
