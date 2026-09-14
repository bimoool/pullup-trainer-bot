"""Ежемесячный тест на максимум блока на объём (ревизия формулы прогрессии,
п.4; переосмыслено из "разгрузки" в issue #89 — по факту не снижение
нагрузки, а разовая проверка реального текущего максимума) — раз в 30 дней
структура блока A целиком заменяется на один подход без отягощения,
независимо от того, на чём блок обычно сейчас стоит. Реальным
aiogram-роутингом, как test_workout_finalize.py."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import WorkoutStates
from app.db.models import BlockType, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import (
    DELOAD_INTERVAL_DAYS,
    EquipmentType,
)
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


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]


async def _make_user_due_for_deload(session, user: User) -> None:
    """Пользователь с реальной историей (одна тренировка, блок A уже на
    весе — проверяем, что разгрузка форсирует свой вес ДАЖЕ поверх этого),
    у которого первый сет стартовал 31 день назад и последняя тренировка
    была достаточно давно для READY (не TOO_EARLY/GAP_*)."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workout_set.started_at = datetime.now(UTC) - timedelta(days=31)
    await session.flush()

    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.WEIGHT, block_a_equipment_value=Decimal(5),
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


async def test_start_workout_shows_deload_prompt_and_forces_bodyweight(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_user_due_for_deload(session, user)

    # Посчитано вручную по формуле recalculate_volume_block (не выведено из
    # тестируемого кода): единственная предшествующая тренировка — target=10,
    # work_sets=3, working_reps=(11,11,11), max_reps=12 → delta=2>0,
    # avg_working=11, step=max(1, ceil(10*0.05))=1, computed_target=12.
    # 12 < VOLUME_TARGET_CEILING(33), поэтому это и есть target_after=12,
    # без отката/доп.подходов. Текст теста на максимум (issue #105) больше не
    # называет никакого ориентирующего числа — target_a в FSM остаётся равным
    # текущей цели блока A (12), просто не показывается пользователю.
    expected_target_a = 12

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent = _sent_texts(bot)
    expected_prompt = texts.VOLUME_DELOAD_PROMPT.format(interval_days=DELOAD_INTERVAL_DAYS)
    assert expected_prompt in sent
    assert not any(text.startswith("<b>План на сегодня:</b>") for text in sent)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    data = await fsm.get_data()
    assert data["is_deload_a"] is True
    assert data["target_a"] == expected_target_a
    assert data["equipment_results"]["a"] == {"type": "bodyweight", "value": None, "item_id": None}
    assert await fsm.get_state() == WorkoutStates.waiting_for_block_a


async def test_deload_block_a_accepts_single_number_without_anomaly_prompt(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    # Реальный результат теста на максимум — произвольное число, введённое
    # пользователем; никак не привязано к ориентиру из VOLUME_DELOAD_PROMPT
    # (тот — только подсказка масштаба, не обязательная цель).
    actual_max_reps = 15

    await _make_user_due_for_deload(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text=str(actual_max_reps)), session=session,
    )

    sent = _sent_texts(bot)
    assert texts.OPTIONAL_EXERCISE_OFFER in sent
    assert not any("похоже" in text or "рабочих подхода" in text for text in sent if "?" not in text[:1])

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    data = await fsm.get_data()
    assert data["block_a_working_reps"] == []
    assert data["block_a_max_reps"] == actual_max_reps


async def test_deload_workout_records_frozen_progress_and_summary_suffix(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    actual_max_reps = 15

    await _make_user_due_for_deload(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text=str(actual_max_reps)), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="optional_exercise:skip"), session=session,
    )
    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="3 3 3 3 4"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_comment"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    deload_workout = history[-1]
    block_a = next(b for b in deload_workout.blocks if b.block_type == BlockType.A)

    assert block_a.is_deload is True
    assert block_a.equipment_type == EquipmentType.BODYWEIGHT
    assert list(block_a.working_reps) == []
    assert block_a.max_reps == actual_max_reps
    # Заморожено — совпадает с тем, что было ДО (то же самое, что дала бы
    # обычная тренировка без разгрузки, работавшая бы дальше с прошлой цели).
    assert block_a.target_after == block_a.target_before
    assert block_a.work_sets_after == block_a.work_sets_before
    assert block_a.equipment_changed is False

    summary = next(
        m.text for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text and m.text.startswith(texts.WORKOUT_SUMMARY.split("{")[0])
    )
    assert texts.VOLUME_DELOAD_DONE_SUFFIX in summary
    assert texts.VOLUME_WORK_SET_ADDED_SUFFIX not in summary
    assert texts.VOLUME_WEIGHT_TRANSITION_SUFFIX not in summary
