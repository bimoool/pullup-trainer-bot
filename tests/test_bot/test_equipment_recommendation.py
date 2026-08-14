"""План снаряда на первой тренировке/ретесте (Часть 10, пакет #2) — раньше
это была рекомендация с кнопками подтверждения/замены, теперь бот
формулирует план фактом одним сообщением на оба блока сразу и применяет
снаряд автоматически, без промежуточного шага. Гоняет реальным
aiogram-роутингом."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import EquipmentStates, WorkoutStates
from app.db.models import User
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from tests.test_bot.conftest import make_callback_update as _callback_update


async def _setup_equipment_queue(
    session, user: User, bot: Bot, dispatcher: Dispatcher, *, queue: list[str], baseline_reps: int,
) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_type)
    # set_data, не update_data — dispatcher/bot session-scoped, тот же
    # telegram_id (фикстура user всегда 1001) переиспользуется между
    # тестами файла, update_data смержил бы с FSM-хвостом от предыдущего
    # теста (например, equipment_plan_announced=True) вместо чистого старта.
    #
    # Блок, которого нет в очереди, уже "решён" _begin_equipment_setup в
    # реальном коде (needs_new_equipment=False, результат заполняется сразу)
    # — плейсхолдер здесь нужен, чтобы _send_plan после опустошения очереди
    # не упал на отсутствующем ключе equipment_results[тот_блок].
    equipment_results = {
        block: {"type": "bodyweight", "value": None, "item_id": None} for block in ("a", "b") if block not in queue
    }
    await fsm.set_data({
        "equipment_flow": "live",
        "equipment_queue": queue,
        "equipment_results": equipment_results,
        "baseline_reps": baseline_reps,
        "telegram_id": user.telegram_id,
        "workout_set_id": 1,
        "target_a": 10,
        "target_b": 4,
        "target_a_override": None,
        "target_b_override": None,
    })


async def _advance(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    """"Назад" с шага ввода значения реально переисполняет
    _advance_equipment_queue (см. handle_equipment_back_to_type) — тот же
    путь, которым в проде впервые попадают в очередь из
    _begin_equipment_setup, только без лишней настройки FSM с нуля."""
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_back:type"), session=session,
    )


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]


async def test_bodyweight_then_weight_cascades_through_both_blocks_automatically(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """baseline_reps=20 -> объём: свой вес (20>10, авто без ввода), сила:
    отягощение (20>=8, требует ввода веса) — одно нажатие "назад" должно
    прокатиться через весь блок A и остановиться на вводе веса блока B."""
    await _setup_equipment_queue(session, user, bot, dispatcher, queue=["a", "b"], baseline_reps=20)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await _advance(session, user, bot, dispatcher)

    data = await fsm.get_data()
    assert data["equipment_results"]["a"] == {"type": "bodyweight", "value": None, "item_id": None}
    assert data["equipment_queue"] == ["b"]
    assert await fsm.get_state() == EquipmentStates.waiting_for_value.state


async def test_plan_announced_exactly_once_for_full_queue(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _setup_equipment_queue(session, user, bot, dispatcher, queue=["a", "b"], baseline_reps=20)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await _advance(session, user, bot, dispatcher)

    announcements = [t for t in _sent_texts(bot) if "Исходя из замера" in t]
    assert len(announcements) == 1
    assert "собственным весом" in announcements[0]
    assert "отягощением" in announcements[0]
    assert (await fsm.get_data())["equipment_plan_announced"] is True


async def test_band_recommendation_offers_yes_no_not_confirm_replace_screen(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """baseline_reps=1 -> объём рекомендует резину (1<=10); список пуст ->
    да/нет-предложение завести (пакет #5), затем шаг имени после "Да" — без
    экрана подтверждения/замены снаряда."""
    await _setup_equipment_queue(session, user, bot, dispatcher, queue=["a"], baseline_reps=1)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await _advance(session, user, bot, dispatcher)

    assert await fsm.get_state() == EquipmentStates.waiting_for_type.state
    # ни одной кнопки подтверждения/замены не осталось в тексте плана
    assert not any("Взять другой снаряд" in t for t in _sent_texts(bot))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_band_offer:yes"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_new_item_name.state


async def test_bodyweight_only_block_finishes_queue_without_asking_anything(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _setup_equipment_queue(session, user, bot, dispatcher, queue=["a"], baseline_reps=20)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await _advance(session, user, bot, dispatcher)

    data = await fsm.get_data()
    assert data["equipment_results"]["a"] == {"type": "bodyweight", "value": None, "item_id": None}
    # единственный блок в очереди -> очередь опустела -> сразу к тренировке
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state


async def test_recommendation_uses_per_block_thresholds_not_volume_block_ones(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Регрессия на баг из живого тестирования: замер 20 для СИЛОВОГО блока
    должен рекомендовать отягощение (20>=8), а не свой вес."""
    await _setup_equipment_queue(session, user, bot, dispatcher, queue=["b"], baseline_reps=20)
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await _advance(session, user, bot, dispatcher)

    assert await fsm.get_state() == EquipmentStates.waiting_for_value.state
    data = await fsm.get_data()
    assert data["pending_equipment_type"] == "weight"


async def test_strength_weight_start_shows_specific_hint_not_generic_target(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Часть 10, пакет #2, п.7 — конкретная рекомендация (5 кг / минимум 4
    повторения), не общий принцип "около N повторений". Формулировка
    переработана в пакете #5 — 5 кг явно ориентир, не требование, единственное
    условие — минимум 4 повторения выбранным весом."""
    await _setup_equipment_queue(session, user, bot, dispatcher, queue=["b"], baseline_reps=20)

    await _advance(session, user, bot, dispatcher)

    texts_sent = _sent_texts(bot)
    assert any("ориентируйся на 5 кг" in t and "минимум 4 повторения" in t for t in texts_sent)
    assert not any("Рекомендуемый стартовый вес" in t for t in texts_sent)
    assert not any("около" in t and "повторений" in t for t in texts_sent)


async def test_band_target_hint_created_item_still_scoped_to_block(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Создание новой резины через авто-рекомендацию всё равно попадает в
    личный список пользователя как обычно."""
    await _setup_equipment_queue(session, user, bot, dispatcher, queue=["a"], baseline_reps=1)

    await _advance(session, user, bot, dispatcher)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_band_offer:yes"), session=session,
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


async def test_open_picker_still_works_for_equipment_change_not_baseline(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Смена снаряда по порогу прогрессии (baseline_reps=None) — по-прежнему
    открытый вопрос с 4 кнопками, это НЕ трогали в пакете #2."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(EquipmentStates.waiting_for_type)
    await fsm.update_data(
        equipment_flow="live", equipment_queue=["a"], equipment_results={}, baseline_reps=None,
        telegram_id=user.telegram_id, workout_set_id=1, target_a=10, target_b=4,
        target_a_override=None, target_b_override=None,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip_back:type"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_type.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:weight"), session=session,
    )
    assert await fsm.get_state() == EquipmentStates.waiting_for_value.state
