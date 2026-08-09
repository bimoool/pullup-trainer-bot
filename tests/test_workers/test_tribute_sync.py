from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.workers.tribute_sync import JOB_ID, SYNC_INTERVAL_MINUTES, register, sync_tribute_payments


def test_register_adds_job_with_expected_interval():
    scheduler = AsyncIOScheduler()
    # add_job только сохраняет kwargs, не вызывает функцию — реальный Bot
    # (с валидным токеном, сетевыми проверками) здесь не нужен.
    dummy_bot = object()

    register(scheduler, dummy_bot)

    job = scheduler.get_job(JOB_ID)

    assert job is not None
    assert job.func is sync_tribute_payments
    assert job.kwargs == {"bot": dummy_bot}
    assert job.trigger.interval.total_seconds() == SYNC_INTERVAL_MINUTES * 60
