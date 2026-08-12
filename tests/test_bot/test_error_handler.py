"""Глобальный обработчик необработанных исключений (Часть 10) — после
диагностики бага "Пропустить у комментария теряет тренировку молча"
пользователь попросил сеть безопасности на уровне диспетчера: любое
необработанное исключение должно логироваться, показываться пользователю
понятным сообщением и попадать в events + личку админу, а не гасить update
в тишине aiogram'а. Гоняет ИЗОЛИРОВАННЫЙ Dispatcher с фиктивным
гарантированно падающим хендлером — не трогает общий router/dispatcher
из conftest.py, чтобы не протаскивать тестовый "бомбовый" хендлер в
остальные тесты tests/test_bot/."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.error_handler import register_error_handler
from app.config import settings
from app.db.models import User
from app.db.repositories.events import EventRepository
from tests.test_bot.conftest import BOT_TELEGRAM_ID


def _make_boom_update(*, telegram_id: int) -> Update:
    message = Message(
        message_id=100, date=datetime.now(UTC),
        chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=BOT_TELEGRAM_ID, is_bot=True, first_name="Bot"),
        text="stub",
    )
    return Update(
        update_id=777,
        callback_query=CallbackQuery(
            id="1",
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            chat_instance="1",
            data="__test_boom__",
            message=message,
        ),
    )


def _build_isolated_dispatcher() -> Dispatcher:
    """Собственный Dispatcher+Router с одним намеренно падающим хендлером —
    register_error_handler подключается ровно так же, как в app/main.py."""
    boom_router = Router()

    @boom_router.callback_query(F.data == "__test_boom__")
    async def _boom(callback: CallbackQuery) -> None:
        raise RuntimeError("намеренная ошибка теста")

    dispatcher = Dispatcher(storage=MemoryStorage())
    register_error_handler(dispatcher)
    dispatcher.include_router(boom_router)
    return dispatcher


async def test_unhandled_exception_is_caught_logged_and_reported(
    session: AsyncSession, user: User, bot: Bot, monkeypatch, test_dsn,
):
    # error_handler открывает свою сессию через async_session_factory —
    # подменяем её на фабрику от той же тестовой БД (test_dsn), иначе она бы
    # пыталась резолвить прод-хост "db" из DATABASE_URL и падала бы локально
    # (см. app/db/base.py — engine строится от settings.database_url при
    # импорте, что годится для прод-контейнера, но не для локального pytest).
    test_engine = create_async_engine(test_dsn)
    test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.bot.error_handler.async_session_factory", test_session_factory)
    monkeypatch.setattr(settings, "admin_ids", "999999")
    # error_handler пишет через ОТДЕЛЬНОЕ соединение (см. комментарий выше) —
    # без коммита здесь пользователь виден только внутри транзакции фикстуры
    # session и невидим для того соединения (обычный MVCC, не баг).
    await session.commit()

    dispatcher = _build_isolated_dispatcher()

    # Диспетчер не должен пробросить исключение наружу — если упадёт здесь,
    # сеть безопасности не сработала и бот бы рухнул целиком.
    await dispatcher.feed_update(bot, _make_boom_update(telegram_id=user.telegram_id))

    await test_engine.dispose()

    sent_to_user = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == user.telegram_id
    ]
    assert len(sent_to_user) == 1
    assert "пошло не так" in sent_to_user[0].text

    admin_notifications = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == 999999
    ]
    assert len(admin_notifications) == 1
    assert str(user.telegram_id) in admin_notifications[0].text
    assert "намеренная ошибка теста" in admin_notifications[0].text

    events = await EventRepository(session).list_for_user(user.id)
    exception_events = [e for e in events if e.event_type == "unhandled_exception"]
    assert len(exception_events) == 1
    assert exception_events[0].payload["update_id"] == 777
    assert "намеренная ошибка теста" in exception_events[0].payload["exception"]


async def test_unhandled_exception_clears_fsm_state(session: AsyncSession, user: User, bot: Bot, monkeypatch, test_dsn):
    from app.bot.states import WorkoutStates

    test_engine = create_async_engine(test_dsn)
    test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.bot.error_handler.async_session_factory", test_session_factory)
    await session.commit()

    dispatcher = _build_isolated_dispatcher()
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_comment)

    await dispatcher.feed_update(bot, _make_boom_update(telegram_id=user.telegram_id))
    await test_engine.dispose()

    assert await fsm.get_state() is None


async def test_unhandled_exception_without_known_user_does_not_crash(bot: Bot, monkeypatch, test_dsn):
    """Апдейт от telegram_id, которого нет в users (гипотетический случай —
    _record_unhandled_exception сама ищет пользователя и тихо выходит, если
    не нашла) — обработчик не должен падать даже без записи события."""
    test_engine = create_async_engine(test_dsn)
    test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.bot.error_handler.async_session_factory", test_session_factory)

    dispatcher = _build_isolated_dispatcher()
    await dispatcher.feed_update(bot, _make_boom_update(telegram_id=999_999_999))
    await test_engine.dispose()

    sent_to_user = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.chat_id == 999_999_999
    ]
    assert len(sent_to_user) == 1
