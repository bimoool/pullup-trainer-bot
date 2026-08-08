from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import payment_link_keyboard
from app.db.models import SubscriptionSource
from app.db.repositories.users import UserRepository
from app.services.subscription import SubscriptionService
from app.services.tribute import SUBSCRIPTION_DAYS

router = Router()

# ЧЕРНОВИК: сумма в Stars не была явно продиктована в этой сессии ("как
# договаривались отдельно") — цифра ниже условная, заменить на согласованную.
STARS_PRICE = 200
STARS_SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60  # нативный период подписки Stars — 30 дней

SUBSCRIPTION_PAYLOAD_PREFIX = "subscription:"


@router.callback_query(F.data == "pay_stars")
async def handle_pay_stars(callback: CallbackQuery) -> None:
    link = await callback.bot.create_invoice_link(
        title="Подписка Pull-Up Trainer",
        description=f"Доступ на {SUBSCRIPTION_DAYS} дней",
        payload=f"{SUBSCRIPTION_PAYLOAD_PREFIX}{callback.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=STARS_PRICE)],
        subscription_period=STARS_SUBSCRIPTION_PERIOD_SECONDS,
    )
    await callback.message.answer("Оплата через Telegram Stars:", reply_markup=payment_link_keyboard(link))
    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    subscriptions = SubscriptionService(session)
    await subscriptions.extend(
        user.id,
        now=datetime.now(UTC),
        days=SUBSCRIPTION_DAYS,
        source=SubscriptionSource.STARS,
        payment_reference=message.successful_payment.telegram_payment_charge_id,
    )
    await message.answer("Подписка активирована — можно тренироваться!")
