""""Посмотреть план" (show_plan) — Часть 10, пакет #2, п.9: снаряд теперь
виден сразу, не скрыт до "Начать тренировку". Реальным aiogram-роутингом."""

from datetime import UTC, datetime
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from tests.test_bot.conftest import make_callback_update as _callback_update


async def test_current_plan_shows_equipment_immediately(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal(48),
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="show_plan"), session=session,
    )

    plan_messages = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and "Текущий план" in m.text
    ]
    assert len(plan_messages) == 1
    assert "снаряд — собственный вес" in plan_messages[0]
    assert "снаряд — отягощение +48 кг" in plan_messages[0]
    # больше не "уточню на самой тренировке" — снаряд виден сразу
    assert "уточню" not in plan_messages[0]


async def test_current_plan_before_first_workout_uses_initial_volume_target(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Часть 10, пакет #2, п.14 — "Текущий план" для ещё ни разу не
    тренировавшегося пользователя должен показывать ту же скорректированную
    цель ("замер минус 25%"), что реально применится при старте, а не флэт
    VOLUME_BLOCK.base_target."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=20)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="show_plan"), session=session,
    )

    plan_messages = [
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and "Текущий план" in m.text
    ]
    assert len(plan_messages) == 1
    assert "объём: 15 повторений" in plan_messages[0]  # ceil(20*0.75)=15
