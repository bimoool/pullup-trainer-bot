from datetime import UTC, date, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import (
    bottom_menu_keyboard,
    gender_keyboard,
    questionnaire_birth_date_keyboard,
    timezone_choice_keyboard,
)
from app.bot.states import OnboardingStates
from app.bot.timezones import TIMEZONE_DISPLAY_LABELS
from app.config import settings
from app.db.models import Gender, SubscriptionStatus
from app.db.repositories.users import UserRepository
from app.domain.constants import TRIAL_DAYS
from app.services.onboarding import OnboardingService

router = Router()


async def _gender(message: Message, state: FSMContext) -> None:
    # A deployment may resume Redis FSM created by the old compulsory questionnaire.
    data = await state.get_data()
    await state.set_data({key: value for key, value in data.items() if key not in ("weight_kg", "height_cm")})
    await state.set_state(OnboardingStates.waiting_for_gender)
    await message.answer(
        texts.QUESTIONNAIRE_OPTIONAL_GENDER_PROMPT,
        reply_markup=gender_keyboard(skip_callback="qnr_skip:gender"),
    )


async def _birth_date(message: Message, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await message.answer(
        texts.QUESTIONNAIRE_OPTIONAL_BIRTH_DATE_PROMPT,
        reply_markup=questionnaire_birth_date_keyboard(),
    )


async def _timezone(message: Message, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_timezone)
    await message.answer(
        texts.QUESTIONNAIRE_TIMEZONE_CHOICE_PROMPT,
        reply_markup=timezone_choice_keyboard("qnr_timezone", back_callback="qnr_back:birth_date"),
    )


@router.message(StateFilter(OnboardingStates.waiting_for_weight, OnboardingStates.waiting_for_height))
async def resume_obsolete_questionnaire(message: Message, state: FSMContext) -> None:
    await _gender(message, state)


@router.callback_query(OnboardingStates.waiting_for_gender, F.data.in_({"gender:male", "gender:female", "qnr_skip:gender"}))
async def handle_gender(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    data.pop("gender", None)
    if callback.data != "qnr_skip:gender":
        data["gender"] = Gender(callback.data.removeprefix("gender:")).value
    await state.set_data(data)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _birth_date(callback.message, state)
    await callback.answer()


@router.message(OnboardingStates.waiting_for_birth_date)
async def handle_birth_date(message: Message, state: FSMContext) -> None:
    try:
        value = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").replace(tzinfo=UTC).date()
    except ValueError:
        await message.answer(texts.QUESTIONNAIRE_BIRTH_DATE_INVALID)
        return
    if value > datetime.now(UTC).date():
        await message.answer(texts.QUESTIONNAIRE_BIRTH_DATE_FUTURE)
        return
    await state.update_data(birth_date=value.isoformat())
    await _timezone(message, state)


@router.callback_query(OnboardingStates.waiting_for_birth_date, F.data == "qnr_skip:birth_date")
async def skip_birth_date(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    data.pop("birth_date", None)
    await state.set_data(data)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _timezone(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.in_({"qnr_back:weight", "qnr_back:height", "qnr_back:gender"}))
async def back_to_gender(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await _gender(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "qnr_back:birth_date")
async def back_to_birth_date(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await _birth_date(callback.message, state)
    await callback.answer()


@router.message(OnboardingStates.waiting_for_timezone)
async def handle_timezone_text(message: Message, state: FSMContext) -> None:
    # No free-text city or silent fallback. Old clients/FSM receive the choices too.
    await _timezone(message, state)


@router.callback_query(OnboardingStates.waiting_for_timezone, F.data.startswith("qnr_timezone:"))
async def handle_timezone(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    timezone_name = callback.data.removeprefix("qnr_timezone:")
    if timezone_name not in TIMEZONE_DISPLAY_LABELS:
        await callback.answer("Выбери часовой пояс из списка.", show_alert=True)
        return
    data = await state.get_data()
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    now = datetime.now(UTC)
    user = await OnboardingService(session).complete_questionnaire_and_start_trial(
        user_id=user.id,
        gender=Gender(data["gender"]) if data.get("gender") else None,
        birth_date=date.fromisoformat(data["birth_date"]) if data.get("birth_date") else None,
        timezone=timezone_name,
        now=now,
    )
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    trial_granted_now = (
        user.subscription_status == SubscriptionStatus.TRIAL
        and user.subscription_expires_at == now + timedelta(days=TRIAL_DAYS)
    )
    await callback.message.answer(
        texts.TRIAL_STARTED.format(trial_days=TRIAL_DAYS) if trial_granted_now else texts.ONBOARDING_ACCESS_KEPT,
    )
    await callback.message.answer(
        texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard(is_admin=settings.is_admin(callback.from_user.id)),
    )
    await callback.answer()
