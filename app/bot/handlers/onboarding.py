from datetime import UTC, datetime

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.states import OnboardingStates
from app.db.repositories.users import UserRepository
from app.services.onboarding import OnboardingService

router = Router()

MAX_REASONABLE_REPS = 100


@router.message(OnboardingStates.waiting_for_baseline_reps)
async def handle_baseline_reps(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) > MAX_REASONABLE_REPS:
        await message.answer(texts.BASELINE_INVALID)
        return
    reps = int(text)

    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=datetime.now(UTC), reps=reps)

    await state.set_state(OnboardingStates.waiting_for_weight)
    await message.answer(texts.WELCOME_AFTER_BASELINE.format(reps=reps))
    await message.answer(texts.QUESTIONNAIRE_WEIGHT_PROMPT)
