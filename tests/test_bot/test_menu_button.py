"""Menu button (значок слева от поля ввода) — единственный способ открытия
Mini App, для которого Telegram официально гарантирует непустую initData
(issue #30, docs.telegram-mini-apps.com/platform/init-data). Раньше кнопка
жила в нижней клавиатуре (KeyboardButton.web_app) — тот способ запуска
документированно отдаёт initData пустой, это и было первопричиной
"чёрного экрана"/ошибки инициализации (issue #23/#28), не баг SDK и не
кэш."""

from aiogram import Bot
from aiogram.methods import SetChatMenuButton
from aiogram.types import MenuButtonDefault, MenuButtonWebApp

from app.config import settings
from app.main import configure_menu_button


async def test_menu_button_falls_back_to_default_when_url_not_configured(bot: Bot, monkeypatch):
    monkeypatch.setattr(settings, "mini_app_url", "")

    await configure_menu_button(bot)

    [call] = [m for m in bot.session.sent_methods if isinstance(m, SetChatMenuButton)]
    assert isinstance(call.menu_button, MenuButtonDefault)


async def test_menu_button_opens_mini_app_when_url_configured(bot: Bot, monkeypatch):
    monkeypatch.setattr(settings, "mini_app_url", "https://app.bimoool.com")

    await configure_menu_button(bot)

    [call] = [m for m in bot.session.sent_methods if isinstance(m, SetChatMenuButton)]
    assert isinstance(call.menu_button, MenuButtonWebApp)
    assert call.menu_button.web_app.url == "https://app.bimoool.com"
