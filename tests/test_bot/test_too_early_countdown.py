"""Таймер обратного отсчёта в TOO_EARLY (Часть 10, пакет #2, п.23) — раньше
экран "рано тренироваться" не говорил, сколько именно ждать; теперь считает
часы + дату/время следующей доступной тренировки. Реальным aiogram-роутингом."""

import math
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.services.training_analytics import resolve_timezone
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

    # issue #304 (OD-2): «два полных дня отдыха» — следующий старт MAIN с начала дня
    # local_date(последней) + 3 в поясе пользователя (Пн → Чт), а не performed_at + MIN_REST_DAYS.
    tz = resolve_timezone(user.timezone)
    ready_date = performed_at.astimezone(tz).date() + timedelta(days=3)
    ready_at_dt = datetime.combine(ready_date, time(0), tzinfo=tz).astimezone(UTC)
    # Час считается от момента, когда хендлер реально снял now() — где-то
    # между before и after, поэтому допускаем разброс в 1 час на округление.
    hours_left_min = max(0, math.ceil((ready_at_dt - after).total_seconds() / 3600))
    hours_left_max = max(0, math.ceil((ready_at_dt - before).total_seconds() / 3600))

    # Пакет #6 — раз лимит "факультатив не чаще раза в неделю" ещё не
    # исчерпан, к сообщению добавляется предложение факультатива.
    expected = {
        texts.TOO_EARLY_FOR_WORKOUT.format(
            hours_left=hours_left, ready_date=ready_date.strftime("%d.%m"), ready_time="00:00",
        ) + texts.TOO_EARLY_ELECTIVE_OFFER
        for hours_left in (hours_left_min, hours_left_max)
    }

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    [too_early] = [t for t in sent_texts if t.startswith(texts.TOO_EARLY_FOR_WORKOUT.split("{")[0])]
    assert too_early in expected
    assert ready_date.strftime("%d.%m") in too_early
