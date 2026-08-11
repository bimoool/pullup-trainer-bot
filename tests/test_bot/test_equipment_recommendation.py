"""Рекомендация снаряда вместо открытого вопроса на первой тренировке/
ретесте (Часть 10) — реальным aiogram-роутингом: "✅ Начать с ..." сразу
применяет рекомендованный тип, "Взять другой снаряд" открывает обычный
список из 4 кнопок."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import EquipmentStates, WorkoutStates
from app.db.models import User
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository


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


async def _start_equipment_queue_for_block_a_with_baseline(
    session, user: User, bot: Bot, dispatcher: Dispatcher, *, baseline_reps: int,
) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_type)
    await fsm.update_data(
        equipment_flow="live",
        equipment_queue=["a"],
        equipment_results={},
        baseline_reps=baseline_reps,
        workout_set_id=1,
        target_a=10,
        target_b=4,
        target_a_override=None,
        target_b_override=None,
    )


async def test_advance_queue_with_baseline_stores_recommendation(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """baseline_reps=20 -> объёмный блок рекомендует свой вес (20>10)."""
    await _start_equipment_queue_for_block_a_with_baseline(session, user, bot, dispatcher, baseline_reps=20)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    # _advance_equipment_queue уже был вызван неявно через update_data выше?
    # Нет — вызывается только из _begin_equipment_setup/после выбора,
    # поэтому дёргаем реальный путь: имитируем повторный показ через "назад".
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_back:type"), session=session,
    )

    data = await fsm.get_data()
    assert data["recommended_equipment"] == "bodyweight"


async def test_accept_recommendation_bodyweight_advances_without_asking_value(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _start_equipment_queue_for_block_a_with_baseline(session, user, bot, dispatcher, baseline_reps=20)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.update_data(recommended_equipment="bodyweight")

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_recommend:accept"), session=session,
    )

    data = await fsm.get_data()
    assert data["equipment_results"]["a"] == {"type": "bodyweight", "value": None, "item_id": None}
    # единственный блок в очереди -> сразу к вводу результатов тренировки
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state


async def test_accept_recommendation_band_goes_to_band_flow_with_target_hint_context(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """baseline_reps=1 -> объёмный блок рекомендует резину (1<=10)."""
    await _start_equipment_queue_for_block_a_with_baseline(session, user, bot, dispatcher, baseline_reps=1)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.update_data(recommended_equipment="band")

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_recommend:accept"), session=session,
    )

    # список резин пуст -> сразу шаг имени новой резины
    assert await fsm.get_state() == EquipmentStates.waiting_for_new_item_name.state


async def test_other_equipment_falls_back_to_open_picker(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_equipment_queue_for_block_a_with_baseline(session, user, bot, dispatcher, baseline_reps=20)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_recommend:other"), session=session,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == EquipmentStates.waiting_for_type.state

    # теперь обычный открытый выбор работает как раньше
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:weight"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_value.state


async def test_recommendation_uses_per_block_thresholds_not_volume_block_ones(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Регрессия на баг из живого тестирования: замер 20 для СИЛОВОГО блока
    должен рекомендовать отягощение (20>=8), а не свой вес."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_type)
    await fsm.update_data(
        equipment_flow="live", equipment_queue=["b"], equipment_results={}, baseline_reps=20,
        workout_set_id=1, target_a=10, target_b=4, target_a_override=None, target_b_override=None,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_back:type"), session=session,
    )

    data = await fsm.get_data()
    assert data["recommended_equipment"] == "weight"


async def test_band_target_hint_created_item_still_scoped_to_block(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Создание новой резины через рекомендацию всё равно попадает в
    личный список пользователя как обычно (просто с подсказкой цели в
    тексте, который StubSession не проверяет — здесь проверяем эффект)."""
    await _start_equipment_queue_for_block_a_with_baseline(session, user, bot, dispatcher, baseline_reps=1)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.update_data(recommended_equipment="band")
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_recommend:accept"), session=session,
    )

    await dispatcher.feed_update(
        bot, Update(
            update_id=2,
            message=Message(
                message_id=102, date=datetime.now(UTC),
                chat=Chat(id=user.telegram_id, type="private"),
                from_user=TgUser(id=user.telegram_id, is_bot=False, first_name="Tester"),
                text="зелёная",
            ),
        ),
        session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_item_kg"), session=session,
    )

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert [item.name for item in items] == ["зелёная"]
