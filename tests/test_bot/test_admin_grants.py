"""Диагностика ручной выдачи подписки/монет из /admin — по запросу автора
после того, как предыдущий отчёт обошёл этот пункт молчанием. Проверяет
реальным aiogram-роутингом весь путь: /admin -> "Пользователи" -> карточка
пользователя -> "Выдать подписку"/"Начислить монеты" -> ввод числа ->
эффект в БД, плюс отказ в доступе для не-админа на каждом шаге."""

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import AdminStates
from app.config import settings
from app.db.models import SubscriptionStatus, User
from app.db.repositories.users import UserRepository
from app.services.subscription import SubscriptionService
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


# --- Главное меню /admin — кнопки действительно доступны сразу с первого экрана ------


async def test_admin_command_menu_lists_users_button_for_admin(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="/admin"), session=session)

    [menu] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_MENU_HEADER
    ]
    buttons = {b.text: b.callback_data for row in menu.reply_markup.inline_keyboard for b in row}
    assert buttons["👥 Пользователи"] == "admin_users"


async def test_admin_command_denied_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="/admin"), session=session)

    texts_sent = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    assert texts_sent == [texts.ADMIN_ACCESS_DENIED]


async def test_user_card_shows_grant_buttons(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"admin_user:{user.id}"), session=session,
    )

    [card] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and f"telegram_id: {user.telegram_id}" in m.text
    ]
    buttons = {b.text: b.callback_data for row in card.reply_markup.inline_keyboard for b in row}
    assert buttons["🎁 Выдать подписку"] == f"admin_grant_days:{user.id}"
    assert buttons["🪙 Начислить монеты"] == f"admin_grant_coins:{user.id}"


# --- Выдача подписки ------------------------------------------------------------------


async def test_grant_days_extends_subscription_for_target_user(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    assert user.subscription_status == SubscriptionStatus.NONE

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"admin_grant_days:{user.id}"), session=session,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == AdminStates.waiting_for_grant_days.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="30"), session=session)

    await session.refresh(user)
    assert user.subscription_status == SubscriptionStatus.ACTIVE
    assert user.subscription_expires_at is not None
    assert (user.subscription_expires_at - datetime.now(UTC)).days in (29, 30)
    assert await fsm.get_state() is None


async def test_grant_days_rejects_non_numeric_input(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(AdminStates.waiting_for_grant_days)
    await fsm.update_data(admin_target_user_id=user.id)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="тридцать"), session=session)

    await session.refresh(user)
    assert user.subscription_status == SubscriptionStatus.NONE
    assert await fsm.get_state() == AdminStates.waiting_for_grant_days.state


async def test_grant_days_denied_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    # Общий dispatcher/telegram_id между тестами файла (см. conftest.py) —
    # состояние из предыдущего теста, дошедшего до waiting_for_grant_days,
    # иначе просачивается сюда (тот же паттерн, что в test_edit_calendar.py).
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"admin_grant_days:{user.id}"), session=session,
    )

    assert await fsm.get_state() is None
    await session.refresh(user)
    assert user.subscription_status == SubscriptionStatus.NONE


# --- Начисление монет ------------------------------------------------------------------


async def test_grant_coins_adds_balance_for_target_user(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    assert user.coins_balance == 0

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"admin_grant_coins:{user.id}"), session=session,
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == AdminStates.waiting_for_grant_coins.state

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="100"), session=session)

    await session.refresh(user)
    assert user.coins_balance == 100
    assert await fsm.get_state() is None


async def test_grant_coins_accepts_negative_amount_as_correction(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await UserRepository(session).adjust_coins_balance(user.id, 50)
    await session.refresh(user)
    assert user.coins_balance == 50

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(AdminStates.waiting_for_grant_coins)
    await fsm.update_data(admin_target_user_id=user.id)

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="-20"), session=session)

    await session.refresh(user)
    assert user.coins_balance == 30


async def test_grant_coins_denied_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"admin_grant_coins:{user.id}"), session=session,
    )

    assert await fsm.get_state() is None
    await session.refresh(user)
    assert user.coins_balance == 0


# --- Дата окончания подписки — карточка и список (фидбек с реальной карточки) ---------


async def test_user_card_shows_subscription_expiry_date(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await SubscriptionService(session).grant_by_admin(user.id, now=datetime.now(UTC), days=14)
    await session.refresh(user)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"admin_user:{user.id}"), session=session,
    )

    [card] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and f"telegram_id: {user.telegram_id}" in m.text
    ]
    expected_date = user.subscription_expires_at.strftime("%d.%m.%Y")
    assert f"до {expected_date}" in card.text


async def test_user_card_shows_date_for_expired_subscription(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """Фидбек: заходил неделю назад — одно, полгода назад — совсем другое,
    админу нужна дата истечения при решении, продлевать ли и на сколько."""
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    expires_at = datetime.now(UTC) - timedelta(days=45)
    await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.EXPIRED, expires_at=expires_at,
    )
    await session.refresh(user)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"admin_user:{user.id}"), session=session,
    )

    [card] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and f"telegram_id: {user.telegram_id}" in m.text
    ]
    assert f"истекла {expires_at.strftime('%d.%m.%Y')}" in card.text


async def test_user_list_button_shows_subscription_status_and_date(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    await session.refresh(user)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_users"), session=session,
    )

    [listing] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_USERS_HEADER
    ]
    labels = [b.text for row in listing.reply_markup.inline_keyboard for b in row]
    expected_date = user.subscription_expires_at.strftime("%d.%m.%Y")
    assert any("пробный период" in label and expected_date in label for label in labels)


# --- Пуш пользователю о продлении подписки (фидбек: раньше выдача проходила тихо) -----


async def test_grant_days_sends_push_to_target_user(session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    admin = await UserRepository(session).create(telegram_id=9001, username="admin_account")
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=admin.telegram_id, data=f"admin_grant_days:{user.id}"), session=session,
    )
    await dispatcher.feed_update(bot, _message_update(telegram_id=admin.telegram_id, text="14"), session=session)

    await session.refresh(user)
    expected_date = user.subscription_expires_at.strftime("%d.%m.%Y")
    [push] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == user.telegram_id
    ]
    assert push.text == texts.ADMIN_SUBSCRIPTION_EXTENDED_PUSH.format(days=14, expires_at=expected_date)

    # Админу отдельно приходит своё подтверждение в СВОЙ чат, не в чат цели.
    admin_confirmations = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
    ]
    assert any("Подписка на 14 дней выдана" in (m.text or "") for m in admin_confirmations)


async def test_grant_days_push_failure_does_not_block_the_extension(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    admin = await UserRepository(session).create(telegram_id=9002, username="admin_account_2")
    monkeypatch.setattr(settings, "admin_ids", str(admin.telegram_id))

    async def _raise_forbidden(chat_id, text, **kwargs):
        raise TelegramForbiddenError(
            SendMessage(chat_id=chat_id, text=text), "Forbidden: bot was blocked by the user",
        )

    monkeypatch.setattr(bot, "send_message", _raise_forbidden)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=admin.telegram_id, data=f"admin_grant_days:{user.id}"), session=session,
    )
    await dispatcher.feed_update(bot, _message_update(telegram_id=admin.telegram_id, text="14"), session=session)

    await session.refresh(user)
    assert user.subscription_status == SubscriptionStatus.ACTIVE
    assert (user.subscription_expires_at - datetime.now(UTC)) > timedelta(days=13)

    # Админу всё равно пришло подтверждение — сбой пуша не сломал остальной хендлер.
    admin_confirmations = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == admin.telegram_id
        and "Подписка на 14 дней выдана" in (m.text or "")
    ]
    assert len(admin_confirmations) == 1
