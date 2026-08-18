"""Тарифы/реквизиты/оферта доступны изнутри бота (требование модерации
Робокассы, не только внешний канал @pulluptrainerinfo) — кнопка «💳 Тарифы
и реквизиты» в разделе «❓ Помощь». Реальным aiogram-роутингом."""

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.bot.keyboards import help_keyboard
from app.db.models import User
from tests.test_bot.conftest import make_callback_update as _callback_update


def test_pricing_button_is_in_help_keyboard():
    markup = help_keyboard()

    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "pricing_info" in callbacks


def test_pricing_button_uses_configured_label():
    markup = help_keyboard()

    buttons = {button.callback_data: button.text for row in markup.inline_keyboard for button in row}
    assert buttons["pricing_info"] == texts.PRICING_BUTTON


async def test_tapping_pricing_button_sends_pricing_text(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="pricing_info"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert texts.PRICING_TEXT in sent_texts


def test_pricing_text_contains_required_moderation_fields():
    """Robokassa требует конкретно: цена, порядок оформления, условия
    возврата, реквизиты исполнителя, ссылка на полный текст оферты."""
    body = texts.PRICING_TEXT
    assert "990" in body
    assert "14 дней" in body
    assert "возврат" in body.lower()
    assert "667354733620" in body  # ИНН
    assert "324665800108241" in body  # ОГРН/ОГРНИП
    assert "kirillvozzhaev99@gmail.com" in body
    assert "https://t.me/pulluptrainerinfo" in body
