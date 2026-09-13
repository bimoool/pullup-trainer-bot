"""🔔 Напоминание о тренировке (issue #100) — тумблер+час через реальный
aiogram-роутинг (как test_profile_edit.py), и сам воркер (app/workers/
training_reminder.py) — прямым вызовом с явной session (как
send_weekly_digest_reminder в tests/test_bot/test_weekly_digest.py), чтобы
не задеть боевую БД через async_session_factory."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage

from app.bot import texts
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import DEFAULT_TRAINING_REMINDER_HOUR, EquipmentType
from app.domain.session import BlockLog
from app.workers.training_reminder import send_training_reminders
from tests.test_bot.conftest import make_callback_update as _callback_update

# Без DST-переходов — стабильный фиксированный офсет, чтобы тест не зависел
# от даты прогона.
TIMEZONE_NAME = "Europe/Moscow"


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]


async def _record_history(session, user: User, *, days_ago: int) -> None:
    performed_at = datetime.now(UTC) - timedelta(days=days_ago)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )


async def test_open_shows_disabled_by_default(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="training_reminder_open"), session=session,
    )

    [text] = _sent_texts(bot)
    assert texts.TRAINING_REMINDER_STATUS_OFF in text


async def test_toggle_enables_then_disables(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="training_reminder_toggle"), session=session,
    )
    reloaded = await UserRepository(session).get_by_telegram_id(user.telegram_id)
    assert reloaded.training_reminder_enabled is True

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="training_reminder_toggle"), session=session,
    )
    reloaded_again = await UserRepository(session).get_by_telegram_id(user.telegram_id)
    assert reloaded_again.training_reminder_enabled is False


async def test_hour_adjust_wraps_around_midnight(session, user: User, bot: Bot, dispatcher: Dispatcher):
    users = UserRepository(session)
    await users.set_training_reminder(user.id, enabled=True, hour=0)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="training_reminder_hour:-1"), session=session,
    )

    reloaded = await users.get_by_telegram_id(user.telegram_id)
    assert reloaded.training_reminder_hour == 23

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="training_reminder_hour:1"), session=session,
    )
    reloaded_again = await users.get_by_telegram_id(user.telegram_id)
    assert reloaded_again.training_reminder_hour == 0


async def test_hour_adjust_starts_from_default_when_unset(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="training_reminder_hour:1"), session=session,
    )

    reloaded = await UserRepository(session).get_by_telegram_id(user.telegram_id)
    assert reloaded.training_reminder_hour == DEFAULT_TRAINING_REMINDER_HOUR + 1


async def test_worker_sends_reminder_when_ready_and_hour_matches(session, user: User, bot: Bot):
    users = UserRepository(session)
    await users.complete_onboarding(user.id, datetime.now(UTC))
    await users.update_profile(user.id, timezone=TIMEZONE_NAME)
    local_now = datetime.now(ZoneInfo(TIMEZONE_NAME))
    await users.set_training_reminder(user.id, enabled=True, hour=local_now.hour)
    await _record_history(session, user, days_ago=3)  # READY: MIN_REST_DAYS=2 < 3 < GAP_ROLLBACK_DAYS=21

    await send_training_reminders(bot, session=session)

    assert _sent_texts(bot) == [texts.TRAINING_REMINDER_TODAY]
    reloaded = await users.get_by_telegram_id(user.telegram_id)
    assert reloaded.training_reminder_last_sent_date == local_now.date()


async def test_worker_does_not_resend_same_local_day(session, user: User, bot: Bot):
    users = UserRepository(session)
    await users.complete_onboarding(user.id, datetime.now(UTC))
    await users.update_profile(user.id, timezone=TIMEZONE_NAME)
    local_now = datetime.now(ZoneInfo(TIMEZONE_NAME))
    await users.set_training_reminder(user.id, enabled=True, hour=local_now.hour)
    await _record_history(session, user, days_ago=3)

    await send_training_reminders(bot, session=session)
    await send_training_reminders(bot, session=session)

    assert len(_sent_texts(bot)) == 1


async def test_worker_skips_when_too_early(session, user: User, bot: Bot):
    users = UserRepository(session)
    await users.complete_onboarding(user.id, datetime.now(UTC))
    await users.update_profile(user.id, timezone=TIMEZONE_NAME)
    local_now = datetime.now(ZoneInfo(TIMEZONE_NAME))
    await users.set_training_reminder(user.id, enabled=True, hour=local_now.hour)
    await _record_history(session, user, days_ago=1)  # TOO_EARLY: MIN_REST_DAYS=2 > 1

    await send_training_reminders(bot, session=session)

    assert _sent_texts(bot) == []


async def test_worker_skips_when_disabled(session, user: User, bot: Bot):
    users = UserRepository(session)
    await users.complete_onboarding(user.id, datetime.now(UTC))
    await users.update_profile(user.id, timezone=TIMEZONE_NAME)
    local_now = datetime.now(ZoneInfo(TIMEZONE_NAME))
    await users.set_training_reminder(user.id, enabled=False, hour=local_now.hour)
    await _record_history(session, user, days_ago=3)

    await send_training_reminders(bot, session=session)

    assert _sent_texts(bot) == []


async def test_worker_skips_when_timezone_missing(session, user: User, bot: Bot):
    users = UserRepository(session)
    await users.complete_onboarding(user.id, datetime.now(UTC))
    await users.set_training_reminder(user.id, enabled=True, hour=datetime.now(UTC).hour)
    await _record_history(session, user, days_ago=3)

    await send_training_reminders(bot, session=session)

    assert _sent_texts(bot) == []
