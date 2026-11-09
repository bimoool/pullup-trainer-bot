"""Reset only three reserved synthetic staging identities for release hotfix QA."""

import asyncio

from scripts.qa.provision_staging_identities import _purge, assert_staging_environment

QA_LIVE_IDS = (7_000_000_010, 7_000_000_011, 7_000_000_012)


async def main() -> None:
    import os

    from app.db.base import async_session_factory
    from scripts.e2e_seed import seed_v5_weighted_b_live

    assert_staging_environment(os.environ)
    async with async_session_factory() as session:
        for telegram_id in QA_LIVE_IDS:
            await _purge(session, telegram_id)
            await seed_v5_weighted_b_live(session, telegram_id)
        await session.commit()
    print("Provisioned three reserved synthetic hotfix identities on staging")


if __name__ == "__main__":
    asyncio.run(main())
