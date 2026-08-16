"""Факультативная нагрузка на отдыхе после блока А (Часть 10, п. 20, пакет
#2, п.24) — раньше "Хочу" отвечал только тостом, который не отправлял сами
упражнения (баг из живого тестирования). Два конкретных варианта
(приседания/выпады) вместо одной комбинированной кнопки — выбор по
ощущениям самого человека, без автоопределения уровня по данным. Реальным
aiogram-роутингом."""

from datetime import UTC, datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.bot.states import WorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from tests.test_bot.conftest import make_callback_update as _callback_update

_BRANCHES = [
    ("optional_exercise:squats", texts.OPTIONAL_EXERCISE_SQUATS_DETAILS),
    ("optional_exercise:lunges", texts.OPTIONAL_EXERCISE_LUNGES_DETAILS),
]


async def _put_user_at_block_a_step(session, user: User, bot: Bot, dispatcher: Dispatcher) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_block_a)
    await fsm.set_data({
        "workout_set_id": workout_set.id, "target_a": 10, "target_b": 4,
        "target_a_override": None, "target_b_override": None,
        "equipment_results": {
            "a": {"type": "bodyweight", "value": None, "item_id": None},
            "b": {"type": "bodyweight", "value": None, "item_id": None},
        },
    })


async def test_offer_does_not_reveal_exercise_details_upfront(session, user: User, bot: Bot, dispatcher: Dispatcher):
    from aiogram.types import Chat, Message, Update
    from aiogram.types import User as TgUser

    await _put_user_at_block_a_step(session, user, bot, dispatcher)

    update = Update(
        update_id=1,
        message=Message(
            message_id=1, date=datetime.now(UTC),
            chat=Chat(id=user.telegram_id, type="private"),
            from_user=TgUser(id=user.telegram_id, is_bot=False, first_name="Tester"),
            text="10 10 10 11",
        ),
    )
    await dispatcher.feed_update(bot, update, session=session)

    [offer] = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.OPTIONAL_EXERCISE_OFFER
    ]
    assert "приседания" not in offer.lower()
    assert "выпады" not in offer.lower()


@pytest.mark.parametrize(("callback_data", "expected_details"), _BRANCHES)
async def test_tapping_choice_sends_a_real_message_with_exercise_details(
    session, user: User, bot: Bot, dispatcher: Dispatcher, callback_data: str, expected_details: str,
):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=callback_data), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert expected_details in sent_texts


async def test_tapping_skip_does_not_send_exercise_details(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="optional_exercise:skip"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert texts.OPTIONAL_EXERCISE_SQUATS_DETAILS not in sent_texts
    assert texts.OPTIONAL_EXERCISE_LUNGES_DETAILS not in sent_texts


@pytest.mark.parametrize(("callback_data", "expected_details"), _BRANCHES)
async def test_tapping_choice_sends_exercise_details_before_block_b_prompt(
    session, user: User, bot: Bot, dispatcher: Dispatcher, callback_data: str, expected_details: str,
):
    """Баг из живого тестирования (пакет #3): раньше приглашение ко второму
    блоку уходило сразу вместе с предложением ("Хочешь доп. упражнения?"),
    независимо от выбора — при выборе упражнения инструкция приходила
    ПОСЛЕ приглашения, путая порядок действий. Теперь порядок жёстко завязан
    на сам выбор: инструкция — первой, приглашение ко второму блоку с явным
    переходом внутри неё — следом."""
    await _put_user_at_block_a_step(session, user, bot, dispatcher)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=callback_data), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    details_index = sent_texts.index(expected_details)
    block_b_index = next(i for i, t in enumerate(sent_texts) if t.startswith("Теперь блок на силу"))
    assert details_index < block_b_index
    assert "пришли результат блока на силу" in expected_details.lower()
    assert "например" not in expected_details.lower()


async def test_tapping_skip_still_advances_straight_to_block_b_prompt(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _put_user_at_block_a_step(session, user, bot, dispatcher)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="optional_exercise:skip"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert any(t.startswith("Теперь блок на силу") for t in sent_texts)


def test_lunges_button_marks_advanced_level():
    assert "продвинутый" in texts.OPTIONAL_EXERCISE_LUNGES_BUTTON.lower()
