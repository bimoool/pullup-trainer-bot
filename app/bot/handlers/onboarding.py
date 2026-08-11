from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import baseline_confirm_keyboard
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
    необходимость. Убираем клавиатуру, чтобы не тапали дважды.

    Раньше здесь был только callback.answer() (всплывающий тост) — легко
    пропустить, человек видел, что кнопка пропала, и тишину дальше (баг из
    живого тестирования). Теперь отправляем настоящее сообщение в чат."""
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.BASELINE_START_PROMPT)
    await callback.answer()


@router.message(OnboardingStates.waiting_for_baseline_reps)
async def handle_baseline_reps(message: Message, state: FSMContext) -> None:
    """Число пока НЕ пишется в БД — только подтверждение ниже (см.
    handle_baseline_confirm) действительно его сохраняет. Живое
    тестирование показало, что опечатку в замере раньше нечем было
    поймать до самого конца анкеты."""
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) > MAX_REASONABLE_REPS:
        await message.answer(texts.BASELINE_INVALID)
        return
    reps = int(text)

    await state.update_data(pending_baseline_reps=reps)
    await state.set_state(OnboardingStates.waiting_for_baseline_confirm)
    await message.answer(texts.BASELINE_CONFIRM_PROMPT.format(reps=reps), reply_markup=baseline_confirm_keyboard())


@router.callback_query(OnboardingStates.waiting_for_baseline_confirm, F.data == "baseline_reenter")
async def handle_baseline_reenter(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_baseline_reps)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.BASELINE_START_PROMPT)
    await callback.answer()


@router.callback_query(OnboardingStates.waiting_for_baseline_confirm, F.data == "baseline_confirm")
async def handle_baseline_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    reps = data["pending_baseline_reps"]

    users = UserRepository(session)
    user = await users.get_by_telegram_id(callback.from_user.id)

    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=datetime.now(UTC), reps=reps)

    await callback.message.edit_reply_markup(reply_markup=None)

    if reps == 0:
        await callback.message.answer(texts.BASELINE_ZERO_NOTICE)

    # Мотивационное сообщение — обязательное (Часть 10), не только для
    # результата 0: видеокружок-плейсхолдер здесь, не в BASELINE_GUIDE
    # (тот — про то, как делать замер, этот — после результата).
    await callback.message.answer(texts.MOTIVATION_AFTER_BASELINE)

    await state.set_state(OnboardingStates.waiting_for_weight)
    await callback.message.answer(texts.WELCOME_AFTER_BASELINE.format(reps=reps))
    await callback.message.answer(texts.QUESTIONNAIRE_WEIGHT_PROMPT)
    await callback.answer()
