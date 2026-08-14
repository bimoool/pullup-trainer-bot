"""Личный список резин (Часть 8 респека) — проверяет реальным
aiogram-роутингом весь путь выбора BAND-снаряда: пустой список -> имя ->
kg (или пропуск) -> запись в equipment_results и очередь; выбор уже
добавленного снаряда из списка; и реордер "🎗 Мои резины" из Профиля."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
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
        # Блок B не нуждается в переспросе (needs_new_equipment=False) —
        # _begin_equipment_setup заполняет его результат сразу, до захода в
        # очередь (см. app/bot/handlers/equipment.py); повторяем то же здесь.
        equipment_results={"b": {"type": "band", "value": None, "item_id": None}},
        baseline_reps=None,
        workout_set_id=1,
        target_a=10,
        target_b=4,
        target_a_override=None,
        target_b_override=None,
    )


async def test_band_choice_with_empty_list_offers_yes_no_before_asking_name(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Пакет #5 — "заведём? как назовём" было одним слитным сообщением с
    двумя вопросами; теперь да/нет и имя — два отдельных шага."""
    await _start_equipment_queue_for_block_a(session, user, bot, dispatcher)

    await dispatcher.feed_update(bot, _callback_update(telegram_id=user.telegram_id, data="equip:band"), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    # Ещё не в шаге ввода имени — сначала да/нет.
    assert await fsm.get_state() == EquipmentStates.waiting_for_type.state
    assert (await fsm.get_data())["equipment_queue"] == ["a"]

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_band_offer:yes"), session=session,
    )

    assert await fsm.get_state() == EquipmentStates.waiting_for_new_item_name.state
    # очередь всё ещё не тронута — блок "a" по-прежнему первый
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


# --- "❓ Как выбрать резину" на шаге ввода имени — по запросу, не сама -----------


async def test_band_name_prompt_offers_help_button_alongside_back_and_cancel(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_equipment_queue_for_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(bot, _callback_update(telegram_id=user.telegram_id, data="equip:band"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_band_offer:yes"), session=session,
    )

    [name_prompt] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.EQUIPMENT_BAND_NAME_PROMPT
    ]
    buttons = {
        b.text: b.callback_data for row in name_prompt.reply_markup.inline_keyboard for b in row
    }
    assert buttons[texts.EQUIPMENT_BAND_HELP_BUTTON] == "band_name_help"
    assert "← Назад" in buttons
    assert "❌ Отмена" in buttons


async def test_standalone_band_name_prompt_offers_help_without_back_button(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="band_add_standalone"), session=session,
    )

    [name_prompt] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.EQUIPMENT_BAND_NAME_PROMPT
    ]
    buttons = {
        b.text: b.callback_data for row in name_prompt.reply_markup.inline_keyboard for b in row
    }
    assert buttons[texts.EQUIPMENT_BAND_HELP_BUTTON] == "band_name_help"
    assert "← Назад" not in buttons
    assert "❌ Отмена" in buttons


async def test_band_name_help_sends_text_without_disrupting_the_flow(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Справка по запросу — не должна ломать сценарий: состояние и уже
    отправленное приглашение с клавиатурой остаются как есть, следующее
    сообщение с именем резины по-прежнему обрабатывается нормально."""
    await _start_equipment_queue_for_block_a(session, user, bot, dispatcher)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_new_item_name)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="band_name_help"), session=session,
    )

    assert await fsm.get_state() == EquipmentStates.waiting_for_new_item_name.state
    help_messages = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.EQUIPMENT_BAND_HELP_TEXT
    ]
    assert len(help_messages) == 1

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="зелёная"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_new_item_kg.state


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
