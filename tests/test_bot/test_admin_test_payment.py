"""Диагностический платёж Robokassa на 1₽ (админка) — та же ссылка и тот
же путь подтверждения, что у обычной подписки, только на 1₽ вместо
SUBSCRIPTION_PRICE_RUB. Реальным aiogram-роутингом, как test_admin_grants.py."""


from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.config import settings
from app.db.models import PendingPaymentStatus, User
from app.db.repositories.pending_payments import PendingPaymentRepository
from app.domain.constants import ADMIN_TEST_PAYMENT_AMOUNT_RUB
from tests.test_bot.conftest import make_callback_update as _callback_update


def _configure_robokassa(monkeypatch) -> None:
    monkeypatch.setattr(settings, "robokassa_merchant_login", "shop")
    monkeypatch.setattr(settings, "robokassa_password_1", "pass1")
    monkeypatch.setattr(settings, "robokassa_password_2", "pass2")


async def test_admin_menu_lists_test_payment_button(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_menu"), session=session,
    )

    [menu] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ADMIN_MENU_HEADER
    ]
    buttons = {b.text: b.callback_data for row in menu.reply_markup.inline_keyboard for b in row}
    assert buttons["🧪 Тестовый платёж 1₽"] == "admin_test_payment"


async def test_test_payment_denied_for_non_admin(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_test_payment"), session=session,
    )

    assert await PendingPaymentRepository(session).list_pending() == []


async def test_test_payment_blocked_when_robokassa_not_configured(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    monkeypatch.setattr(settings, "robokassa_merchant_login", "")
    monkeypatch.setattr(settings, "robokassa_password_1", "")
    monkeypatch.setattr(settings, "robokassa_password_2", "")

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_test_payment"), session=session,
    )

    assert await PendingPaymentRepository(session).list_pending() == []
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage)]
    assert texts.PAYMENT_LINK_SENT not in sent_texts


async def test_test_payment_creates_one_rub_link_for_admin(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    _configure_robokassa(monkeypatch)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="admin_test_payment"), session=session,
    )

    pending = await PendingPaymentRepository(session).list_pending()
    assert len(pending) == 1
    assert pending[0].status == PendingPaymentStatus.PENDING
    assert pending[0].days == 30  # обычный срок подписки, диагностика меняет только сумму

    [sent] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.PAYMENT_LINK_SENT
    ]
    [link_button] = [b for row in sent.reply_markup.inline_keyboard for b in row]
    assert f"OutSum={ADMIN_TEST_PAYMENT_AMOUNT_RUB}.00" in link_button.url
    assert f"InvId={pending[0].id}" in link_button.url


async def test_regular_paywall_link_unaffected_by_test_payment_defaults(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """Параметризация create_payment_link не должна менять поведение
    обычной оплаты подписки — значения по умолчанию остаются прежними."""
    _configure_robokassa(monkeypatch)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="pay_robokassa"), session=session,
    )

    pending = await PendingPaymentRepository(session).list_pending()
    assert len(pending) == 1
    assert pending[0].days == 30

    [sent] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.PAYMENT_LINK_SENT
    ]
    [link_button] = [b for row in sent.reply_markup.inline_keyboard for b in row]
    assert "OutSum=990.00" in link_button.url
