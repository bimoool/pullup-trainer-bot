"""paywall_keyboard() — кнопка Робокассы появляется только когда переданы
ключи (без них ссылка на оплату гарантированно нерабочая)."""

from app.bot.keyboards import paywall_keyboard


def test_robokassa_button_hidden_by_default():
    markup = paywall_keyboard()

    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "pay_robokassa" not in callbacks
    assert "pay_tribute" in callbacks


def test_robokassa_button_shown_when_available():
    markup = paywall_keyboard(robokassa_available=True)

    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "pay_robokassa" in callbacks
    assert "pay_tribute" in callbacks
