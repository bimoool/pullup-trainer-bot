"""Онбординг после правок Части 10: подтверждение результата замера
(баг — раньше писалось в БД сразу, без возможности исправить опечатку),
анкета с полом/датой рождения вместо возраста числом, часовой пояс городом
текстом вместо кнопок. Реальный aiogram-роутинг, не юнит-тест сервиса."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.states import OnboardingStates
from app.db.models import Gender, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
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


async def test_baseline_number_does_not_save_before_confirm(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_baseline_reps)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="12"), session=session)

    assert await fsm.get_state() == OnboardingStates.waiting_for_baseline_confirm.state
    assert await BaselineRepository(session).list_for_user(user.id) == []


async def test_baseline_reenter_discards_pending_value_and_asks_again(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_baseline_reps)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="12"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="baseline_reenter"), session=session,
    )

    assert await fsm.get_state() == OnboardingStates.waiting_for_baseline_reps.state
    assert await BaselineRepository(session).list_for_user(user.id) == []


async def test_baseline_confirm_saves_and_advances_to_optional_gender(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_baseline_reps)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="12"), session=session)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="baseline_confirm"), session=session,
    )

    baselines = await BaselineRepository(session).list_for_user(user.id)
    assert len(baselines) == 1
    assert baselines[0].reps == 12
    assert await fsm.get_state() == OnboardingStates.waiting_for_gender.state


async def test_baseline_accepts_three_digit_number(session, user: User, bot: Bot, dispatcher: Dispatcher):
    # Баг: раньше MAX_REASONABLE_REPS=100 жёстко отклонял любое трёхзначное
    # число (102 → "Не разобрал число повторений") на каждую попытку.
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_baseline_reps)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="102"), session=session)

    assert await fsm.get_state() == OnboardingStates.waiting_for_baseline_confirm.state
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="baseline_confirm"), session=session,
    )
    baselines = await BaselineRepository(session).list_for_user(user.id)
    assert baselines[0].reps == 102


async def test_baseline_still_rejects_absurdly_large_number(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    # Жёсткий предел (сейчас 1000+) остаётся — это защита от опечаток
    # (лишний ноль и т.п.), не то же самое, что снятое ограничение на 100.
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_baseline_reps)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="1000"), session=session)

    assert await fsm.get_state() == OnboardingStates.waiting_for_baseline_reps.state
    assert await BaselineRepository(session).list_for_user(user.id) == []


async def test_baseline_confirm_with_zero_still_saves(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_baseline_reps)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="0"), session=session)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="baseline_confirm"), session=session,
    )

    baselines = await BaselineRepository(session).list_for_user(user.id)
    assert len(baselines) == 1
    assert baselines[0].reps == 0


async def test_full_questionnaire_keeps_voluntary_demographics_and_explicit_timezone(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_gender)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="gender:male"), session=session,
    )
    assert await fsm.get_state() == OnboardingStates.waiting_for_birth_date.state

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="15.03.1996"), session=session,
    )
    assert await fsm.get_state() == OnboardingStates.waiting_for_timezone.state

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="qnr_timezone:Asia/Yekaterinburg"), session=session,
    )

    assert await fsm.get_state() is None
    reloaded = await UserRepository(session).get_by_telegram_id(user.telegram_id)
    assert reloaded.weight_kg is None
    assert reloaded.height_cm is None
    assert reloaded.gender == Gender.MALE
    assert reloaded.birth_date.isoformat() == "1996-03-15"
    assert reloaded.timezone == "Asia/Yekaterinburg"
    assert reloaded.onboarding_completed_at is not None


async def test_unrecognized_city_requires_an_explicit_timezone_choice(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_gender)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="gender:female"), session=session,
    )
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="01.01.2000"), session=session)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="synthetic unknown city"), session=session)
    assert await fsm.get_state() == OnboardingStates.waiting_for_timezone.state
    assert user.timezone is None
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="qnr_timezone:Europe/Moscow"), session=session,
    )
    reloaded = await UserRepository(session).get_by_telegram_id(user.telegram_id)
    assert reloaded.timezone == "Europe/Moscow"
    assert reloaded.gender == Gender.FEMALE


async def test_birth_date_in_future_is_rejected(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_birth_date)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="01.01.2999"), session=session,
    )

    # состояние не сдвинулось — дата из будущего отклонена
    assert await fsm.get_state() == OnboardingStates.waiting_for_birth_date.state


async def test_minimal_bot_questionnaire_skips_demographics_and_uses_explicit_timezone(
    session, user, bot, dispatcher,
):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_gender)
    await fsm.set_data({})
    for data in ("qnr_skip:gender", "qnr_skip:birth_date", "qnr_timezone:Asia/Yekaterinburg"):
        await dispatcher.feed_update(bot, _callback_update(telegram_id=user.telegram_id, data=data), session=session)
    await session.refresh(user)
    assert await fsm.get_state() is None
    assert user.onboarding_completed_at is not None
    assert user.timezone == "Asia/Yekaterinburg"
    assert (user.weight_kg, user.height_cm, user.gender, user.birth_date) == (None, None, None, None)


async def test_old_body_questionnaire_state_drops_unneeded_fields_after_restart(session, user, bot, dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_weight)
    await fsm.set_data({"weight_kg": "78.5", "height_cm": 180})
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="80"), session=session)
    assert await fsm.get_state() == OnboardingStates.waiting_for_gender.state
    data = await fsm.get_data()
    assert "weight_kg" not in data and "height_cm" not in data
    await session.refresh(user)
    assert user.weight_kg is None and user.height_cm is None


async def test_timezone_text_does_not_silently_assign_moscow(session, user, bot, dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(OnboardingStates.waiting_for_timezone)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="unknown synthetic city"), session=session)
    assert await fsm.get_state() == OnboardingStates.waiting_for_timezone.state
    await session.refresh(user)
    assert user.timezone is None and user.onboarding_completed_at is None
