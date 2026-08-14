from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Achievement


class AchievementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def unlock(self, *, user_id: int, code: str, context: dict | None = None) -> Achievement | None:
        """Идемпотентная разблокировка: если ачивка с этим code у пользователя
        уже есть (UNIQUE(user_id, code)), возвращает None вместо ошибки —
        вызывающему сервису не нужно предварительно проверять has_unlocked."""
        achievement = Achievement(user_id=user_id, code=code, context=context)
        try:
            async with self._session.begin_nested():
                self._session.add(achievement)
                await self._session.flush()
        except IntegrityError:
            # begin_nested() сам откатывает SAVEPOINT и открепляет achievement
            # от сессии при выходе с исключением — повторный expunge() здесь
            # был бы избыточен и падал бы с "not present in this Session".
            return None
        return achievement

    async def has_unlocked(self, user_id: int, code: str) -> bool:
        result = await self._session.execute(
            select(Achievement.id).where(Achievement.user_id == user_id, Achievement.code == code),
        )
        return result.scalar_one_or_none() is not None

    async def list_for_user(self, user_id: int) -> list[Achievement]:
        result = await self._session.execute(
            select(Achievement).where(Achievement.user_id == user_id).order_by(Achievement.unlocked_at),
        )
        return list(result.scalars().all())

    async def list_since(self, after_id: int, *, limit: int) -> list[Achievement]:
        """Разблокировки ЛЮБОГО пользователя с id > after_id — вход для
        app.workers.sheets_sync.py (лист "achievements")."""
        result = await self._session.execute(
            select(Achievement).where(Achievement.id > after_id).order_by(Achievement.id).limit(limit),
        )
        return list(result.scalars().all())
