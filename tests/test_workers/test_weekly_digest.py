from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.workers.weekly_digest import JOB_ID, register, send_weekly_digest_reminder


def test_register_adds_job_on_sunday_evening():
    scheduler = AsyncIOScheduler()
    dummy_bot = object()
    dummy_dispatcher = object()

    register(scheduler, dummy_bot, dummy_dispatcher)

    job = scheduler.get_job(JOB_ID)

    assert job is not None
    assert job.func is send_weekly_digest_reminder
    assert job.kwargs == {"bot": dummy_bot, "dispatcher": dummy_dispatcher}
    assert isinstance(job.trigger, CronTrigger)


async def test_worker_delivery_failure_redacts_exception_and_continues_to_next_admin(session, monkeypatch, caplog):
    from aiogram import Dispatcher
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.methods import SendMessage

    from app.bot.states import AdminStates
    from app.config import settings

    private_value = "synthetic-private-worker-note"
    monkeypatch.setattr(settings, "admin_ids", "999999,999998")

    class GitHub:
        async def list_commits_since(self, since):
            return []

        async def list_open_issues(self):
            return []

    class Bot:
        id = 123456789

        def __init__(self):
            self.calls = []

        async def send_message(self, chat_id, text):
            self.calls.append(chat_id)
            if chat_id == 999999:
                raise TelegramBadRequest(method=SendMessage(chat_id=chat_id, text=text), message=private_value)

    bot = Bot()
    dispatcher = Dispatcher(storage=MemoryStorage())
    await send_weekly_digest_reminder(bot, dispatcher, session=session, github_client=GitHub())
    assert bot.calls == [999999, 999998]
    assert private_value not in caplog.text
    assert "TelegramBadRequest" in caplog.text
    assert not any(record.exc_info for record in caplog.records)
    second = dispatcher.fsm.get_context(bot=bot, chat_id=999998, user_id=999998)
    assert await second.get_state() == AdminStates.waiting_for_weekly_digest_text.state
