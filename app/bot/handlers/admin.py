import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.formatting import format_subscription_status
from app.bot.handlers.subscription import _robokassa_available
from app.bot.keyboards import (
    BOTTOM_MENU_ADMIN,
    admin_dm_prompt_keyboard,
    admin_menu_keyboard,
    admin_reset_confirm_keyboard,
    admin_user_card_keyboard,
    admin_user_list_keyboard,
    cancel_keyboard,
    payment_link_keyboard,
    profile_keyboard,
)
from app.bot.middlewares import MediaGroupMiddleware
from app.bot.states import AdminStates
from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.db.repositories.weekly_digests import WeeklyDigestRepository
from app.domain.constants import ADMIN_TEST_PAYMENT_AMOUNT_RUB, WEEKLY_DIGEST_REPLY_DEADLINE_HOURS
from app.services.admin import FUNNEL_STEPS, AdminService, UserCard
from app.services.admin_reset import reset_user_progress
from app.services.gamification import GamificationService
from app.services.robokassa import RobokassaClient, RobokassaService
from app.services.subscription import SubscriptionService
from app.workers.weekly_digest import send_weekly_digest_reminder

logger = logging.getLogger(__name__)

router = Router()
# Только альбомы (media_group_id), долетевшие до этого роутера — рассылка
# всем (handle_admin_broadcast_text), еженедельный дайджест
# (handle_weekly_digest_reply) и личное сообщение из карточки пользователя
# (handle_admin_dm_text) читают несколько фото через data["album"] (issue
# #72), остальные хендлеры не завязаны на photo и не замечают буферизацию.
router.message.outer_middleware(MediaGroupMiddleware())


def _is_admin(telegram_id: int) -> bool:
    return settings.is_admin(telegram_id)


def _user_label(user: User) -> str:
    return f"@{user.username}" if user.username else f"id {user.telegram_id}"


@router.message(Command("admin"))
@router.message(F.text == BOTTOM_MENU_ADMIN)
async def handle_admin_command(message: Message, state: FSMContext) -> None:
    """Тот же обработчик и для команды /admin, и для кнопки "🛠 Админка" в
    постоянном нижнем меню (видна только админам, см. bottom_menu_keyboard)
    — кнопка не более чем ярлык для той же команды, не отдельный сценарий."""
    if not _is_admin(message.from_user.id):
        await message.answer(texts.ADMIN_ACCESS_DENIED)
        return
    await state.clear()
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


@router.callback_query(F.data == "admin_menu")
async def handle_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await state.clear()
    await callback.message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))
    await callback.answer()


@router.callback_query(F.data == "admin_funnel")
async def handle_admin_funnel(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    funnel = await AdminService(session).compute_funnel()
    text = texts.ADMIN_FUNNEL_HEADER
    for step in FUNNEL_STEPS:
        users = funnel.steps[step]
        if not users:
            text += texts.ADMIN_FUNNEL_STEP_EMPTY.format(step=step)
            continue
        lines = "\n".join(
            texts.ADMIN_FUNNEL_USER_LINE.format(username=u.username or "—", telegram_id=u.telegram_id) for u in users
        )
        text += texts.ADMIN_FUNNEL_STEP.format(step=step, count=len(users), users=lines)

    await callback.message.answer(text, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))
    await callback.answer()


@router.callback_query(F.data == "admin_users")
async def handle_admin_users(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    users = await UserRepository(session).list_all()
    await callback.message.answer(texts.ADMIN_USERS_HEADER, reply_markup=admin_user_list_keyboard(users))
    await callback.answer()


def _format_user_card(card: UserCard) -> str:
    user = card.user
    subscription = format_subscription_status(user, show_expired_date=True)
    return texts.ADMIN_USER_CARD.format(
        name=_user_label(user), telegram_id=user.telegram_id,
        baseline_count=card.baseline_count, workout_count=card.workout_count,
        target_a=card.target_a.target, target_b=card.target_b.target,
        subscription=subscription, coins=user.coins_balance,
    )


@router.callback_query(F.data.startswith("admin_user:"))
async def handle_admin_user_card(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_user:"))
    user = await UserRepository(session).get_by_id(user_id)
    card = await AdminService(session).build_user_card(user)

    await callback.message.answer(_format_user_card(card), reply_markup=admin_user_card_keyboard(user_id))
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def handle_admin_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await callback.message.answer(texts.ADMIN_BROADCAST_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


def _broadcast_source_text(message: Message) -> str | None:
    """Источник рассылаемого текста: у обычного текстового сообщения это
    message.text, но у сообщения с картинкой Telegram кладёт подпись в
    message.caption, а message.text остаётся None. Раньше оба
    вызывающих места (_broadcast_to_onboarded_users, WeeklyDigestRepository.
    record) брали message.text напрямую — рассылка с картинкой падала на
    `SendMessage.text=None` (aiogram/pydantic не пускает None в text),
    прод-инцидент issue #69."""
    return message.text or message.caption


def _album_photo_file_ids(album: list[Message]) -> list[str]:
    return [m.photo[-1].file_id for m in album if m.photo]


def _album_caption(album: list[Message]) -> str | None:
    """Telegram кладёт подпись альбома только в ОДНО из его сообщений (не
    обязательно первое по порядку получения) — ищем её по всем частям, а не
    только у той, что дошла до буфера первой (см. MediaGroupMiddleware)."""
    return next((m.caption for m in album if m.caption), None)


async def _broadcast(bot: Bot, message: Message, users: list[User], album: list[Message] | None = None) -> tuple[int, int]:
    """Общий механизм рассылки — используется и ручной "📢 Рассылка всем"
    (handle_admin_broadcast_text, только завершившие онбординг), и
    еженедельным дайджестом (handle_weekly_digest_reply, весь список
    пользователей — issue #84). Список адресатов выбирает вызывающий
    (_broadcast_to_onboarded_users/_broadcast_to_all_users), эта функция
    только знает, КАК отправить, не КОМУ. parse_mode=None: текст набирает
    человек (админ), не наш HTML-шаблон — случайные "<"/"&" не должны
    ронять рассылку ошибкой парсинга сущностей.

    Сообщение с картинкой (message.photo) пересылается через send_photo с
    той же подписью, не send_message — иначе картинка терялась бы молча,
    а caption ушёл бы как обычный текст без неё.

    Несколько фото в одной рассылке (album, буферизован MediaGroupMiddleware
    по media_group_id, issue #72) — send_media_group с caption на первом
    элементе массива, Telegram показывает её как общую подпись альбома;
    caption на остальных элементах Telegram молча игнорирует, если бы он
    там был — не только на первом фото по отдельности (был бы старый баг:
    альбом уходил как одно фото с подписью, остальные без текста)."""
    photos = _album_photo_file_ids(album) if album else ([message.photo[-1].file_id] if message.photo else [])
    text = _album_caption(album) if album else _broadcast_source_text(message)
    sent = 0
    for user in users:
        try:
            if len(photos) > 1:
                media = [InputMediaPhoto(media=photos[0], caption=text, parse_mode=None)] + [
                    InputMediaPhoto(media=file_id) for file_id in photos[1:]
                ]
                await bot.send_media_group(user.telegram_id, media)
            elif photos:
                await bot.send_photo(user.telegram_id, photos[0], caption=text, parse_mode=None)
            else:
                await bot.send_message(user.telegram_id, text, parse_mode=None)
            sent += 1
        except TelegramAPIError:
            logger.warning("broadcast: failed to notify user %s", user.telegram_id, exc_info=True)
    return sent, len(users)


async def _broadcast_to_onboarded_users(
    bot: Bot, session: AsyncSession, message: Message, album: list[Message] | None = None,
) -> tuple[int, int]:
    """Ручная "📢 Рассылка всем" — только завершившие онбординг. Сознательно
    не расширена на всех пользователей (issue #84) — этот охват не трогать
    без явной отдельной просьбы, в отличие от _broadcast_to_all_users."""
    users = await UserRepository(session).list_onboarded()
    return await _broadcast(bot, message, users, album=album)


async def _broadcast_to_all_users(
    bot: Bot, session: AsyncSession, message: Message, album: list[Message] | None = None,
) -> tuple[int, int]:
    """Еженедельный дайджест — охват шире ручной рассылки: включает и не
    прошедших онбординг (issue #84), цель — вернуть тех, кто начал, но не
    закончил анкету."""
    users = await UserRepository(session).list_all()
    return await _broadcast(bot, message, users, album=album)


@router.message(AdminStates.waiting_for_broadcast_text)
async def handle_admin_broadcast_text(
    message: Message, state: FSMContext, session: AsyncSession, album: list[Message] | None = None,
) -> None:
    sent, total = await _broadcast_to_onboarded_users(message.bot, session, message, album=album)

    await state.clear()
    await message.answer(texts.ADMIN_BROADCAST_DONE.format(sent=sent, total=total))
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


@router.callback_query(F.data == "admin_weekly_digest_now")
async def handle_admin_weekly_digest_now(callback: CallbackQuery, dispatcher: Dispatcher, session: AsyncSession) -> None:
    """"🗞 Разослать дайджест сейчас" (issue #86) — ручной запуск ТОГО ЖЕ
    процесса, что и воскресный крон (app/workers/weekly_digest.py::register),
    без дублирования сбора коммитов/issues или логики рассылки:
    send_weekly_digest_reminder сама шлёт напоминание всем settings.
    admin_id_list и выставляет FSM-состояние waiting_for_weekly_digest_text
    — дальнейший ответ ловит тот же handle_weekly_digest_reply, что и у
    расписания. dispatcher инжектится aiogram'ом автоматически (Dispatcher.
    feed_update кладёт self в data как "dispatcher"), тем же способом, что
    и bot/session — не нужно прокидывать его отдельным параметром роутера."""
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await send_weekly_digest_reminder(callback.bot, dispatcher, session=session)
    await callback.answer(texts.ADMIN_WEEKLY_DIGEST_TRIGGERED_TOAST)


@router.callback_query(F.data.startswith("admin_dm:"))
async def handle_admin_dm_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_dm:"))
    user = await UserRepository(session).get_by_id(user_id)
    await state.update_data(admin_target_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_dm_text)
    await callback.message.answer(
        texts.ADMIN_DM_PROMPT.format(name=_user_label(user)), reply_markup=admin_dm_prompt_keyboard(user_id),
    )
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_dm_text, F.data.startswith("admin_dm_template:"))
async def handle_admin_dm_template(callback: CallbackQuery) -> None:
    """Telegram не даёт боту подставить текст в чужое поле ввода (см.
    admin_dm_prompt_keyboard) — присылаем заготовку отдельным сообщением
    без разметки, чтобы долгим нажатием скопировалась один в один. Ничего
    не отправляет получателю и не меняет состояние — следующий текст от
    админа по-прежнему уходит через handle_admin_dm_text как обычно."""
    await callback.message.answer(texts.ADMIN_DM_INCIDENT_TEMPLATE, parse_mode=None)
    await callback.answer(texts.ADMIN_DM_TEMPLATE_SENT_TOAST, show_alert=True)


@router.message(AdminStates.waiting_for_dm_text)
async def handle_admin_dm_text(
    message: Message, state: FSMContext, session: AsyncSession, album: list[Message] | None = None,
) -> None:
    data = await state.get_data()
    user = await UserRepository(session).get_by_id(data["admin_target_user_id"])

    # Та же буферизация альбома по media_group_id (issue #72), что и у
    # рассылки — без неё несколько фото в личном сообщении ушли бы
    # получателю отдельными сообщениями, не альбомом с общей подписью.
    photos = _album_photo_file_ids(album) if album else ([message.photo[-1].file_id] if message.photo else [])
    caption = _album_caption(album) if album else message.caption

    try:
        if len(photos) > 1:
            media = [InputMediaPhoto(media=photos[0], caption=caption, parse_mode=None)] + [
                InputMediaPhoto(media=file_id) for file_id in photos[1:]
            ]
            await message.bot.send_media_group(user.telegram_id, media)
        elif photos:
            await message.bot.send_photo(user.telegram_id, photos[0], caption=caption, parse_mode=None)
        else:
            await message.bot.send_message(user.telegram_id, message.text, parse_mode=None)
        await message.answer(texts.ADMIN_DM_DONE)
    except TelegramAPIError:
        await message.answer(texts.ADMIN_DM_FAILED)

    await state.clear()
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


@router.callback_query(F.data.startswith("admin_grant_days:"))
async def handle_admin_grant_days_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_grant_days:"))
    user = await UserRepository(session).get_by_id(user_id)
    await state.update_data(admin_target_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_grant_days)
    await callback.message.answer(
        texts.ADMIN_GRANT_DAYS_PROMPT.format(name=_user_label(user)), reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_grant_days)
async def handle_admin_grant_days_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer(texts.ADMIN_GRANT_INVALID_NUMBER)
        return
    if days <= 0:
        await message.answer(texts.ADMIN_GRANT_INVALID_NUMBER)
        return

    data = await state.get_data()
    user = await UserRepository(session).get_by_id(data["admin_target_user_id"])
    updated = await SubscriptionService(session).grant_by_admin(user.id, now=datetime.now(UTC), days=days)

    await state.clear()
    await message.answer(texts.ADMIN_GRANT_DAYS_DONE.format(days=days, name=_user_label(user)))
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))

    # Продление уже записано выше — сбой пуша (юзер заблокировал бота и
    # т.п.) не должен выглядеть как неудачная выдача подписки для админа.
    try:
        await message.bot.send_message(
            user.telegram_id,
            texts.ADMIN_SUBSCRIPTION_EXTENDED_PUSH.format(
                days=days, expires_at=updated.subscription_expires_at.strftime("%d.%m.%Y"),
            ),
        )
    except TelegramAPIError:
        logger.warning("admin grant_days: failed to notify user %s about extension", user.telegram_id, exc_info=True)


@router.callback_query(F.data.startswith("admin_grant_coins:"))
async def handle_admin_grant_coins_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user_id = int(callback.data.removeprefix("admin_grant_coins:"))
    user = await UserRepository(session).get_by_id(user_id)
    await state.update_data(admin_target_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_grant_coins)
    await callback.message.answer(
        texts.ADMIN_GRANT_COINS_PROMPT.format(name=_user_label(user)), reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_grant_coins)
async def handle_admin_grant_coins_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer(texts.ADMIN_GRANT_INVALID_NUMBER)
        return

    data = await state.get_data()
    user = await UserRepository(session).get_by_id(data["admin_target_user_id"])
    await GamificationService(session).grant_coins_by_admin(user.id, amount)

    await state.clear()
    await message.answer(texts.ADMIN_GRANT_COINS_DONE.format(amount=amount, name=_user_label(user)))
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))


# --- Полный сброс СВОЕГО (админа) аккаунта — инструмент для ручного
# тестирования (Часть 9), кнопка в Профиле, а не в списке пользователей:
# в отличие от остальной админки выше, здесь нет admin_target_user_id —
# действие всегда над собственным аккаунтом вызвавшего.


@router.callback_query(F.data == "admin_reset_prompt")
async def handle_admin_reset_prompt(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.message.answer(texts.ADMIN_RESET_WARNING, reply_markup=admin_reset_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_reset_cancel")
async def handle_admin_reset_cancel(callback: CallbackQuery) -> None:
    await callback.answer(texts.CANCELLED)


@router.callback_query(F.data == "admin_reset_confirm")
async def handle_admin_reset_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return

    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    await reset_user_progress(session, user.id)

    await state.clear()
    await callback.message.answer(texts.ADMIN_RESET_DONE, reply_markup=profile_keyboard(is_admin=True))


# --- Диагностический платёж Robokassa на 1₽ (Часть 11) --------------------------
# Та же ссылка на оплату и тот же путь подтверждения (RobokassaService.
# sync_pending_payments — воркер, опрос OpStateExt), что и у обычной
# подписки (см. subscription.py::handle_pay_robokassa), только на 1₽
# вместо SUBSCRIPTION_PRICE_RUB — проверить весь путь вживую (создание
# ссылки → реальная оплата → подтверждение → продление подписки), не
# тратя 990₽ на каждую проверку. Всегда над собственным аккаунтом
# вызвавшего, как и "🧪 Полный сброс" выше — не отдельный целевой
# пользователь.


@router.callback_query(F.data == "admin_test_payment")
async def handle_admin_test_payment(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(texts.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    if not _robokassa_available():
        await callback.answer(texts.ADMIN_TEST_PAYMENT_UNAVAILABLE, show_alert=True)
        return

    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    client = RobokassaClient(
        merchant_login=settings.robokassa_merchant_login,
        password_1=settings.robokassa_password_1,
        password_2=settings.robokassa_password_2,
    )
    robokassa = RobokassaService(session, client)
    link = await robokassa.create_payment_link(
        user.id, amount_rub=ADMIN_TEST_PAYMENT_AMOUNT_RUB, description=texts.ADMIN_TEST_PAYMENT_DESCRIPTION,
    )

    await callback.message.answer(texts.PAYMENT_LINK_SENT, reply_markup=payment_link_keyboard(link))
    await callback.answer()


# --- Еженедельный дайджест новостей продукта (Часть 12) --------------------------
# waiting_for_weekly_digest_text выставляется не отсюда, а программно из
# app/workers/weekly_digest.py в момент отправки напоминания — этот
# хендлер только принимает ОТВЕТ на него. Дедлайн (WEEKLY_DIGEST_REPLY_
# DEADLINE_HOURS) хранится в domain, не в воркере, именно чтобы можно было
# читать его отсюда без обратной зависимости bot -> workers.


@router.message(AdminStates.waiting_for_weekly_digest_text)
async def handle_weekly_digest_reply(
    message: Message, state: FSMContext, session: AsyncSession, album: list[Message] | None = None,
) -> None:
    data = await state.get_data()
    sent_at = datetime.fromisoformat(data["weekly_digest_reminder_sent_at"])
    deadline = sent_at + timedelta(hours=WEEKLY_DIGEST_REPLY_DEADLINE_HOURS)
    now = datetime.now(UTC)

    await state.clear()

    if now > deadline:
        await message.answer(texts.ADMIN_WEEKLY_DIGEST_EXPIRED.format(expires_at=deadline.strftime("%d.%m %H:%M")))
        return

    # _broadcast_to_all_users, не _broadcast_to_onboarded_users — дайджест
    # охватывает и не прошедших онбординг (issue #84), цель — вернуть тех,
    # кто начал, но не закончил анкету. Обычная ручная рассылка (/admin →
    # "📢 Рассылка всем") этот охват не расширяет, см. её докстринг.
    sent, total = await _broadcast_to_all_users(message.bot, session, message, album=album)
    # Только при реальной рассылке — просроченный ответ (ветка above) сюда
    # не доходит, иначе last_digest_sent_at сдвигался бы неделя за неделей
    # без единой настоящей отправки пользователям. text — из того же
    # источника, что и сама рассылка (_broadcast_source_text/_album_caption):
    # у дайджеста с картинкой message.text был бы None, а колонка text NOT NULL.
    text = (_album_caption(album) if album else _broadcast_source_text(message)) or ""
    await WeeklyDigestRepository(session).record(sent_at=now, text=text, recipients_count=sent)
    await message.answer(texts.ADMIN_BROADCAST_DONE.format(sent=sent, total=total))
    await message.answer(texts.ADMIN_MENU_HEADER, reply_markup=admin_menu_keyboard(settings.admin_sheet_url))
