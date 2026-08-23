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
