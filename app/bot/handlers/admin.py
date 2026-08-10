import logging
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import (
    admin_menu_keyboard,
    admin_reset_confirm_keyboard,
    admin_user_card_keyboard,
    admin_user_list_keyboard,
    cancel_keyboard,
    profile_keyboard,
)
from app.bot.states import AdminStates
from app.config import settings
from app.db.models import SubscriptionStatus, User
from app.db.repositories.users import UserRepository
from app.services.admin import FUNNEL_STEPS, AdminService, UserCard
from app.services.admin_reset import reset_user_progress
from app.services.gamification import GamificationService
from app.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

router = Router()

_SUBSCRIPTION_LABELS = {
    SubscriptionStatus.NONE: "нет подписки",
    SubscriptionStatus.TRIAL: "пробный период",
    SubscriptionStatus.ACTIVE: "активна",
    SubscriptionStatus.EXPIRED: "истекла",
}


def _is_admin(telegram_id: int) -> bool:
    return settings.is_admin(telegram_id)


def _user_label(user: User) -> str:
    return f"@{user.username}" if user.username else f"id {user.telegram_id}"


@router.message(Command("admin"))
async def handle_admin_command(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(texts.ADMIN_ACCESS_DENIED)
        return
    await state.clear()
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


@router.callback_query(F.data == "admin_menu")
async def handle_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await state.clear()
    await callback.message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))
    await callback.answer()


@router.callback_query(F.data == "admin_funnel")
async def handle_admin_funnel(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    funnel = await AdminService(session).compute_funnel()
    text = texts.ADMIN_FUNNEL_HEADER
    for step in FUNNEL_STEPS:
        users = funnel.steps[step]
        if not users:
            text += texts.ADMIN_FUNNEL_STEP_EMPTY.format(step=step)
            continue
        lines = "\n".join(
            texts.ADMIN_FUNNEL_USER_LINE.format(username=u.username or "—", telegram_id=u.telegram_id) for u in users
        )
        text += texts.ADMIN_FUNNEL_STEP.format(step=step, count=len(users), users=lines)

    await callback.message.answer(text, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))
    await callback.answer()


@router.callback_query(F.data == "admin_users")
async def handle_admin_users(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    users = await UserRepository(session).list_all()
    await callback.message.answer(texts.ADMIN_USERS_HEADER, reply_markup=admin_user_list_keyboard(users))
    await callback.answer()


def _format_user_card(card: UserCard) -> str:
    user = card.user
    subscription = _SUBSCRIPTION_LABELS[user.subscription_status]
    return texts.ADMIN_USER_CARD.format(
        name=_user_label(user), telegram_id=user.telegram_id,
        baseline_count=card.baseline_count, workout_count=card.workout_count,
        target_a=card.target_a.target, target_b=card.target_b.target,
        subscription=subscription, coins=user.coins_balance,
    )


@router.callback_query(F.data.startswith("admin_user:"))
async def handle_admin_user_card(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_user:"))
    user = await UserRepository(session).get_by_id(user_id)
    card = await AdminService(session).build_user_card(user)

    await callback.message.answer(_format_user_card(card), reply_markup=admin_user_card_keyboard(user_id))
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def handle_admin_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await callback.message.answer(texts.ADMIN_BROADCAST_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast_text)
async def handle_admin_broadcast_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    # parse_mode=None: бот по умолчанию шлёт HTML (см. app/main.py), а это
    # текст, который набрал админ, не наш шаблон — случайные "<"/"&" не
    # должны ронять рассылку ошибкой парсинга сущностей.
    users = await UserRepository(session).list_onboarded()
    sent = 0
    for user in users:
        try:
            await message.bot.send_message(user.telegram_id, message.text, parse_mode=None)
            sent += 1
        except TelegramAPIError:
            logger.warning("admin broadcast: failed to notify user %s", user.telegram_id, exc_info=True)

    await state.clear()
    await message.answer(texts.ADMIN_BROADCAST_DONE.format(sent=sent, total=len(users)))
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


@router.callback_query(F.data.startswith("admin_dm:"))
async def handle_admin_dm_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_dm:"))
    user = await UserRepository(session).get_by_id(user_id)
    await state.update_data(admin_target_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_dm_text)
    await callback.message.answer(texts.ADMIN_DM_PROMPT.format(name=_user_label(user)), reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(AdminStates.waiting_for_dm_text)
async def handle_admin_dm_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    user = await UserRepository(session).get_by_id(data["admin_target_user_id"])

    try:
        await message.bot.send_message(user.telegram_id, message.text, parse_mode=None)
        await message.answer(texts.ADMIN_DM_DONE)
    except TelegramAPIError:
        await message.answer(texts.ADMIN_DM_FAILED)

    await state.clear()
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


@router.callback_query(F.data.startswith("admin_grant_days:"))
async def handle_admin_grant_days_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_grant_days:"))
    user = await UserRepository(session).get_by_id(user_id)
    await state.update_data(admin_target_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_grant_days)
    await callback.message.answer(
        texts.ADMIN_GRANT_DAYS_PROMPT.format(name=_user_label(user)), reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_grant_days)
async def handle_admin_grant_days_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer(texts.ADMIN_GRANT_INVALID_NUMBER)
        return
    if days <= 0:
        await message.answer(texts.ADMIN_GRANT_INVALID_NUMBER)
        return

    data = await state.get_data()
    user = await UserRepository(session).get_by_id(data["admin_target_user_id"])
    await SubscriptionService(session).grant_by_admin(user.id, now=datetime.now(UTC), days=days)

    await state.clear()
    await message.answer(texts.ADMIN_GRANT_DAYS_DONE.format(days=days, name=_user_label(user)))
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


@router.callback_query(F.data.startswith("admin_grant_coins:"))
async def handle_admin_grant_coins_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_grant_coins:"))
    user = await UserRepository(session).get_by_id(user_id)
    await state.update_data(admin_target_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_grant_coins)
    await callback.message.answer(
        texts.ADMIN_GRANT_COINS_PROMPT.format(name=_user_label(user)), reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_grant_coins)
async def handle_admin_grant_coins_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer(texts.ADMIN_GRANT_INVALID_NUMBER)
        return

    data = await state.get_data()
    user = await UserRepository(session).get_by_id(data["admin_target_user_id"])
    await GamificationService(session).grant_coins_by_admin(user.id, amount)

    await state.clear()
    await message.answer(texts.ADMIN_GRANT_COINS_DONE.format(amount=amount, name=_user_label(user)))
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


# --- Полный сброс СВОЕГО (админа) аккаунта — инструмент для ручного
# тестирования (Часть 9), кнопка в Профиле, а не в списке пользователей:
# в отличие от остальной админки выше, здесь нет admin_target_user_id —
# действие всегда над собственным аккаунтом вызвавшего.


@router.callback_query(F.data == "admin_reset_prompt")
async def handle_admin_reset_prompt(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.message.answer(texts.ADMIN_RESET_WARNING, reply_markup=admin_reset_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_reset_cancel")
async def handle_admin_reset_cancel(callback: CallbackQuery) -> None:
    await callback.answer(texts.CANCELLED)


@router.callback_query(F.data == "admin_reset_confirm")
async def handle_admin_reset_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    await reset_user_progress(session, user.id)

    await state.clear()
    await callback.message.answer(texts.ADMIN_RESET_DONE, reply_markup=profile_keyboard(is_admin=True))
    await callback.answer()
