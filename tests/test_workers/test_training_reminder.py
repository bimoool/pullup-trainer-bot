from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.workers.training_reminder import (
    JOB_ID,
    POLL_INTERVAL_MINUTES,
    register,
    send_training_reminders,
)


def test_register_adds_job_with_expected_interval():
    scheduler = AsyncIOScheduler()
    dummy_bot = object()

    register(scheduler, dummy_bot)

    job = scheduler.get_job(JOB_ID)

    assert job is not None
    assert job.func is send_training_reminders
    assert job.kwargs == {"bot": dummy_bot}
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == POLL_INTERVAL_MINUTES * 60
