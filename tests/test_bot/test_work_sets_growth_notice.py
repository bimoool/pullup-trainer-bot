"""Объяснение роста work_sets блока на объём ДО начала тренировки (issue
#79) — застой/потолок повторений. Реальным aiogram-роутингом, как
test_volume_deload.py: причину не пересчитывает бот, только форматирует
готовое NextBlockState.work_sets_growth_reason в текст."""

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import VOLUME_BLOCK, EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from tests.test_bot.conftest import make_callback_update as _callback_update


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]


async def _onboard(session, user: User) -> int:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    return workout_set.id


async def test_start_workout_shows_ceiling_notice_before_plan(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    workout_set_id = await _onboard(session, user)
    # Тот же ввод, что и в test_volume_block_ceiling_rolls_back_and_adds_set_
    # instead_of_switching_equipment (репозиторный тест) — первая тренировка
    # сразу перевыполняет потолок 33, work_sets растёт 3->4 по причине CEILING.
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC) - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(32, 32, 32), max_reps=38),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent = _sent_texts(bot)
    assert texts.WORK_SETS_GROWTH_CEILING_NOTICE in sent
    assert texts.WORK_SETS_GROWTH_STALL_NOTICE not in sent


async def test_start_workout_no_growth_notice_for_ordinary_workout(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    workout_set_id = await _onboard(session, user)
    # Обычный рост цели без роста work_sets — банер не должен появляться.
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC) - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent = _sent_texts(bot)
    assert texts.WORK_SETS_GROWTH_CEILING_NOTICE not in sent
    assert texts.WORK_SETS_GROWTH_STALL_NOTICE not in sent


async def test_start_workout_shows_stall_notice_after_four_flat_workouts(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    workout_set_id = await _onboard(session, user)
    repo = WorkoutRepository(session)
    flat_reps = BlockLog(working_reps=(10, 10, 10), max_reps=10)
    strength_reps = BlockLog(working_reps=(3, 3, 3, 3), max_reps=4)

    for days_ago in (20, 15, 10, 5):
        await repo.record_workout(
            user_id=user.id, workout_set_id=workout_set_id,
            performed_at=datetime.now(UTC) - timedelta(days=days_ago),
            block_a_reps=flat_reps, block_b_reps=strength_reps,
            block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
            block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
        )

    history = await repo.list_for_user(user.id)
    last_block_a = next(b for b in history[-1].blocks if b.block_type.value == "a")
    assert last_block_a.work_sets_after == VOLUME_BLOCK.work_sets + 1
    assert last_block_a.work_sets_growth_reason == "stall"

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent = _sent_texts(bot)
    assert texts.WORK_SETS_GROWTH_STALL_NOTICE in sent
    assert texts.WORK_SETS_GROWTH_CEILING_NOTICE not in sent
