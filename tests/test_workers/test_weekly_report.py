from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.workers.weekly_report import JOB_ID, register, send_weekly_reports


def test_register_adds_job_on_monday_mornings():
    scheduler = AsyncIOScheduler()
    dummy_bot = object()

    register(scheduler, dummy_bot)

    job = scheduler.get_job(JOB_ID)

    assert job is not None
    assert job.func is send_weekly_reports
    assert job.kwargs == {"bot": dummy_bot}
    assert isinstance(job.trigger, CronTrigger)
