from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import main_menu_keyboard, timezone_keyboard
from app.bot.states import OnboardingStates
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
        await message.answer(texts.QUESTIONNAIRE_INVALID_NUMBER)
        return

    await state.update_data(weight_kg=str(value))
    await state.set_state(OnboardingStates.waiting_for_height)
    await message.answer(texts.QUESTIONNAIRE_HEIGHT_PROMPT)


@router.message(OnboardingStates.waiting_for_height)
async def handle_height(message: Message, state: FSMContext) -> None:
    value = _parse_positive_int(message.text)
    if value is None:
        await message.answer(texts.QUESTIONNAIRE_INVALID_NUMBER)
        return

    await state.update_data(height_cm=value)
    await state.set_state(OnboardingStates.waiting_for_age)
    await message.answer(texts.QUESTIONNAIRE_AGE_PROMPT)


@router.message(OnboardingStates.waiting_for_age)
async def handle_age(message: Message, state: FSMContext) -> None:
    value = _parse_positive_int(message.text)
    if value is None:
        await message.answer(texts.QUESTIONNAIRE_INVALID_NUMBER)
        return

    await state.update_data(age=value)
    await state.set_state(OnboardingStates.waiting_for_timezone)
    await message.answer(texts.QUESTIONNAIRE_TIMEZONE_PROMPT, reply_markup=timezone_keyboard())


@router.callback_query(OnboardingStates.waiting_for_timezone, F.data.startswith("tz:"))
async def handle_timezone(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    timezone_name = callback.data.removeprefix("tz:")
    data = await state.get_data()

    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    onboarding = OnboardingService(session)
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id,
        weight_kg=Decimal(data["weight_kg"]),
        height_cm=data["height_cm"],
        age=data["age"],
        timezone=timezone_name,
        now=datetime.now(UTC),
    )

    await state.clear()
    await callback.message.edit_text(texts.TRIAL_STARTED.format(trial_days=TRIAL_DAYS))
    await callback.message.answer("Что делаем?", reply_markup=main_menu_keyboard())
    await callback.answer()
