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
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject, Update
from aiogram.types import User as TgUser

from app.bot.handlers import router as app_router

# Токен формально валиден для Bot(...) (цифры:остальное), реальных запросов
# не делает — все исходящие вызовы перехватывает StubSession ниже.
FAKE_TOKEN = "123456789:AAFakeTokenForBotTestsOnly000000000000000"
BOT_TELEGRAM_ID = 123456789  # id из FAKE_TOKEN — см. make_callback_update ниже


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


def make_callback_update(*, telegram_id: int, data: str, message_id: int = 100) -> Update:
    """Общий конструктор Update с CallbackQuery для всех тестов
    tests/test_bot/ — раньше каждый файл держал свою локальную копию, и все
    они ошибочно ставили message.from_user = нажавший кнопку пользователь.

    В реальном Telegram сообщение, к которому прикреплена inline-кнопка,
    отправлено БОТОМ — callback.message.from_user всегда бот, а не тот, кто
    нажал; нажавший доступен только через callback.from_user. Ошибочная
    локальная копия маскировала реальный прод-баг (Часть 10): несколько
    хендлеров брали telegram_id через message.from_user.id вместо
    callback.from_user.id и падали на AttributeError (user из БД не
    находился — id бота там не зарегистрирован), теряя данные молча.
    См. workout.py::_finalize_workout, backdate.py::finalize_backdated_workout,
    menu.py::render_profile, profile_edit.py::_save_and_confirm."""
    message = Message(
        message_id=message_id, date=datetime.now(UTC),
        chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=BOT_TELEGRAM_ID, is_bot=True, first_name="Bot"),
        text="stub",
    )
    return Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="1",
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester", username="tester"),
            chat_instance="1",
            data=data,
            message=message,
        ),
    )
