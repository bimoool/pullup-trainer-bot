"""«✏️ Изменить профиль» (Часть 10) — те же вопросы/валидация, что и в
анкете онбординга (app/bot/handlers/questionnaire.py), но по одному полю
за раз: не пересобирать весь профиль ради одного изменившегося числа."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.handlers.menu import render_profile
from app.bot.keyboards import cancel_keyboard, gender_keyboard, profile_edit_keyboard
from app.bot.states import ProfileEditStates
from app.bot.timezones import resolve_city_timezone
from app.db.models import Gender
from app.db.repositories.users import UserRepository

router = Router()

_FIELD_STATES = {
    "weight": ProfileEditStates.waiting_for_weight,
    "height": ProfileEditStates.waiting_for_height,
    "gender": ProfileEditStates.waiting_for_gender,
    "birth_date": ProfileEditStates.waiting_for_birth_date,
    "timezone": ProfileEditStates.waiting_for_timezone,
}


@router.callback_query(F.data == "profile_edit_open")
async def handle_profile_edit_open(callback: CallbackQuery) -> None:
    await callback.message.answer(texts.PROFILE_EDIT_HEADER, reply_markup=profile_edit_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_edit_close")
async def handle_profile_edit_close(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await render_profile(callback.message, session, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("profile_edit:"))
async def handle_profile_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.removeprefix("profile_edit:")
    await state.set_state(_FIELD_STATES[field])
    await callback.message.edit_reply_markup(reply_markup=None)

    if field == "weight":
        await callback.message.answer(texts.QUESTIONNAIRE_WEIGHT_PROMPT, reply_markup=cancel_keyboard())
    elif field == "height":
        await callback.message.answer(texts.QUESTIONNAIRE_HEIGHT_PROMPT, reply_markup=cancel_keyboard())
    elif field == "gender":
        await callback.message.answer(texts.QUESTIONNAIRE_GENDER_PROMPT, reply_markup=gender_keyboard())
    elif field == "birth_date":
        await callback.message.answer(texts.QUESTIONNAIRE_BIRTH_DATE_PROMPT, reply_markup=cancel_keyboard())
    elif field == "timezone":
        await callback.message.answer(texts.QUESTIONNAIRE_TIMEZONE_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


async def _save_and_confirm(
    message: Message, state: FSMContext, session: AsyncSession, *, telegram_id: int, **field,
) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)
    await users.update_profile(user.id, **field)
    await state.clear()
    await message.answer(texts.PROFILE_EDIT_DONE)
    await render_profile(message, session, telegram_id)


@router.message(ProfileEditStates.waiting_for_weight)
async def handle_edit_weight(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        value = Decimal((message.text or "").strip().replace(",", "."))
    except InvalidOperation:
        await message.answer(texts.QUESTIONNAIRE_WEIGHT_INVALID)
        return
    if value <= 0:
        await message.answer(texts.QUESTIONNAIRE_WEIGHT_INVALID)
        return
    await _save_and_confirm(message, state, session, telegram_id=message.from_user.id, weight_kg=value)


@router.message(ProfileEditStates.waiting_for_height)
async def handle_edit_height(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(texts.QUESTIONNAIRE_HEIGHT_INVALID)
        return
    await _save_and_confirm(message, state, session, telegram_id=message.from_user.id, height_cm=int(raw))


@router.callback_query(ProfileEditStates.waiting_for_gender, F.data.startswith("gender:"))
async def handle_edit_gender(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    gender = Gender(callback.data.removeprefix("gender:"))
    await callback.message.edit_reply_markup(reply_markup=None)
    await _save_and_confirm(callback.message, state, session, telegram_id=callback.from_user.id, gender=gender)
    await callback.answer()


@router.message(ProfileEditStates.waiting_for_birth_date)
async def handle_edit_birth_date(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        value = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").replace(tzinfo=UTC).date()
    except ValueError:
        await message.answer(texts.QUESTIONNAIRE_BIRTH_DATE_INVALID)
        return
    if value > datetime.now(UTC).date():
        await message.answer(texts.QUESTIONNAIRE_BIRTH_DATE_FUTURE)
        return
    await _save_and_confirm(message, state, session, telegram_id=message.from_user.id, birth_date=value)


@router.message(ProfileEditStates.waiting_for_timezone)
async def handle_edit_timezone(message: Message, state: FSMContext, session: AsyncSession) -> None:
    city = (message.text or "").strip()
    if not city:
        return
    await _save_and_confirm(
        message, state, session, telegram_id=message.from_user.id, timezone=resolve_city_timezone(city),
    )
