"""issue #141: после ONBOARDING_INTRO новый пользователь ведётся сразу в
Mini App (OnboardingScreen.tsx, issue #124) кнопкой, а не в текстовый ввод в
чате бота. Текстовый путь (waiting_for_baseline_reps) остаётся рабочим как
запасной — на случай, если Mini App ещё не настроена на этом окружении
(settings.mini_app_url пуст, тот же принцип условной видимости, что и у
постоянной Menu Button, см. test_menu_button.py), и как фолбэк, если
пользователь проигнорирует кнопку и всё равно напишет число в чат."""

from datetime import UTC, datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import select

from app.bot import texts
from app.bot.states import OnboardingStates
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository


def _start_update(telegram_id: int, username: str | None = None) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=1, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester", username=username),
            text="/start",
        ),
    )


async def test_start_offers_mini_app_button_when_configured(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "mini_app_url", "https://app.bimoool.com")
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await dispatcher.feed_update(bot, _start_update(user.telegram_id), session=session)

    sent = [m for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    cta_message = sent[-1]
    assert cta_message.text == texts.ONBOARDING_OPEN_MINI_APP
    button = cta_message.reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == "https://app.bimoool.com"
    # Текстовый путь всё ещё доступен: состояние уже выставлено на ввод
    # числа, как и до этого issue — кнопка не единственный способ пройти
    # дальше.
    assert await fsm.get_state() == OnboardingStates.waiting_for_baseline_reps.state


async def test_start_falls_back_to_text_flow_when_mini_app_not_configured(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "mini_app_url", "")
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)

    await dispatcher.feed_update(bot, _start_update(user.telegram_id), session=session)

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    assert texts.ONBOARDING_WHAT_NEXT in sent_texts
    assert texts.BASELINE_GUIDE in sent_texts
    assert texts.ONBOARDING_OPEN_MINI_APP not in sent_texts
    assert await fsm.get_state() == OnboardingStates.waiting_for_baseline_reps.state


@pytest.mark.parametrize("legacy_username", [None, "synthetic_old_username"])
async def test_start_does_not_capture_username_or_replace_existing_user(
    session, bot: Bot, dispatcher: Dispatcher, legacy_username,
):
    users = UserRepository(session)
    telegram_id = 61001
    previous = (
        await users.create(telegram_id=telegram_id, username=legacy_username)
        if legacy_username is not None else None
    )

    for incoming_username in ("synthetic_new_username", "synthetic_renamed_username"):
        await dispatcher.feed_update(
            bot, _start_update(telegram_id, username=incoming_username), session=session,
        )
        current = await users.get_by_telegram_id(telegram_id)
        assert current is not None
        if previous is not None:
            assert current.id == previous.id
        # Read the persisted column, rather than relying on the ORM identity cache.
        stored_username = await session.scalar(select(User.username).where(User.id == current.id))
        assert stored_username == legacy_username
        previous = current
