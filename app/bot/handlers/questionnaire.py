from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import back_cancel_keyboard, bottom_menu_keyboard, gender_keyboard
from app.bot.states import OnboardingStates
from app.bot.timezones import resolve_city_timezone
from app.config import settings
from app.db.models import Gender
from app.db.repositories.users import UserRepository
from app.domain.constants import TRIAL_DAYS
from app.services.onboarding import OnboardingService

router = Router()


def _parse_positive_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _parse_positive_int(raw: str | None) -> int | None:
    if raw is None or not raw.strip().isdigit():
        return None
    value = int(raw.strip())
    return value if value > 0 else None


@router.message(OnboardingStates.waiting_for_weight)
async def handle_weight(message: Message, state: FSMContext) -> None:
    value = _parse_positive_decimal(message.text)
    if value is None:
        await message.answer(texts.QUESTIONNAIRE_WEIGHT_INVALID)
        return

    await state.update_data(weight_kg=str(value))
    await state.set_state(OnboardingStates.waiting_for_height)
    await message.answer(texts.QUESTIONNAIRE_HEIGHT_PROMPT, reply_markup=back_cancel_keyboard("qnr_back:weight"))


@router.message(OnboardingStates.waiting_for_height)
async def handle_height(message: Message, state: FSMContext) -> None:
    value = _parse_positive_int(message.text)
    if value is None:
        await message.answer(texts.QUESTIONNAIRE_HEIGHT_INVALID)
        return

    await state.update_data(height_cm=value)
    await state.set_state(OnboardingStates.waiting_for_gender)
    await message.answer(texts.QUESTIONNAIRE_GENDER_PROMPT, reply_markup=gender_keyboard("qnr_back:height"))


@router.callback_query(OnboardingStates.waiting_for_gender, F.data.startswith("gender:"))
async def handle_gender(callback: CallbackQuery, state: FSMContext) -> None:
    gender = Gender(callback.data.removeprefix("gender:"))
    await state.update_data(gender=gender.value)
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        texts.QUESTIONNAIRE_BIRTH_DATE_PROMPT, reply_markup=back_cancel_keyboard("qnr_back:gender"),
    )
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
    await state.set_state(OnboardingStates.waiting_for_timezone)
    await message.answer(texts.QUESTIONNAIRE_TIMEZONE_PROMPT, reply_markup=back_cancel_keyboard("qnr_back:birth_date"))


@router.callback_query(F.data == "qnr_back:weight")
async def handle_back_to_weight(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_weight)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.QUESTIONNAIRE_WEIGHT_PROMPT)
    await callback.answer()


@router.callback_query(F.data == "qnr_back:height")
async def handle_back_to_height(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_height)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.QUESTIONNAIRE_HEIGHT_PROMPT, reply_markup=back_cancel_keyboard("qnr_back:weight"))
    await callback.answer()


@router.callback_query(F.data == "qnr_back:gender")
async def handle_back_to_gender(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_gender)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.QUESTIONNAIRE_GENDER_PROMPT, reply_markup=gender_keyboard("qnr_back:height"))
    await callback.answer()


@router.callback_query(F.data == "qnr_back:birth_date")
async def handle_back_to_birth_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        texts.QUESTIONNAIRE_BIRTH_DATE_PROMPT, reply_markup=back_cancel_keyboard("qnr_back:gender"),
    )
    await callback.answer()


@router.message(OnboardingStates.waiting_for_timezone)
async def handle_timezone(message: Message, state: FSMContext, session: AsyncSession) -> None:
    city = (message.text or "").strip()
    if not city:
        return
    timezone_name = resolve_city_timezone(city)
    data = await state.get_data()

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    onboarding = OnboardingService(session)
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id,
        weight_kg=Decimal(data["weight_kg"]),
        height_cm=data["height_cm"],
        gender=Gender(data["gender"]),
        birth_date=date.fromisoformat(data["birth_date"]),
        timezone=timezone_name,
        now=datetime.now(UTC),
    )

    await state.clear()
    await message.answer(texts.TRIAL_STARTED.format(trial_days=TRIAL_DAYS))
    await message.answer(
        texts.WHAT_NEXT, reply_markup=bottom_menu_keyboard(is_admin=settings.is_admin(message.from_user.id)),
    )
