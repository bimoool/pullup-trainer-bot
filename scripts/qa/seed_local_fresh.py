"""Seed the three reserved release profiles in the fixed browser diagnostic DB."""

import asyncio
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import text

from app.config import settings
from app.db.base import async_session_factory
from scripts.qa.identities import QA_IDENTITIES
from scripts.qa.provision_staging_identities import (
    _purge,
    provision_aged_active,
    provision_aged_legacy_snapshot,
    provision_fresh_active,
)


async def main() -> None:
    target = urlparse(settings.database_url.replace("+asyncpg", ""))
    if target.hostname not in {"localhost", "127.0.0.1"} or target.path != "/pullup_qa_fresh_local":
        raise RuntimeError("local fresh diagnostic requires its fixed loopback database")
    if settings.bot_token != "ci-test-token":
        raise RuntimeError("local fresh diagnostic requires the fixed synthetic bot token")
    async with async_session_factory() as session:
        if (
            await session.execute(text("select current_database()"))
        ).scalar() != "pullup_qa_fresh_local":
            raise RuntimeError("local fresh diagnostic database mismatch")
        fresh = QA_IDENTITIES["qa_fresh_active"]
        aged = QA_IDENTITIES["qa_aged_active"]
        legacy = QA_IDENTITIES["qa_aged_legacy_snapshot"]
        now = datetime.now(UTC)
        for identity in (fresh, aged, legacy):
            await _purge(session, identity)
        await provision_fresh_active(session, fresh, now)
        await provision_aged_active(session, aged, now, aged_days=26, visited_weeks=1)
        await provision_aged_legacy_snapshot(session, legacy, now, visited_weeks=1)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
