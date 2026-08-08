from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.workers.tribute_sync import JOB_ID, SYNC_INTERVAL_MINUTES, register, sync_tribute_payments


def test_register_adds_job_with_expected_interval():
    scheduler = AsyncIOScheduler()
    register(scheduler)

    job = scheduler.get_job(JOB_ID)

    assert job is not None
    assert job.func is sync_tribute_payments
    assert job.trigger.interval.total_seconds() == SYNC_INTERVAL_MINUTES * 60
