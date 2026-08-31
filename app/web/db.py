from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-версия app.bot.middlewares.DbSessionMiddleware — одна сессия
    на запрос. Веб-слой сейчас только читает (GET /api/hello), поэтому
    commit не нужен; появится с первым пишущим эндпойнтом Mini App."""
    async with async_session_factory() as session:
        yield session
