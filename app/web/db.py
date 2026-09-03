from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-версия app.bot.middlewares.DbSessionMiddleware — одна сессия
    на запрос, тот же принцип: коммит только при успешном завершении
    хендлера, необработанное исключение просто закрывает сессию без
    коммита (см. CLAUDE.md — то же правило, что у DbSessionMiddleware
    бота). Появился с первым пишущим эндпойнтом Mini App (issue #36,
    Этап 1 — POST /api/workout/submit)."""
    async with async_session_factory() as session:
        yield session
        await session.commit()
