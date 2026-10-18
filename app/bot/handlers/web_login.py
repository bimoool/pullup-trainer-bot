"""Вход в браузере через бота (WEB-AUTH): /start weblogin_<id> и кнопки «Подтвердить»/«Отмена».

CLAUDE.md: telegram_id берём ТОЛЬКО из callback.from_user (callback.message.from_user — это бот)."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.services import web_login

router = Router()

CB_APPROVE = "wl:ok:"
CB_DENY = "wl:no:"


def confirm_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=texts.WEB_LOGIN_BTN_CONFIRM, callback_data=f"{CB_APPROVE}{request_id}"),
        InlineKeyboardButton(text=texts.WEB_LOGIN_BTN_CANCEL, callback_data=f"{CB_DENY}{request_id}"),
    ]])


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(web_login.START_PAYLOAD_PREFIX)))
async def handle_web_login_start(
    message: Message, command: CommandObject, session: AsyncSession,
) -> None:
    request_id = (command.args or "")[len(web_login.START_PAYLOAD_PREFIX):]
    result = await web_login.open_request(session, request_id, message.from_user.id)
    if result.status == "taken":
        await message.answer(texts.WEB_LOGIN_TAKEN)
        return
    if result.status != "ok":
        await message.answer(texts.WEB_LOGIN_GONE)
        return
    await message.answer(texts.WEB_LOGIN_PROMPT.format(code=result.code), reply_markup=confirm_keyboard(request_id))


@router.callback_query(F.data.startswith(CB_APPROVE))
async def handle_web_login_approve(callback: CallbackQuery, session: AsyncSession) -> None:
    request_id = callback.data[len(CB_APPROVE):]
    # Нажавший — callback.from_user, не callback.message.from_user (там бот).
    ok = await web_login.approve_request(
        session, request_id, telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name, username=callback.from_user.username,
    )
    await callback.message.edit_text(texts.WEB_LOGIN_APPROVED if ok else texts.WEB_LOGIN_GONE)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_DENY))
async def handle_web_login_deny(callback: CallbackQuery, session: AsyncSession) -> None:
    request_id = callback.data[len(CB_DENY):]
    ok = await web_login.deny_request(session, request_id, telegram_id=callback.from_user.id)
    await callback.message.edit_text(texts.WEB_LOGIN_DENIED if ok else texts.WEB_LOGIN_GONE)
    await callback.answer()
