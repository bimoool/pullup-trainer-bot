"""Пакет #3 — два бага бэкдейта, найденные фокус-группой. Реальным
aiogram-роутингом.

Баг 1: опрос снаряда в бэкдейте использовал ту же формулировку, что и
живая смена снаряда по порогу прогрессии ("дошёл до порога — пора
потяжелее"), хотя в бэкдейте порог вообще не проверяется (снаряд
переспрашивается всегда, безусловно). Плюс шаг ввода веса не позволял
0/пропуск для непройденного блока.

Баг 2: заявленный "рассинхрон" между отметкой дня в календаре и
критерием редактируемости не подтвердился при разборе кода и прямой
проверке прод-БД — record_backdated_workout создаёт Workout только в
самом конце потока, /cancel в любой точке лишь чистит FSM, ничего в БД
не создавая. Тест ниже фиксирует это как регрессию. Отдельно — реальная
находка: generic "нечего редактировать" не объясняет разницу между
"тренировок в этот день не было" и "тренировка есть, но внесена задним
числом" — второе теперь отвечает текстом EDIT_NOT_EDITABLE."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import EquipmentStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
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


async def _start_backdate_at_block_a(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="backdate_workout"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="05.01.2026"), session=session,
    )


# --- Баг 1: текст опроса снаряда в бэкдейте -----------------------------------


async def test_backdate_equipment_prompt_uses_neutral_text_even_at_threshold_reps(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """working_reps на обоих блоках достигают equipment_change_threshold —
    в живом потоке это вызвало бы EQUIPMENT_TYPE_PROMPT_CHANGE ("дошёл до
    порога"). В бэкдейте порог не проверяется вовсе — должен показаться
    нейтральный EQUIPMENT_TYPE_PROMPT_BACKDATE, без слов "порог"/"пора"."""
    await _start_backdate_at_block_a(session, user, bot, dispatcher)

    # VOLUME_BLOCK.equipment_change_threshold=20, work_sets=3 — все рабочие подходы на пороге.
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="20 20 20 25"), session=session,
    )
    # STRENGTH_BLOCK.equipment_change_threshold=7, work_sets=4 — то же самое.
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="7 7 7 7 10"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    expected = texts.EQUIPMENT_TYPE_PROMPT_BACKDATE.format(block_label="блоке на объём")
    assert expected in sent_texts
    assert not any("порог" in t or "потяжелее" in t for t in sent_texts)


async def test_backdate_weight_step_offers_skip_button(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_backdate_at_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="5 5 5 8"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 5"), session=session,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:weight"), session=session,
    )

    [value_prompt] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and m.text.startswith(texts.EQUIPMENT_VALUE_PROMPT_WEIGHT)
    ]
    skip_buttons = [
        b for row in value_prompt.reply_markup.inline_keyboard for b in row if b.callback_data == "skip_item_kg"
    ]
    assert len(skip_buttons) == 1


async def test_backdate_weight_step_accepts_typed_zero_as_skip(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _start_backdate_at_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="5 5 5 8"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 5"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:weight"), session=session,
    )

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="0"), session=session)

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert texts.EQUIPMENT_VALUE_INVALID not in sent_texts

    # Продолжаем блок b свободным весом тела, чтобы дойти до записи и
    # проверить, что equipment_value блока a реально сохранился как None.
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    [workout] = history
    block_a = next(b for b in workout.blocks if b.block_type.value == "a")
    assert block_a.equipment_type.value == "weight"
    assert block_a.equipment_value is None


async def test_live_flow_weight_step_still_rejects_zero(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Регрессия на живой поток — 0 остаётся невалидным вводом там, где
    вес реально применяется прямо сейчас (в отличие от бэкдейта)."""
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_data({
        "equipment_flow": "live", "equipment_queue": ["a"], "equipment_results": {},
        "telegram_id": user.telegram_id, "pending_equipment_type": "weight",
    })
    await fsm.set_state(EquipmentStates.waiting_for_value)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="0"), session=session)

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert texts.EQUIPMENT_VALUE_INVALID in sent_texts
    assert await fsm.get_state() == EquipmentStates.waiting_for_value.state


# --- Баг 2: /cancel посреди бэкдейта не должен оставлять следов -------------------


async def test_cancel_mid_backdate_leaves_no_orphan_workout(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    # "После нескольких /cancel подряд" — повторяем цикл старт/дата/отмена
    # трижды, как в описанном репро.
    for _ in range(3):
        await _start_backdate_at_block_a(session, user, bot, dispatcher)
        assert await fsm.get_state() is not None
        await dispatcher.feed_update(
            bot, _message_update(telegram_id=user.telegram_id, text="/cancel"), session=session,
        )
        assert await fsm.get_state() is None

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_cancel_after_blocks_entered_before_equipment_confirmed_leaves_no_orphan(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Более глубокая точка отмены — оба блока введены, очередь снаряда уже
    открыта (EquipmentStates), но ни один снаряд ещё не подтверждён."""
    await _start_backdate_at_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="5 5 5 8"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 5"), session=session,
    )

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="/cancel"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() is None
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_edit_calendar_day_with_only_backdated_workout_explains_why(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """День отмечен ✅ в "Истории"/календаре бэкдейта (там маркируются любые
    тренировки), но в "Изменить тренировку" не редактируется — сообщение
    должно объяснять причину (EDIT_NOT_EDITABLE), а не молчать generic-ом."""
    await _start_backdate_at_block_a(session, user, bot, dispatcher)
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="5 5 5 8"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 5"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="equip:bodyweight"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1

    before = len(bot.session.sent_methods)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:edit:2026-01-05"), session=session,
    )

    [answer] = [m for m in bot.session.sent_methods[before:] if isinstance(m, AnswerCallbackQuery)]
    assert answer.text == texts.EDIT_NOT_EDITABLE


async def test_edit_calendar_day_with_no_workout_shows_generic_text(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="cal_day:edit:2026-01-05"), session=session,
    )

    [answer] = [m for m in bot.session.sent_methods if isinstance(m, AnswerCallbackQuery)]
    assert answer.text == texts.EDIT_NOTHING_TO_EDIT
