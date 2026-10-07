"""🧪 Fresh reset (staging) through the real aiogram routing (Dispatcher.feed_update).

Production / unidentified environment: unavailable even for an admin. Non-admin: rejected. Admin on staging: the
first tap is a dry run (nothing written), the explicit «СБРОСИТЬ МОЙ STAGING-ПРОФИЛЬ» applies to the CALLER ONLY
(the telegram id comes from callback.from_user; there is no target parameter)."""

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.bot.handlers import admin as admin_handlers
from app.bot.keyboards import profile_keyboard
from app.config import settings
from app.db.repositories.users import UserRepository
from app.services.qa_staging_guard import StagingEnvironment
from tests.test_bot.conftest import make_callback_update
from tests.test_services.test_qa_fresh_reset import _caller_counts, _populate

ADMIN_TG, OTHER_TG = 7_000_000_201, 7_000_000_202
STAGING = StagingEnvironment(db_name="pullup_test", mini_app_host="staging.app.bimoool.com")


def _texts(bot: Bot) -> list[str]:
    return [m.text for m in bot.session.sent_methods if isinstance(m, SendMessage)]


def _keyboards(bot: Bot) -> list:
    return [m.reply_markup for m in bot.session.sent_methods if isinstance(m, SendMessage)]


def _command_update(telegram_id: int, command: str) -> Update:
    from datetime import UTC, datetime

    return Update(update_id=1, message=Message(
        message_id=1, date=datetime.now(UTC), chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=telegram_id, is_bot=False, first_name="Admin"), text=command,
    ))


def _on_staging(monkeypatch) -> None:
    monkeypatch.setattr(admin_handlers, "identify_running_staging", lambda: STAGING)


async def _uid(session, telegram_id: int) -> int:
    return (await UserRepository(session).get_by_telegram_id(telegram_id)).id


async def test_production_environment_is_unavailable_even_for_admin(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    """No monkeypatch of the environment: the real settings (test DB, no staging Mini App host) are not staging."""
    monkeypatch.setattr(settings, "admin_ids", str(ADMIN_TG))
    uid = await _populate(session, ADMIN_TG)
    before = await _caller_counts(session, uid)

    await dispatcher.feed_update(bot, _command_update(ADMIN_TG, "/qa_fresh_reset"), session=session)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data="qa_fresh_reset_prompt"), session=session)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data="qa_fresh_reset_confirm"), session=session)

    assert all("недоступен" in t for t in _texts(bot))
    assert await _caller_counts(session, uid) == before
    # and the profile never shows the button outside staging
    assert texts.QA_FRESH_RESET_BUTTON not in str(profile_keyboard(is_admin=True, qa_fresh_reset=False))


async def test_non_admin_is_rejected(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", "")
    _on_staging(monkeypatch)
    uid = await _populate(session, OTHER_TG)
    before = await _caller_counts(session, uid)

    await dispatcher.feed_update(bot, _command_update(OTHER_TG, "/qa_fresh_reset"), session=session)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id=OTHER_TG, data="qa_fresh_reset_confirm"), session=session)

    assert not any("DRY RUN" in t or "Fresh reset complete" in t for t in _texts(bot))
    assert await _caller_counts(session, uid) == before


async def test_admin_dry_run_then_confirm_resets_only_the_caller(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", f"{ADMIN_TG},{OTHER_TG}")  # another admin exists — still untouched
    _on_staging(monkeypatch)
    admin_uid = await _populate(session, ADMIN_TG)
    other_uid = await _populate(session, OTHER_TG)
    admin_before = await _caller_counts(session, admin_uid)
    other_before = await _caller_counts(session, other_uid)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data="qa_fresh_reset_prompt"), session=session)

    dry = _texts(bot)[-1]
    assert "DRY RUN" in dry and "pullup_test" in dry and "✅ все пройдены" in dry
    assert "active до" in dry
    assert texts.QA_FRESH_RESET_CONFIRM_BUTTON in str(_keyboards(bot)[-1])
    assert await _caller_counts(session, admin_uid) == admin_before  # dry run wrote nothing

    await dispatcher.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data="qa_fresh_reset_confirm"), session=session)

    done = _texts(bot)[-1]
    assert "Fresh reset complete" in done
    assert "onboarding=false / plans=0 / sessions=0 / coins=0 / entitlement=active" in done
    assert all(n == 0 for n in (await _caller_counts(session, admin_uid)).values())
    assert await _caller_counts(session, other_uid) == other_before


def test_profile_button_is_admin_and_staging_only():
    assert texts.QA_FRESH_RESET_BUTTON in str(profile_keyboard(is_admin=True, qa_fresh_reset=True))
    assert texts.QA_FRESH_RESET_BUTTON not in str(profile_keyboard(is_admin=False, qa_fresh_reset=True))
    assert texts.QA_FRESH_RESET_BUTTON not in str(profile_keyboard(is_admin=True, qa_fresh_reset=False))


async def test_unexpected_error_is_reported_and_rolled_back(session, bot: Bot, dispatcher: Dispatcher, monkeypatch):
    """E.g. archive-table drift on staging: the service rolls back and re-raises; the QA session must see it."""
    monkeypatch.setattr(settings, "admin_ids", str(ADMIN_TG))
    _on_staging(monkeypatch)
    uid = await _populate(session, ADMIN_TG)
    before = await _caller_counts(session, uid)

    from app.services import qa_fresh_reset

    async def broken_system_counts(_session):
        raise RuntimeError("archive drift")

    monkeypatch.setattr(qa_fresh_reset, "_system_counts", broken_system_counts)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data="qa_fresh_reset_confirm"), session=session)

    assert "НЕ выполнен" in _texts(bot)[-1] and "RuntimeError" in _texts(bot)[-1]
    assert await _caller_counts(session, uid) == before


async def test_admin_grant_via_bot_then_dry_run_shows_the_same_effective_entitlement(
    session, bot: Bot, dispatcher: Dispatcher, monkeypatch,
):
    """The staging scenario end to end through the real handlers: trial -> «🎁 Выдать подписку» on oneself -> the push
    names the new expiry -> /qa_fresh_reset shows THAT expiry as the preserved, effective entitlement."""
    import re
    from datetime import UTC, datetime

    from app.services.subscription import SubscriptionService

    monkeypatch.setattr(settings, "admin_ids", str(ADMIN_TG))
    _on_staging(monkeypatch)
    user = await UserRepository(session).create(telegram_id=ADMIN_TG, username="owner")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data=f"admin_grant_days:{user.id}"), session=session)
    await dispatcher.feed_update(bot, _command_update(ADMIN_TG, "15"), session=session)
    await session.commit()  # what DbSessionMiddleware does after the handler
    push = next(t for t in _texts(bot) if "продлена" in t)
    day, month, year = re.search(r"до (\d\d)\.(\d\d)\.(\d{4})", push).groups()

    await dispatcher.feed_update(bot, _command_update(ADMIN_TG, "/qa_fresh_reset"), session=session)

    dry = _texts(bot)[-1]
    assert f"active до {year}-{month}-{day}" in dry, dry
    assert "Доступ к курсам сейчас (как считает продукт, users.*): есть" in dry
    assert "active/admin_grant" in dry and "trial/trial" in dry
    assert "✅ все пройдены" in dry
