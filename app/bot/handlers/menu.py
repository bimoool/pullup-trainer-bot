from datetime import UTC, datetime
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import calculate_age, format_subscription_status
from app.bot.keyboards import (
    BOTTOM_MENU_HELP,
    BOTTOM_MENU_PROFILE,
    BOTTOM_MENU_PROGRESS,
    BOTTOM_MENU_WORKOUT,
    help_keyboard,
    profile_keyboard,
    progress_section_keyboard,
    workout_section_keyboard,
)
from app.bot.timezones import format_timezone_label
from app.config import settings
from app.db.models import Gender
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.users import UserRepository
from app.domain.achievements import ACHIEVEMENT_LABELS, AchievementCode

# ВАЖНО: подключается в app/bot/handlers/__init__.py сразу после start —
# нажатие на кнопку нижнего меню обязано перехватывать апдейт независимо от
# текущего FSM-состояния, так же как /cancel (см. Часть 3: "выход в меню из
# любого сценария").
router = Router()

# Часть app/assets (см. Dockerfile: COPY app ./app) — деплоится вместе с
# остальным кодом, не раскладывается на сервере вручную. parents[2] от
# этого файла (app/bot/handlers/menu.py) — корень пакета app/.
OFERTA_PDF_PATH = Path(__file__).resolve().parents[2] / "assets" / "oferta.pdf"

_GENDER_LABELS = {
    Gender.MALE: texts.PROFILE_GENDER_MALE,
    Gender.FEMALE: texts.PROFILE_GENDER_FEMALE,
}


@router.message(F.text == BOTTOM_MENU_WORKOUT)
async def handle_workout_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.SECTION_WORKOUT_TITLE, reply_markup=workout_section_keyboard())


@router.message(F.text == BOTTOM_MENU_PROGRESS)
async def handle_progress_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.SECTION_PROGRESS_TITLE, reply_markup=progress_section_keyboard())


async def render_profile(message: Message, session: AsyncSession, telegram_id: int) -> None:
    """Вынесено из handle_profile_section — переиспользуется хендлером
    "← Назад" в редактировании профиля (см. profile_edit.py), чтобы после
    правки поля просто перерисовать актуальный профиль, а не дублировать
    сборку текста.

    telegram_id — явный параметр, а не message.from_user.id: у части
    вызовов message — это callback.message (см. profile_edit.py), а там
    from_user — бот, не пользователь (тот же класс бага, что и с кнопкой
    "Пропустить" у комментария, см. workout.py::_finalize_workout)."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(telegram_id)

    achievements = await AchievementRepository(session).list_for_user(user.id)
    if achievements:
        # Без тире перед эмодзи (Часть 10) — сами эмодзи уже достаточно
        # разделяют пункты списка, тире было лишним.
        achievement_list = "\n".join(
            ACHIEVEMENT_LABELS.get(AchievementCode(a.code), a.code) for a in achievements
        )
    else:
        achievement_list = texts.PROFILE_NO_ACHIEVEMENTS

    age = calculate_age(user.birth_date, datetime.now(UTC).date()) if user.birth_date is not None else None

    body = texts.PROFILE_BODY.format(
        subscription=format_subscription_status(user),
        weight_kg=user.weight_kg if user.weight_kg is not None else texts.PROFILE_NOT_SET,
        height_cm=user.height_cm if user.height_cm is not None else texts.PROFILE_NOT_SET,
        gender=_GENDER_LABELS[user.gender] if user.gender is not None else texts.PROFILE_NOT_SET,
        age=age if age is not None else texts.PROFILE_NOT_SET,
        timezone=format_timezone_label(user.timezone) if user.timezone else texts.PROFILE_NOT_SET,
        coins=user.coins_balance,
        achievement_count=len(achievements),
        achievement_list=achievement_list,
    )
    is_admin = settings.is_admin(telegram_id)
    await message.answer(f"{texts.PROFILE_HEADER}\n\n{body}", reply_markup=profile_keyboard(is_admin=is_admin))


@router.message(F.text == BOTTOM_MENU_PROFILE)
async def handle_profile_section(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await render_profile(message, session, message.from_user.id)


@router.message(F.text == BOTTOM_MENU_HELP)
async def handle_help_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.HELP_TEXT, reply_markup=help_keyboard())


@router.callback_query(F.data == "help_detailed")
async def handle_help_detailed(callback: CallbackQuery) -> None:
    await callback.message.answer(texts.HELP_DETAILED_TEXT)
    await callback.answer()


@router.callback_query(F.data == "pricing_info")
async def handle_pricing_info(callback: CallbackQuery) -> None:
    """Требование модерации Робокассы — тарифы/реквизиты/оферта доступны
    изнутри бота, не только на внешнем канале. Полный текст оферты — файлом
    (не ссылкой на канал), сразу следующим сообщением после текста, в этом
    же действии по кнопке."""
    await callback.message.answer(texts.PRICING_TEXT)
    await callback.message.answer_document(FSInputFile(OFERTA_PDF_PATH))
    await callback.answer()
