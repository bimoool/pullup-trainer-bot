"""Обязательная разминка (Часть 10, пакет #2, п.25) — полное описание
только на первой тренировке; на всех следующих — короткое напоминание с
кнопкой «Показать разминку». Реальным aiogram-роутингом."""

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from tests.test_bot.conftest import make_callback_update as _callback_update


def _message_update(*, telegram_id: int, text: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=text,
        ),
    )


async def _make_user_ready(session, user: User) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]


async def test_first_ever_workout_gets_full_warmup_description(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_user_ready(session, user)
    # reps=15 -> объёмный блок авто-подбирает bodyweight (без доп. шагов),
    # силовой — weight (запрашивает вес текстом); оба блока проходят по
    # первой-тренировке очереди снаряда без ручного выбора типа.
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=15)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="20"), session=session)

    sent = _sent_texts(bot)
    assert texts.WARMUP_FULL in sent
    assert texts.WARMUP_REMINDER not in sent


async def test_second_workout_gets_short_reminder_not_full_text(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_user_ready(session, user)
    performed_at = datetime.now(UTC) - timedelta(days=3)  # за пределами MIN_REST_DAYS
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent = _sent_texts(bot)
    assert texts.WARMUP_REMINDER in sent
    assert texts.WARMUP_FULL not in sent


async def test_tapping_show_warmup_button_sends_full_description(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="warmup:show"), session=session,
    )

    assert texts.WARMUP_FULL in _sent_texts(bot)
