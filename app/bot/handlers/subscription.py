from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import payment_link_keyboard, paywall_keyboard
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.services.tribute import (
    SUBSCRIPTION_DAYS,
    SUBSCRIPTION_PRICE_RUB,
    TributeClient,
    TributeService,
)

router = Router()


async def send_paywall(message: Message, user: User) -> None:
    await message.answer(
        texts.TRIAL_ENDED.format(price=SUBSCRIPTION_PRICE_RUB, days=SUBSCRIPTION_DAYS),
        reply_markup=paywall_keyboard(),
    )


@router.callback_query(F.data == "pay_tribute")
async def handle_pay_tribute(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    client = TributeClient(settings.tribute_api_key)
    tribute = TributeService(session, client)
    order = await tribute.create_payment_link(user.id)

    link = order.payment_url or order.webapp_payment_url
    await callback.message.answer(texts.PAYMENT_LINK_SENT, reply_markup=payment_link_keyboard(link))
    await callback.answer()


# Кнопка "⭐ Оплатить Stars" (pay_stars) обрабатывается в payments_stars.py —
# нативные Stars-подписки живут отдельно от Tribute-потока этого файла.
