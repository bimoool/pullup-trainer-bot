"""Тарифы/реквизиты/оферта доступны изнутри бота (требование модерации
Робокассы, не только внешний канал @pulluptrainerinfo) — кнопка «💳 Тарифы
и реквизиты» в разделе «❓ Помощь». Оферта уходит PDF-файлом (app/assets/
oferta.pdf), не ссылкой. Реальным aiogram-роутингом."""

from aiogram import Bot, Dispatcher
from aiogram.methods import SendDocument, SendMessage
from aiogram.types import FSInputFile

from app.bot import texts
from app.bot.handlers.menu import OFERTA_PDF_PATH
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


def test_oferta_pdf_asset_exists_on_disk():
    # Не просто "путь настроен" — сам файл обязан лежать в репозитории
    # (app/assets/oferta.pdf), иначе FSInputFile упадёт в рантайме на
    # первом же нажатии кнопки.
    assert OFERTA_PDF_PATH.is_file()
    assert OFERTA_PDF_PATH.read_bytes()[:4] == b"%PDF"


async def test_tapping_pricing_button_sends_pricing_text(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="pricing_info"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert texts.PRICING_TEXT in sent_texts


async def test_tapping_pricing_button_sends_oferta_document(session, user: User, bot: Bot, dispatcher: Dispatcher):
    """Ключевая проверка: документ реально отправляется отдельным вызовом
    (SendDocument), не просто упомянут в тексте."""
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="pricing_info"), session=session,
    )

    [send_document] = [m for m in bot.session.sent_methods if isinstance(m, SendDocument)]
    assert isinstance(send_document.document, FSInputFile)
    assert send_document.document.path == OFERTA_PDF_PATH


async def test_pricing_text_sent_before_document_in_same_action(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Оба сообщения (текст + документ) — в одном действии по кнопке, текст
    первым, документ следом (не в двух разных местах бота)."""
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="pricing_info"), session=session,
    )

    methods = [m for m in bot.session.sent_methods if isinstance(m, SendMessage | SendDocument)]
    text_index = next(i for i, m in enumerate(methods) if isinstance(m, SendMessage) and m.text == texts.PRICING_TEXT)
    document_index = next(i for i, m in enumerate(methods) if isinstance(m, SendDocument))
    assert text_index < document_index


def test_pricing_text_contains_required_moderation_fields():
    """Robokassa требует конкретно: цена, порядок оформления, условия
    возврата, реквизиты исполнителя. Полный текст оферты теперь уходит
    файлом (см. test_tapping_pricing_button_sends_oferta_document), не
    ссылкой на канал — здесь текст только анонсирует, что файл ниже."""
    body = texts.PRICING_TEXT
    assert "990" in body
    assert "14 дней" in body
    assert "возврат" in body.lower()
    assert "667354733620" in body  # ИНН
    assert "324665800108241" in body  # ОГРН/ОГРНИП
    assert "kirillvozzhaev99@gmail.com" in body
    assert "оферты" in body.lower()
    assert "https://t.me/pulluptrainerinfo" not in body
