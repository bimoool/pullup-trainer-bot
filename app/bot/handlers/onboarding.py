from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.states import OnboardingStates
from app.db.models import Branch
from app.db.repositories.users import UserRepository
from app.services.onboarding import OnboardingService

router = Router()

MAX_REASONABLE_REPS = 100


@router.message(OnboardingStates.waiting_for_baseline_reps)
async def handle_baseline_reps(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) > MAX_REASONABLE_REPS:
        await message.answer(texts.BASELINE_INVALID)
        return

    await state.update_data(baseline_reps=int(text))
    await state.set_state(OnboardingStates.waiting_for_band_thickness)
    await message.answer(texts.BAND_THICKNESS_PROMPT)


@router.message(OnboardingStates.waiting_for_band_thickness)
async def handle_band_thickness(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        band_thickness_mm = Decimal((message.text or "").strip().replace(",", "."))
    except InvalidOperation:
        await message.answer(texts.BAND_THICKNESS_INVALID)
        return

    data = await state.get_data()
    reps = data["baseline_reps"]

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    onboarding = OnboardingService(session)
    _baseline, _workout_set, updated_user = await onboarding.record_baseline_and_start(
        user_id=user.id, performed_at=datetime.now(UTC), reps=reps, band_thickness_mm=band_thickness_mm,
    )

    await state.set_state(OnboardingStates.waiting_for_weight)
    welcome = texts.WELCOME_BAND if updated_user.branch == Branch.BAND else texts.WELCOME_ASSISTED
    await message.answer(welcome.format(reps=reps))
    await message.answer(texts.QUESTIONNAIRE_WEIGHT_PROMPT)
