"""Глобальная сеть безопасности на уровне диспетчера (Часть 10) — любое
необработанное исключение в любом хендлере раньше просто гасилось aiogram'ом
молча (см. диагностику бага "Пропустить" у комментария: тренировка терялась
без единого сообщения об ошибке, а узнать об этом можно было только вручную
читая логи VPS в момент падения). Теперь: полная трассировка в лог,
понятное сообщение пользователю, событие в БД (event_type=
"unhandled_exception", отдельно от ручных "feedback_reported") и личное
уведомление админу — тот же канал, что и у "Сообщить о проблеме"."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import ErrorEvent, Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.config import settings
from app.db.base import async_session_factory
from app.db.repositories.events import EventRepository
from app.db.repositories.users import UserRepository

logger = logging.getLogger(__name__)


def _extract_context(update: Update) -> tuple[int | None, int | None]:
    """(chat_id, telegram_id) — best-effort по типу апдейта: не для всех
    типов есть оба (например у pre_checkout_query нет chat)."""
    if update.message is not None:
        user = update.message.from_user
        return update.message.chat.id, user.id if user else None
    if update.callback_query is not None:
        chat_id = update.callback_query.message.chat.id if update.callback_query.message else None
        return chat_id, update.callback_query.from_user.id
    if update.pre_checkout_query is not None:
        return None, update.pre_checkout_query.from_user.id
    return None, None


async def _record_unhandled_exception(
    session: AsyncSession, *, telegram_id: int, update_id: int, exception: BaseException,
) -> None:
    """Отдельно от открытия сессии — тестируется напрямую с уже готовым
    session (тот же приём, что и RobokassaService против sync_robokassa_payments:
    воркер/хендлер открывает свою сессию, логика — чистая функция)."""
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        return
    await EventRepository(session).create(
        user_id=user.id,
        event_type="unhandled_exception",
        payload={"update_id": update_id, "exception": repr(exception)},
    )


def register_error_handler(dispatcher: Dispatcher) -> None:
    @dispatcher.errors()
    async def handle_unhandled_exception(
        event: ErrorEvent, bot: Bot, state: FSMContext | None = None,
    ) -> bool:
        # Внешний try/except на весь хендлер целиком — это последняя линия
        # обороны, у неё самой не должно быть возможности уронить бота, даже
        # если в самом хендлере ошибок есть баг.
        try:
            logger.error(
                "Необработанное исключение при обработке update id=%s",
                event.update.update_id, exc_info=event.exception,
            )

            chat_id, telegram_id = _extract_context(event.update)

            if state is not None:
                # Сбрасываем состояние — иначе "попробуй ещё раз" в
                # сообщении ниже может означать повторный тап по тому же
                # сломанному шагу того же сценария.
                await state.clear()

            if chat_id is not None:
                try:
                    await bot.send_message(chat_id, texts.UNEXPECTED_ERROR_MESSAGE)
                except TelegramAPIError:
                    logger.warning("error_handler: не удалось уведомить пользователя", exc_info=True)

            if telegram_id is not None:
                # Своя сессия, не data["session"]: DbSessionMiddleware к этому
                # моменту уже откатил и закрыл ту сессию — исключение прошло
                # через её `async with` до того, как долетело сюда.
                async with async_session_factory() as session:
                    try:
                        await _record_unhandled_exception(
                            session, telegram_id=telegram_id,
                            update_id=event.update.update_id, exception=event.exception,
                        )
                        await session.commit()
                    except Exception:
                        logger.exception("error_handler: не удалось записать unhandled_exception в events")

                notification = texts.ADMIN_UNHANDLED_EXCEPTION_NOTIFICATION.format(
                    telegram_id=telegram_id, update_id=event.update.update_id, exception=repr(event.exception),
                )
                for admin_id in settings.admin_id_list:
                    try:
                        await bot.send_message(admin_id, notification, parse_mode=None)
                    except TelegramAPIError:
                        logger.warning("error_handler: не удалось уведомить админа %s", admin_id, exc_info=True)
        except Exception:
            logger.exception("error_handler: внутренний сбой в самом обработчике ошибок")

        return True
