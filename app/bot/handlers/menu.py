from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import (
    BOTTOM_MENU_HELP,
    BOTTOM_MENU_PROFILE,
    BOTTOM_MENU_PROGRESS,
    BOTTOM_MENU_WORKOUT,
    progress_section_keyboard,
    workout_section_keyboard,
)
from app.db.models import SubscriptionStatus
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.users import UserRepository
from app.domain.achievements import AchievementCode

# ВАЖНО: подключается в app/bot/handlers/__init__.py сразу после start —
# нажатие на кнопку нижнего меню обязано перехватывать апдейт независимо от
# текущего FSM-состояния, так же как /cancel (см. Часть 3: "выход в меню из
# любого сценария").
router = Router()

_ACHIEVEMENT_LABELS = {
    AchievementCode.FIRST_BASELINE: "🎯 Первый замер",
    AchievementCode.TEN_WORKOUTS_STREAK: "🔥 10 тренировок подряд",
    AchievementCode.EQUIPMENT_CHANGED: "📈 Смена снаряда",
    AchievementCode.FIRST_WEIGHTED_PULLUP: "🏋️ Первое подтягивание с отягощением",
    AchievementCode.SET_COMPLETED: "✅ Сет завершён",
    AchievementCode.MAX_REPS_PLUS_FIVE: "💪 +5 к максимуму",
    AchievementCode.MONTH_NO_GAPS: "📅 Месяц без пропусков",
}

_SUBSCRIPTION_LABELS = {
    SubscriptionStatus.NONE: "нет подписки",
    SubscriptionStatus.TRIAL: "пробный период",
    SubscriptionStatus.ACTIVE: "активна",
    SubscriptionStatus.EXPIRED: "истекла",
}


@router.message(F.text == BOTTOM_MENU_WORKOUT)
async def handle_workout_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.SECTION_WORKOUT_TITLE, reply_markup=workout_section_keyboard())


@router.message(F.text == BOTTOM_MENU_PROGRESS)
async def handle_progress_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.SECTION_PROGRESS_TITLE, reply_markup=progress_section_keyboard())


@router.message(F.text == BOTTOM_MENU_PROFILE)
async def handle_profile_section(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    users = UserRepository(session)
    user = await users.get_by_telegram_id(message.from_user.id)

    achievements = await AchievementRepository(session).list_for_user(user.id)
    if achievements:
        achievement_list = "\n".join(
            f"— {_ACHIEVEMENT_LABELS.get(AchievementCode(a.code), a.code)}" for a in achievements
        )
    else:
        achievement_list = texts.PROFILE_NO_ACHIEVEMENTS

    subscription = _SUBSCRIPTION_LABELS[user.subscription_status]
    if user.subscription_expires_at is not None and user.subscription_status in (
        SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE,
    ):
        subscription += f" до {user.subscription_expires_at.strftime('%d.%m.%Y')}"

    body = texts.PROFILE_BODY.format(
        weight_kg=user.weight_kg if user.weight_kg is not None else texts.PROFILE_NOT_SET,
        height_cm=user.height_cm if user.height_cm is not None else texts.PROFILE_NOT_SET,
        age=user.age if user.age is not None else texts.PROFILE_NOT_SET,
        timezone=user.timezone or texts.PROFILE_NOT_SET,
        coins=user.coins_balance,
        subscription=subscription,
        achievement_count=len(achievements),
        achievement_list=achievement_list,
    )
    await message.answer(f"{texts.PROFILE_HEADER}\n\n{body}")


@router.message(F.text == BOTTOM_MENU_HELP)
async def handle_help_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.HELP_TEXT)
