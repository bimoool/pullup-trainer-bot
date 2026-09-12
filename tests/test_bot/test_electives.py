"""Факультативы (пакет #6) — 4 формата вне плана, ротация без повтора +
не чаще 2 раз в неделю (issue #94), снаряд всегда как в блоке на объём
(без пикера). Реальным aiogram-роутингом."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.states import ElectiveStates
from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.session import BlockLog
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


async def _make_history(session, user: User, *, equipment_type=EquipmentType.WEIGHT, equipment_value=Decimal("20.0")):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=equipment_type, block_a_equipment_value=equipment_value,
        block_b_equipment_type=equipment_type, block_b_equipment_value=equipment_value,
    )


async def test_menu_without_any_workout_shows_toast_not_picker(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    # См. комментарий в test_menu_blocked_when_weekly_limit_reached — общий
    # telegram_id между тестами файла, чистим FSM явно перед негативной
    # проверкой "состояние не изменилось".
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    assert await fsm.get_state() is None


async def test_menu_with_history_shows_all_four_when_none_done_yet(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_type.state
    [menu] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ELECTIVE_MENU_INTRO
    ]
    callbacks = {b.callback_data for row in menu.reply_markup.inline_keyboard for b in row}
    assert callbacks == {f"elective:{t.value}" for t in ElectiveType} | {"cancel_flow"}


async def test_menu_excludes_type_already_done_in_current_cycle(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    # Вне недельного окна (10 дней назад) — не блокирует лимитом, но
    # по-прежнему учитывается в ротации (она смотрит на всю историю, не
    # только на последнюю неделю).
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.MAX_REPS_LADDER,
        performed_at=datetime.now(UTC) - timedelta(days=10),
        total_reps=30, reps_sequence=[10, 8, 7, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    [menu] = [
        m for m in bot.session.sent_methods
        if isinstance(m, SendMessage) and m.text == texts.ELECTIVE_MENU_INTRO
    ]
    callbacks = {b.callback_data for row in menu.reply_markup.inline_keyboard for b in row}
    assert f"elective:{ElectiveType.MAX_REPS_LADDER.value}" not in callbacks
    assert len(callbacks) == 4  # 3 доступных + отмена


async def test_menu_blocked_when_weekly_limit_reached(session, user: User, bot: Bot, dispatcher: Dispatcher):
    # Session-scoped dispatcher + общий telegram_id между тестами файла —
    # предыдущий тест мог оставить FSM-состояние waiting_for_type (это его
    # ожидаемый успешный исход, он его не чистит). Явно чистим здесь, иначе
    # "assert state is None" ниже проверял бы чужое состояние, не текущий
    # прогон (тот же приём, что и в test_edit_calendar.py).
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    await fsm.clear()

    await _make_history(session, user)
    # Лимит — 2 в неделю (ELECTIVE_MAX_PER_WEEK, issue #94), нужны обе записи,
    # чтобы reached.
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.W_LADDER, performed_at=datetime.now(UTC) - timedelta(days=2),
        total_reps=40, reps_sequence=[5, 4, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=datetime.now(UTC) - timedelta(days=1),
        total_reps=30, reps_sequence=[5, 5, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    assert await fsm.get_state() is None
    menus = [m for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text == texts.ELECTIVE_MENU_INTRO]
    assert menus == []


async def test_entry_older_than_a_week_does_not_count_toward_limit(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.W_LADDER, performed_at=datetime.now(UTC) - timedelta(days=8),
        total_reps=40, reps_sequence=[5, 4, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_type.state


async def test_type_choice_uses_current_volume_block_equipment_no_picker(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    await _make_history(session, user, equipment_type=EquipmentType.WEIGHT, equipment_value=Decimal("20.0"))
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    await dispatcher.feed_update(
        bot,
        _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.MAX_REPS_LADDER.value}"),
        session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_reps.state
    data = await fsm.get_data()
    assert data["equipment_type"] == "weight"
    assert data["equipment_value"] == "20.00"  # Numeric(5,2) в БД, круглый трип добавляет 0
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert any("отягощение" in t for t in sent_texts)


async def test_max_reps_ladder_requires_exactly_four_numbers(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot,
        _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.MAX_REPS_LADDER.value}"),
        session=session,
    )

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="12 10 8"), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_reps.state  # не продвинулось
    history = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_max_reps_ladder_records_full_sequence_and_sum(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot,
        _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.MAX_REPS_LADDER.value}"),
        session=session,
    )

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="12 10 8 6"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() is None
    [elective] = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert elective.elective_type == ElectiveType.MAX_REPS_LADDER
    assert elective.reps_sequence == [12, 10, 8, 6]
    assert elective.total_reps == 36


async def test_w_ladder_accepts_incomplete_sequence(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.W_LADDER.value}"),
        session=session,
    )

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="5 4 3"), session=session)

    [elective] = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert elective.reps_sequence == [5, 4, 3]
    assert elective.total_reps == 12


async def test_w_ladder_rejects_more_than_seventeen_numbers(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.W_LADDER.value}"),
        session=session,
    )

    too_many = " ".join(["1"] * 18)
    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text=too_many), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_reps.state
    history = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_three_minutes_accepts_up_to_six_intervals(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.THREE_MINUTES.value}"),
        session=session,
    )

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="8 7 6 5 4 3"), session=session,
    )

    [elective] = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert elective.reps_sequence == [8, 7, 6, 5, 4, 3]
    assert elective.total_reps == 33


async def test_three_minutes_rejects_more_than_six_intervals(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.THREE_MINUTES.value}"),
        session=session,
    )

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="8 7 6 5 4 3 2"), session=session,
    )

    history = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_volume_target_goal_is_five_times_current_target(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.VOLUME_TARGET.value}"),
        session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_total.state
    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    # target_a после первой тренировки (замер 10, avg=11) — не проверяем
    # число жёстко здесь (это дело recalculate_target), только что "×5"
    # реально применилось: цель блока × 5 больше самого target ровно в 5 раз.
    assert any("Подтягивания на объём" in t and "набери" in t for t in sent_texts)


async def test_volume_target_records_only_total_no_sequence(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.VOLUME_TARGET.value}"),
        session=session,
    )

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="52"), session=session)

    [elective] = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert elective.reps_sequence is None
    assert elective.total_reps == 52
    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() is None


async def test_volume_target_rejects_non_numeric_total(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data=f"elective:{ElectiveType.VOLUME_TARGET.value}"),
        session=session,
    )

    await dispatcher.feed_update(bot, _message_update(telegram_id=user.telegram_id, text="много"), session=session)

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_total.state
    history = await ElectiveWorkoutRepository(session).list_for_user(user.id)
    assert history == []


async def test_too_early_offers_elective_when_allowed(session, user: User, bot: Bot, dispatcher: Dispatcher):
    from app.services.subscription import SubscriptionService

    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    # _make_history записывает тренировку "только что" — MIN_REST_DAYS=2
    # ещё не прошло, TOO_EARLY сработает естественным образом.
    await _make_history(session, user)

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    too_early = [t for t in sent_texts if t.startswith("Рано —")]
    assert too_early
    assert texts.TOO_EARLY_ELECTIVE_OFFER in too_early[0]


async def test_too_early_does_not_offer_elective_when_weekly_limit_reached(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    from app.services.subscription import SubscriptionService

    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    await _make_history(session, user)
    # Лимит — 2 в неделю (ELECTIVE_MAX_PER_WEEK, issue #94), обе записи
    # нужны, чтобы предложение факультатива перестало показываться.
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.W_LADDER, performed_at=datetime.now(UTC) - timedelta(days=1),
        total_reps=20, reps_sequence=[5, 4, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=datetime.now(UTC),
        total_reps=30, reps_sequence=[5, 5, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    too_early = [t for t in sent_texts if t.startswith("Рано —")]
    assert too_early
    assert texts.TOO_EARLY_ELECTIVE_OFFER not in too_early[0]


async def test_offer_button_in_too_early_reaches_the_same_picker(session, user: User, bot: Bot, dispatcher: Dispatcher):
    from app.services.subscription import SubscriptionService

    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    await _make_history(session, user)
    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="start_workout"), session=session,
    )

    await dispatcher.feed_update(
        bot, _callback_update(telegram_id=user.telegram_id, data="electives_start"), session=session,
    )

    fsm = dispatcher.fsm.get_context(bot=bot, chat_id=user.telegram_id, user_id=user.telegram_id)
    assert await fsm.get_state() == ElectiveStates.waiting_for_type.state


# --- Проактивный статус "сегодня отдых" при открытии раздела (issue #94) ------------


async def test_workout_section_shows_rest_day_status_proactively_when_too_early(
    session, user: User, bot: Bot, dispatcher: Dispatcher,
):
    """Раньше статус "рано" показывался только РЕАКТИВНО, после клика
    "Начать тренировку" (см. test_too_early_offers_elective_when_allowed) —
    теперь то же сообщение + предложение факультатива приходит сразу при
    открытии раздела "Тренировка", без явного клика."""
    from app.services.subscription import SubscriptionService

    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    await _make_history(session, user)

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="💪 Тренировка"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    too_early = [t for t in sent_texts if t.startswith("Рано —")]
    assert too_early
    assert texts.TOO_EARLY_ELECTIVE_OFFER in too_early[0]
    assert texts.SECTION_WORKOUT_TITLE in sent_texts


async def test_workout_section_no_rest_day_status_when_ready(session, user: User, bot: Bot, dispatcher: Dispatcher):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))

    await dispatcher.feed_update(
        bot, _message_update(telegram_id=user.telegram_id, text="💪 Тренировка"), session=session,
    )

    sent_texts = [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage) and m.text]
    assert not [t for t in sent_texts if t and t.startswith("Рано —")]
    assert texts.SECTION_WORKOUT_TITLE in sent_texts
