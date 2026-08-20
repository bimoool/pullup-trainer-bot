from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import payment_link_keyboard, paywall_keyboard
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.domain.constants import SUBSCRIPTION_DAYS, SUBSCRIPTION_PRICE_RUB
from app.services.robokassa import RobokassaClient, RobokassaService

router = Router()


def _robokassa_available() -> bool:
    # password_2 обязателен наравне с password_1 — без него ссылка на
    # оплату создастся, но воркер никогда не подтвердит платёж (OpStateExt
    # подписывается именно password_2, см. app/services/robokassa.py).
    return bool(
        settings.robokassa_merchant_login and settings.robokassa_password_1 and settings.robokassa_password_2,
    )


async def send_paywall(message: Message, user: User) -> None:
    await message.answer(
        texts.TRIAL_ENDED.format(price=SUBSCRIPTION_PRICE_RUB, days=SUBSCRIPTION_DAYS),
        reply_markup=paywall_keyboard(robokassa_available=_robokassa_available()),
    )


@router.callback_query(F.data == "pay_robokassa")
async def handle_pay_robokassa(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    client = RobokassaClient(
        merchant_login=settings.robokassa_merchant_login,
        password_1=settings.robokassa_password_1,
        password_2=settings.robokassa_password_2,
    )
    robokassa = RobokassaService(session, client)
    link = await robokassa.create_payment_link(user.id)

    await callback.message.answer(texts.PAYMENT_LINK_SENT, reply_markup=payment_link_keyboard(link))
    await callback.answer()


# Кнопка "⭐ Оплатить Stars" (pay_stars) обрабатывается в payments_stars.py —
# нативные Stars-подписки живут отдельно от карточного потока этого файла.
