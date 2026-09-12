"""Проактивный статус «сегодня отдых» при открытии раздела "Тренировка"
(issue #94) — раньше пауза между тренировками была молчаливой: ничего не
показывалось, пока пользователь сам не нажимал "Начать тренировку" и не
получал TOO_EARLY реактивно (см. tests/test_bot/test_too_early_countdown.py).
Теперь тот же самый статус (app.bot.handlers.workout.resolve_rest_day_notice)
показывается сразу при открытии раздела, до нажатия любой кнопки. Реальным
aiogram-роутингом."""

from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.keyboards import BOTTOM_MENU_WORKOUT
from app.config import settings
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.session import BlockLog


def _workout_section_update(*, telegram_id: int) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=101, date=datetime.now(UTC),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Tester"),
            text=BOTTOM_MENU_WORKOUT,
        ),
    )


async def _make_history(session, user: User, *, performed_at: datetime) -> None:
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


def _sent_texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]


async def test_shows_rest_day_notice_before_section_menu_when_too_early(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    # Тренировка "только что" — MIN_REST_DAYS ещё не прошло, TOO_EARLY
    # сработает естественным образом (тот же приём, что и в test_electives.py).
    await _make_history(session, user, performed_at=datetime.now(UTC))

    await dispatcher.feed_update(bot, _workout_section_update(telegram_id=user.telegram_id), session=session)

    sent = _sent_texts(bot)
    rest_notice = [t for t in sent if t.startswith("Рано —")]
    assert rest_notice
    assert texts.TOO_EARLY_ELECTIVE_OFFER in rest_notice[0]
    # Обычное меню раздела по-прежнему показывается следом — статус не
    # заменяет остальные пункты (план/бэкдейт/факультатив/редактирование).
    assert texts.SECTION_WORKOUT_TITLE in sent
    assert sent.index(rest_notice[0]) < sent.index(texts.SECTION_WORKOUT_TITLE)


async def test_shows_limit_reached_notice_when_weekly_elective_limit_exhausted(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_history(session, user, performed_at=datetime.now(UTC))
    # ELECTIVE_MAX_PER_WEEK == 2 (issue #94) — обе уже использованы.
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.W_LADDER, performed_at=datetime.now(UTC),
        total_reps=20, reps_sequence=[5, 4, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.MAX_REPS_LADDER, performed_at=datetime.now(UTC),
        total_reps=30, reps_sequence=[10, 8, 7, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    await dispatcher.feed_update(bot, _workout_section_update(telegram_id=user.telegram_id), session=session)

    sent = _sent_texts(bot)
    rest_notice = [t for t in sent if t.startswith("Рано —")]
    assert rest_notice
    assert texts.TOO_EARLY_ELECTIVE_OFFER not in rest_notice[0]
    assert texts.TOO_EARLY_ELECTIVE_LIMIT_REACHED.format(limit=2) in rest_notice[0]


async def test_no_rest_notice_when_ready_to_train(session, user: User, bot: Bot, dispatcher: Dispatcher):
    from app.domain.constants import MIN_REST_DAYS

    await _make_history(session, user, performed_at=datetime.now(UTC) - timedelta(days=MIN_REST_DAYS + 1))

    await dispatcher.feed_update(bot, _workout_section_update(telegram_id=user.telegram_id), session=session)

    sent = _sent_texts(bot)
    assert not [t for t in sent if t.startswith("Рано —")]
    assert texts.SECTION_WORKOUT_TITLE in sent


async def test_no_rest_notice_without_any_history_yet(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(bot, _workout_section_update(telegram_id=user.telegram_id), session=session)

    sent = _sent_texts(bot)
    assert not [t for t in sent if t.startswith("Рано —")]
    assert texts.SECTION_WORKOUT_TITLE in sent


async def test_no_rest_notice_for_admin_even_when_too_early(
    session, user: User, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    monkeypatch.setattr(settings, "admin_ids", str(user.telegram_id))
    await _make_history(session, user, performed_at=datetime.now(UTC))

    await dispatcher.feed_update(bot, _workout_section_update(telegram_id=user.telegram_id), session=session)

    sent = _sent_texts(bot)
    assert not [t for t in sent if t.startswith("Рано —")]
    assert texts.SECTION_WORKOUT_TITLE in sent
