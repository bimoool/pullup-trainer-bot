"""Таймер обратного отсчёта в TOO_EARLY (Часть 10, пакет #2, п.23) — раньше
экран "рано тренироваться" не говорил, сколько именно ждать; теперь считает
часы + дату/время следующей доступной тренировки. Реальным aiogram-роутингом."""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import MIN_REST_DAYS, EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from tests.test_bot.conftest import make_callback_update as _callback_update


async def test_too_early_shows_hours_left_and_ready_datetime(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    performed_at = datetime.now(UTC) - timedelta(hours=10)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )

    before = datetime.now(UTC)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )
    after = datetime.now(UTC)

    ready_at_dt = performed_at + timedelta(days=MIN_REST_DAYS)
    # Час считается от момента, когда хендлер реально снял now() — где-то
    # между before и after, поэтому допускаем разброс в 1 час на округление.
    hours_left_min = max(0, math.ceil((ready_at_dt - after).total_seconds() / 3600))
    hours_left_max = max(0, math.ceil((ready_at_dt - before).total_seconds() / 3600))

    # Пакет #6 — раз недельный лимит факультатива (2, issue #94) ещё не
    # исчерпан, к сообщению добавляется предложение факультатива.
    expected = texts.TOO_EARLY_FOR_WORKOUT.format(
        hours_left=hours_left_min,
        ready_date=ready_at_dt.strftime("%d.%m"),
        ready_time=ready_at_dt.strftime("%H:%M"),
    ) + texts.TOO_EARLY_ELECTIVE_OFFER
    expected_alt = texts.TOO_EARLY_FOR_WORKOUT.format(
        hours_left=hours_left_max,
        ready_date=ready_at_dt.strftime("%d.%m"),
        ready_time=ready_at_dt.strftime("%H:%M"),
    ) + texts.TOO_EARLY_ELECTIVE_OFFER

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    [too_early] = [t for t in sent_texts if t.startswith(texts.TOO_EARLY_FOR_WORKOUT.split("{")[0])]
    assert too_early in (expected, expected_alt)
    assert ready_at_dt.strftime("%d.%m") in too_early
    assert ready_at_dt.strftime("%H:%M") in too_early
