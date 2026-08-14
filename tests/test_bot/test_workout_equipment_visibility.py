"""Видимость закреплённого снаряда в живой тренировке + "✏️ Изменить вес/
резину" прямо у приглашения блока (пакет #7) — реальный пробел из
фокус-группы, подтверждённый скриншотом: снаряд молча наследуется с
прошлой тренировки, не показывается ни в приглашении, ни в итоге, и
поправить его в моменте было нельзя. Проверяет реальным aiogram-роутингом."""

from datetime import UTC, datetime
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import EquipmentStates, WorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
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


async def _put_user_mid_live_workout(
    session, user: User, bot: Bot, dispatcher: Dispatcher, *,
    equipment_a: dict, equipment_b: dict, state=WorkoutStates.waiting_for_block_a,
) -> int:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(state)
    await fsm.set_data({
        "workout_set_id": workout_set.id,
        "target_a": 10, "target_b": 4, "target_a_override": None, "target_b_override": None,
        "equipment_results": {"a": equipment_a, "b": equipment_b},
        "telegram_id": user.telegram_id,
        "is_first_workout": False,
    })
    return workout_set.id


def _last_message_text(bot: Bot, *, contains: str) -> str:
    [text] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and contains in m.text
    ]
    return text


def _keyboard_buttons(bot: Bot, *, message_text_contains: str) -> dict[str, str]:
    [message] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and message_text_contains in m.text
    ]
    return {b.text: b.callback_data for row in message.reply_markup.inline_keyboard for b in row}


# --- Видимость в приглашениях ----------------------------------------------------------


async def test_block_a_plan_shows_equipment_for_both_blocks_and_change_buttons(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    equipment_a = {"type": "band", "value": None, "item_id": None}
    equipment_b = {"type": "weight", "value": "48.0", "item_id": None}
    await _put_user_mid_live_workout(
        session, user, bot, dispatcher,
        equipment_a=equipment_a, equipment_b=equipment_b, state=WorkoutStates.waiting_for_block_b,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="wk_back:block_a"), session=session,
    )

    plan = _last_message_text(bot, contains="План на сегодня")
    assert "Работаем с резиной." in plan
    assert "Работаем с отягощением +48 кг." in plan
    # Кнопка тут только на блок A (снаряд блока B меняется у ЕГО
    # собственного приглашения, не здесь) — блок A на резине, значит
    # "Изменить резину", а не "Изменить вес".
    buttons = _keyboard_buttons(bot, message_text_contains="План на сегодня")
    assert buttons[texts.CHANGE_EQUIPMENT_BAND_BUTTON] == "wk_change_equipment:a"
    assert texts.CHANGE_EQUIPMENT_WEIGHT_BUTTON not in buttons


async def test_block_b_prompt_shows_equipment_and_change_button(session, user: User, bot: Bot, dispatcher: Dispatcher):
    equipment_a = {"type": "bodyweight", "value": None, "item_id": None}
    equipment_b = {"type": "weight", "value": "48.0", "item_id": None}
    await _put_user_mid_live_workout(session, user, bot, dispatcher, equipment_a=equipment_a, equipment_b=equipment_b)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 10 11"), session=session)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="optional_exercise:skip"), session=session,
    )

    prompt = _last_message_text(bot, contains="Теперь блок на силу")
    assert "Работаем с отягощением +48 кг." in prompt
    buttons = _keyboard_buttons(bot, message_text_contains="Теперь блок на силу")
    assert buttons[texts.CHANGE_EQUIPMENT_WEIGHT_BUTTON] == "wk_change_equipment:b"
    assert buttons["← Назад"] == "wk_back:block_a"


async def test_block_prompt_omits_change_button_for_bodyweight(session, user: User, bot: Bot, dispatcher: Dispatcher):
    equipment_a = {"type": "bodyweight", "value": None, "item_id": None}
    equipment_b = {"type": "bodyweight", "value": None, "item_id": None}
    await _put_user_mid_live_workout(session, user, bot, dispatcher, equipment_a=equipment_a, equipment_b=equipment_b)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="10 10 10 11"), session=session)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="optional_exercise:skip"), session=session,
    )

    buttons = _keyboard_buttons(bot, message_text_contains="Теперь блок на силу")
    assert texts.CHANGE_EQUIPMENT_WEIGHT_BUTTON not in buttons
    assert texts.CHANGE_EQUIPMENT_BAND_BUTTON not in buttons
    assert set(buttons) == {"← Назад", "❌ Отмена"}


async def test_workout_summary_shows_equipment_used_per_block(session, user: User, bot: Bot, dispatcher: Dispatcher):
    equipment_a = {"type": "band", "value": None, "item_id": None}
    equipment_b = {"type": "weight", "value": "48.0", "item_id": None}
    await _put_user_mid_live_workout(
        session, user, bot, dispatcher,
        equipment_a=equipment_a, equipment_b=equipment_b, state=WorkoutStates.waiting_for_comment,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.update_data(
        block_a_working_reps=[10, 10, 10], block_a_max_reps=11,
        block_b_working_reps=[5, 5, 5, 5], block_b_max_reps=5,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_comment"), session=session,
    )

    summary = _last_message_text(bot, contains="Тренировка записана")
    assert "Объём (резина): 10, 10, 10, максимум 11" in summary
    assert "Сила (отягощение +48 кг): 5, 5, 5, 5, максимум 5" in summary


# --- "✏️ Изменить вес/резину" ------------------------------------------------------------


async def test_change_weight_button_updates_value_and_resends_block_a_prompt(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    equipment_a = {"type": "weight", "value": "20.0", "item_id": None}
    equipment_b = {"type": "bodyweight", "value": None, "item_id": None}
    await _put_user_mid_live_workout(session, user, bot, dispatcher, equipment_a=equipment_a, equipment_b=equipment_b)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="wk_change_equipment:a"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_value.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="25"), session=session)

    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state
    data = await fsm.get_data()
    assert data["equipment_results"]["a"] == {"type": "weight", "value": "25", "item_id": None}
    plan = _last_message_text(bot, contains="План на сегодня")
    assert "Работаем с отягощением +25 кг." in plan


async def test_change_band_button_updates_item_and_resends_block_b_prompt(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    new_band = await EquipmentItemRepository(session).create(user_id=user.id, name="новая резина")
    equipment_a = {"type": "bodyweight", "value": None, "item_id": None}
    equipment_b = {"type": "band", "value": None, "item_id": None}
    await _put_user_mid_live_workout(
        session, user, bot, dispatcher,
        equipment_a=equipment_a, equipment_b=equipment_b, state=WorkoutStates.waiting_for_block_b,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.update_data(block_a_working_reps=[10, 10, 10], block_a_max_reps=11)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="wk_change_equipment:b"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_band_choice.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"band_item:{new_band.id}"), session=session,
    )

    assert await fsm.get_state() == WorkoutStates.waiting_for_block_b.state
    data = await fsm.get_data()
    assert data["equipment_results"]["b"] == {"type": "band", "value": None, "item_id": new_band.id}
    # Уже введённый блок A не потерян — тот же прогресс тренировки.
    assert data["block_a_working_reps"] == [10, 10, 10]


async def test_change_weight_does_not_fire_from_wrong_block_state(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """wk_change_equipment:b гейтится состоянием waiting_for_block_b —
    находясь на блоке A, нажатие (например, старой кнопкой из прошлого
    сообщения) не должно ничего сломать."""
    equipment_a = {"type": "weight", "value": "20.0", "item_id": None}
    equipment_b = {"type": "weight", "value": "48.0", "item_id": None}
    await _put_user_mid_live_workout(session, user, bot, dispatcher, equipment_a=equipment_a, equipment_b=equipment_b)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="wk_change_equipment:b"), session=session,
    )

    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state
    data = await fsm.get_data()
    assert data["equipment_results"]["b"] == equipment_b


async def test_change_weight_full_workout_records_updated_value(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Сквозная проверка до записи в БД — обновлённый вес реально попадает
    в итоговую тренировку, не только показывается в приглашении."""
    equipment_a = {"type": "bodyweight", "value": None, "item_id": None}
    equipment_b = {"type": "weight", "value": "20.0", "item_id": None}
    await _put_user_mid_live_workout(
        session, user, bot, dispatcher,
        equipment_a=equipment_a, equipment_b=equipment_b, state=WorkoutStates.waiting_for_block_b,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.update_data(block_a_working_reps=[10, 10, 10], block_a_max_reps=11)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="wk_change_equipment:b"), session=session,
    )
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="27.5"), session=session)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="5 5 5 5 6"), session=session)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_comment"), session=session,
    )

    [workout] = await WorkoutRepository(session).list_for_user(user.id)
    block_b = next(b for b in workout.blocks if b.block_type.value == "b")
    assert block_b.equipment_value == Decimal("27.5")
