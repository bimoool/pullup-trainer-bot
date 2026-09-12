"""Чередующаяся тяжёлая (чётная) тренировка блока Б (issue #97) — реальным
aiogram-роутингом, как test_volume_deload.py/test_workout_finalize.py: план
показывает правильный текст/подсказку веса ДО ввода, а запись в БД получает
is_heavy=True и замороженную цель ПОСЛЕ."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.bot.states import WorkoutStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from tests.test_bot.conftest import make_callback_update as _callback_update


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]


async def _make_user_ready_for_second_heavy_workout(session, user: User) -> int:
    """Один прошлый тренинг на WEIGHT (позиция 1, нечётная) — следующая
    (позиция 2) обязана быть чётной/тяжёлой."""
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=6),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal(20),
    )
    return workout_set.id


async def test_start_workout_plan_shows_heavy_wording_and_suggested_weight(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_user_ready_for_second_heavy_workout(session, user)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent = _sent_texts(bot)
    [plan] = [t for t in sent if t.startswith("<b>План на сегодня:</b>")]
    assert "ТЯЖЁЛАЯ тренировка" in plan
    assert "фиксированные 3" in plan
    # 20 * (1+5/30)/(1+3/30) = 21.212... -> округление вверх до шага 0.5 -> 21.5
    assert "21.5" in plan
    assert "Работаем с" in plan


async def test_completing_heavy_workout_freezes_target_and_shows_suffix(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    workout_set_id = await _make_user_ready_for_second_heavy_workout(session, user)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.set_state(WorkoutStates.waiting_for_comment)
    await fsm.update_data(
        workout_set_id=workout_set_id,
        target_a=10, target_b=4, target_a_override=None, target_b_override=None,
        block_a_working_reps=[10, 10, 10], block_a_max_reps=11,
        block_b_working_reps=[3, 3, 3, 3], block_b_max_reps=5,  # 5-й подход >= порога роста
        equipment_results={
            "a": {"type": "bodyweight", "value": None, "item_id": None},
            "b": {"type": "weight", "value": "21.5", "item_id": None},
        },
        is_heavy_b=True,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="skip_comment"), session=session,
    )

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 2
    block_b = next(b for b in history[-1].blocks if b.block_type.value == "b")
    assert block_b.is_heavy is True
    assert block_b.target_before == 4
    assert block_b.target_after == 4  # заморожена, не пересчитывается
    assert block_b.equipment_changed is False
    assert block_b.equipment_value == Decimal("21.5")

    [summary] = [t for t in _sent_texts(bot) if t.startswith("Тренировка записана")]
    assert texts.HEAVY_TRAINING_DONE_SUFFIX in summary
    assert texts.HEAVY_WEIGHT_GROWTH_SUFFIX.format(reps=5) in summary


async def test_next_normal_workout_plan_after_heavy_uses_normal_weight_not_heavy(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Позиция 3 (нечётная, обычная) после тяжёлой позиции 2 должна
    показать НОРМАЛЬНЫЙ вес (20 кг тренировки 1), не тяжёлый (21.5 кг
    тренировки 2) — регрессия того самого фильтра
    WorkoutRepository._exclude_heavy_entries."""
    workout_set_id = await _make_user_ready_for_second_heavy_workout(session, user)

    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("21.5"),
    )
    # Позиция 2 записана напрямую через репозиторий (не через FSM) — is_heavy
    # проставляется автоматически внутри complete_workout по той же позиции,
    # что видел бы бот. Проверяем это здесь же, чтобы не полагаться молча.
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert history[-1].blocks[0].block_type.value in ("a", "b")
    block_b_2 = next(b for b in history[-1].blocks if b.block_type.value == "b")
    assert block_b_2.is_heavy is True

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent = _sent_texts(bot)
    [plan] = [t for t in sent if t.startswith("<b>План на сегодня:</b>")]
    assert "тяжёлая тренировка" not in plan
    assert "отягощение +20" in plan or "20" in plan
    assert "21.5" not in plan
