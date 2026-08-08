from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import main_menu_keyboard
from app.bot.states import OnboardingStates
from app.db.repositories.users import UserRepository

router = Router()

WELCOME_BACK = "С возвращением! Что делаем?"


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    if user is None:
        user = await users.create(telegram_id=message.from_user.id, username=message.from_user.username)

    if user.onboarding_completed_at is None:
        await state.clear()
        await state.set_state(OnboardingStates.waiting_for_baseline_reps)
        await message.answer(texts.ONBOARDING_INTRO)
        await message.answer(texts.BAND_SELECTION_GUIDE)
        return

    await state.clear()
    await message.answer(WELCOME_BACK, reply_markup=main_menu_keyboard())
