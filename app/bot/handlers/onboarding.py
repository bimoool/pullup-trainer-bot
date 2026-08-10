from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.states import OnboardingStates
from app.db.repositories.users import UserRepository
from app.services.onboarding import OnboardingService

router = Router()

MAX_REASONABLE_REPS = 100


@router.callback_query(OnboardingStates.waiting_for_baseline_reps, F.data == "start_baseline_measurement")
async def handle_start_baseline_measurement(callback: CallbackQuery) -> None:
    """Явный тап по "Начать замер →" — состояние уже выставлено на
    waiting_for_baseline_reps сразу при показе трёх онбординговых
    сообщений (см. start.py), так что прямой ввод числа тоже сработает;
    кнопка нужна как понятный призыв к действию, а не техническая
    необходимость. Убираем клавиатуру, чтобы не тапали дважды."""
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(texts.BASELINE_START_TOAST)


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
