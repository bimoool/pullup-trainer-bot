from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """ВСЕГДА подключать как ``Depends(get_session, scope="function")``: коммит должен закончиться ДО отправки ответа.
    По умолчанию (scope «request»; проверено в FastAPI 0.143, scope есть с 0.121) код после ``yield`` выполняется ПОСЛЕ отправки ответа — клиент
    получал 200 раньше коммита и следующим запросом не видел свою же запись (CI 16.10: старт тренировки → GET active
    ещё без неё → экран завершал только что начатую сессию). Проверка — tests/test_web/test_session_commit_scope.py.

    FastAPI-версия app.bot.middlewares.DbSessionMiddleware — одна сессия
    на запрос, тот же принцип: коммит только при успешном завершении
    хендлера, необработанное исключение просто закрывает сессию без
    коммита (см. CLAUDE.md — то же правило, что у DbSessionMiddleware
    бота). Появился с первым пишущим эндпойнтом Mini App (issue #36,
    Этап 1 — POST /api/workout/submit)."""
    async with async_session_factory() as session:
        yield session
        await session.commit()
