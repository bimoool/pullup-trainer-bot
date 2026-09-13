"""🔔 Напоминание о тренировке (issue #100) — тумблер + локальный час
push-уведомления "сегодня по плану тренировка" (см. app/workers/
training_reminder.py). Отдельный экран из "Профиля" (не часть "✏️ Изменить
профиль", profile_edit.py) — это настройка поведения бота, а не факт о
пользователе, поэтому обходится без FSM-состояний: каждое нажатие читает
актуальное значение из БД и сразу пишет обратно, экран просто
перерисовывается in-place (edit_text), без пошагового ввода."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import training_reminder_keyboard
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.domain.constants import DEFAULT_TRAINING_REMINDER_HOUR

router = Router()


def _resolve_hour(user: User) -> int:
    if user.training_reminder_hour is not None:
        return user.training_reminder_hour
    return DEFAULT_TRAINING_REMINDER_HOUR


def _status_text(user: User) -> str:
    hour = _resolve_hour(user)
    status = (
        texts.TRAINING_REMINDER_STATUS_ON.format(hour=hour)
        if user.training_reminder_enabled
        else texts.TRAINING_REMINDER_STATUS_OFF
    )
    text = f"{texts.TRAINING_REMINDER_HEADER}\n\n{status}"
    if user.training_reminder_enabled and not user.timezone:
        text += texts.TRAINING_REMINDER_NO_TIMEZONE_WARNING
    return text


def _keyboard(user: User) -> InlineKeyboardMarkup:
    return training_reminder_keyboard(
        enabled=user.training_reminder_enabled, hour=_resolve_hour(user),
    )


async def _render(message: Message, user: User) -> None:
    await message.edit_text(_status_text(user), reply_markup=_keyboard(user))


@router.callback_query(F.data == "training_reminder_open")
async def handle_training_reminder_open(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    await callback.message.answer(_status_text(user), reply_markup=_keyboard(user))
    await callback.answer()


@router.callback_query(F.data == "training_reminder_toggle")
async def handle_training_reminder_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    updated = await users.set_training_reminder(
        user.id, enabled=not user.training_reminder_enabled, hour=user.training_reminder_hour,
    )
    await _render(callback.message, updated)
    await callback.answer()


@router.callback_query(F.data.startswith("training_reminder_hour:"))
async def handle_training_reminder_hour(callback: CallbackQuery, session: AsyncSession) -> None:
    delta = int(callback.data.removeprefix("training_reminder_hour:"))
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    new_hour = (_resolve_hour(user) + delta) % 24
    updated = await users.set_training_reminder(
        user.id, enabled=user.training_reminder_enabled, hour=new_hour,
    )
    await _render(callback.message, updated)
    await callback.answer()


@router.callback_query(F.data == "training_reminder_noop")
async def handle_training_reminder_noop(callback: CallbackQuery) -> None:
    await callback.answer()
