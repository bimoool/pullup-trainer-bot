"""Общая инфраструктура для тестов, гоняющих реальный aiogram-роутинг
(app.bot.handlers.router) через Dispatcher.feed_update — без единого
реального обращения к api.telegram.org. session-scope: Router можно
include_router() только один раз за время жизни объекта, поэтому Dispatcher
собирается один раз на весь тестовый прогон и переиспользуется между всеми
файлами в tests/test_bot/; общее MemoryStorage это не портит — каждый тест
сам выставляет своё FSM-состояние перед feed_update и проверяет после."""

from datetime import UTC, datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, TelegramObject

from app.bot.handlers import router as app_router

# Токен формально валиден для Bot(...) (цифры:остальное), реальных запросов
# не делает — все исходящие вызовы перехватывает StubSession ниже.
FAKE_TOKEN = "123456789:AAFakeTokenForBotTestsOnly000000000000000"


class StubSession(BaseSession):
    """Ни одного реального обращения к api.telegram.org — только чтобы
    message.answer()/callback.answer() внутри хендлеров не падали.

    sent_methods — все исходящие вызовы (send_message и т.п.) запоминаются
    как есть, чтобы тесты могли проверить не только побочные эффекты в БД,
    но и что реально отправлено (текст, reply_markup) — очищается перед
    каждым тестом отдельной fixture ниже, session-scope у bot/dispatcher
    иначе означал бы накопление между файлами."""

    def __init__(self) -> None:
        super().__init__()
        self.sent_methods: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramObject], timeout: int | None = None,
    ) -> TelegramObject:
        self.sent_methods.append(method)
        if isinstance(method.__returning__, bool | type(None)):  # answerCallbackQuery и т.п.
            return True
        return Message(
            message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="private"), text="stub",
        )

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - не используется в этих тестах
        yield b""


@pytest.fixture(scope="session")
def bot() -> Bot:
    return Bot(token=FAKE_TOKEN, session=StubSession())


@pytest.fixture(scope="session")
def dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(app_router)
    return dp


@pytest.fixture(autouse=True)
def _clear_sent_methods(bot: Bot):
    bot.session.sent_methods.clear()
    yield
    bot.session.sent_methods.clear()
