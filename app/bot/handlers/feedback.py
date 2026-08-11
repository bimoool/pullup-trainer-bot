import logging
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import cancel_keyboard, feedback_admin_reply_keyboard
from app.bot.states import FeedbackStates
from app.config import settings
from app.db.repositories.events import EventRepository
from app.db.repositories.users import UserRepository

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "report_problem")
async def handle_report_problem_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting_for_text)
    await callback.message.answer(texts.FEEDBACK_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(FeedbackStates.waiting_for_text)
async def handle_report_problem_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    now = datetime.now(UTC)
    who = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"

    # Пишем событие даже если ни одно личное уведомление админу не
    # доставится (например, у бота нет диалога с админом) — так фидбек не
    # теряется и виден в общей аналитике/Google Sheets.
    await EventRepository(session).create(
        user_id=user.id,
        event_type="feedback_reported",
        payload={"text": message.text, "user_id": user.id, "created_at": now.isoformat()},
    )

    notification = texts.FEEDBACK_ADMIN_NOTIFICATION.format(
        who=who, when=now.strftime("%d.%m.%Y %H:%M"), text=message.text,
    )
    for admin_id in settings.admin_id_list:
        try:
            await message.bot.send_message(
                admin_id, notification, parse_mode=None, reply_markup=feedback_admin_reply_keyboard(user.id),
            )
        except TelegramAPIError:
            logger.warning("feedback: failed to notify admin %s", admin_id, exc_info=True)

    await state.clear()
    await message.answer(texts.FEEDBACK_DONE)
