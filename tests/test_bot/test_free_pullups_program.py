"""Правило 2026-10-07: legacy-каскад бота («💪 Начать тренировку») — это программа «Подтягивания», бесплатна
навсегда: истёкший пользователь не получает пейволл, а проходит тот же сценарий, что и с подпиской."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher

from app.bot import texts
from app.bot.states import WorkoutStates
from app.db.models import SubscriptionStatus, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from tests.test_bot.conftest import make_callback_update


async def test_expired_user_starts_the_free_pullups_workout_without_paywall(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    now = datetime.now(UTC)
    await UserRepository(session).complete_onboarding(user.id, now - timedelta(days=30))
    await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.EXPIRED, expires_at=now - timedelta(days=1),
    )
    performed_at = now - timedelta(days=3)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(None)

    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a.state
    sent = " ".join(str(getattr(m, "text", "")) for m in bot.session.sent_methods)
    assert "Пробный период закончился" not in sent and "Пробный период закончился" in texts.TRIAL_ENDED
