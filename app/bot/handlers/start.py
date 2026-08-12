from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import baseline_start_keyboard, bottom_menu_keyboard
from app.bot.states import OnboardingStates
from app.db.models import User
from app.db.repositories.users import UserRepository

# ВАЖНО: этот router подключается ПЕРВЫМ в app/bot/handlers/__init__.py —
# /start и /cancel обязаны перехватывать апдейт раньше любых хендлеров,
# завязанных на FSM-состояние (иначе, например, "/start" посреди ввода
# результата тренировки уйдёт в parse_block_result и вернёт ошибку разбора
# вместо перезапуска — реальный баг, который эта очерёдность и чинит).
router = Router()


async def _go_home(message: Message, state: FSMContext, user: User, *, cancelled: bool = False) -> None:
    """Общий "выход в начало" — используется и /start, и /cancel, и кнопкой
    отмены: если анкета не завершена, возвращает туда, где пользователь
    остановился в онбординге (а не в несуществующее для него главное меню),
    иначе — в главное меню.

    cancelled=True (Часть 10, пакет #2, п.18) — CANCELLED и WELCOME_BACK
    оба заканчивались на "Что делаем?", и /cancel/кнопка отмены слали ОБА
    подряд одним и тем же смыслом. Один текст вместо двух — "Отменено" для
    явной отмены, "С возвращением" для /start."""
    await state.clear()
    if user.onboarding_completed_at is None:
        await state.set_state(OnboardingStates.waiting_for_baseline_reps)
        await message.answer(texts.ONBOARDING_INTRO)
        await message.answer(texts.ONBOARDING_WHAT_NEXT)
        await message.answer(texts.BASELINE_GUIDE, reply_markup=baseline_start_keyboard())
        return
    text = texts.CANCELLED if cancelled else texts.WELCOME_BACK
    await message.answer(text, reply_markup=bottom_menu_keyboard())


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    if user is None:
        user = await users.create(telegram_id=message.from_user.id, username=message.from_user.username)
    await _go_home(message, state, user)


@router.message(Command("cancel"))
async def handle_cancel_command(message: Message, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)
    if user is None:
        await state.clear()
        await message.answer(texts.CANCELLED)
        return
    await _go_home(message, state, user, cancelled=True)


@router.callback_query(F.data == "cancel_flow")
async def handle_cancel_callback(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)
    if user is not None:
        await _go_home(callback.message, state, user, cancelled=True)
    else:
        await state.clear()
        await callback.message.answer(texts.CANCELLED)
    await callback.answer()


@router.message(Command("help"))
async def handle_help_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.HELP_TEXT)
