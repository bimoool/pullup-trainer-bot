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
from app.services.subscription import SubscriptionService
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
        if isinstance(m, SendMessage) and m.text and "план на первую тренировку" in m.text
    ]
    assert len(plan_messages) == 1
    assert "объём: 15 повторений" in plan_messages[0]  # ceil(20*0.75)=15


async def test_current_plan_before_first_workout_says_first_workout_not_current(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Пакет #5 — "Текущий план (пока без тренировки)" сбивало с толку.
    Для состояния "ни одной тренировки ещё не было" заголовок должен явно
    говорить про ПЕРВУЮ тренировку, не "текущий" (снаряд/цель здесь ещё не
    закреплены прошлой тренировкой)."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="show_plan"), session=session,
    )

    plan_messages = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    [plan] = [t for t in plan_messages if "повторений, снаряд" in t]
    assert plan.startswith("Твой план на первую тренировку:")
    assert "Текущий план:" not in plan


async def test_current_plan_before_first_workout_recommends_same_equipment_as_live_start(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Баг из фокус-группы (пакет #5): "Текущий план" до первой тренировки
    показывал плейсхолдер "резина" для блока на силу вместо реальной
    рекомендации по замеру — рассинхрон с тем, что реально предлагал живой
    старт тренировки при том же замере. Явно сравниваем оба пути для
    одного и того же замера (10 — порог для отягощения в блоке на силу)."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="show_plan"), session=session,
    )
    plan_messages = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    [plan] = [t for t in plan_messages if "повторений, снаряд" in t]
    strength_line = next(line for line in plan.splitlines() if line.startswith("Блок на силу"))
    # При замере 10 объёмный блок легитимно рекомендует резину (10 не > 10)
    # — баг был именно про силовой блок, порог которого другой (>= 8).
    assert "снаряд — отягощение" in strength_line

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )
    live_messages = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    [live_announcement] = [t for t in live_messages if t.startswith("Исходя из замера")]
    assert "будем делать с отягощением" in live_announcement
