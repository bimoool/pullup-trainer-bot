from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import UserFavorite


class FavoriteRepository:
    """Избранное пользователя (issue #272). Видимость целей проверяет вызывающий."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: int) -> list[UserFavorite]:
        result = await self._session.execute(
            select(UserFavorite)
            .where(UserFavorite.user_id == user_id)
            .order_by(UserFavorite.created_at.desc(), UserFavorite.id.desc()),
        )
        return list(result.scalars().all())

    async def add(self, user_id: int, target_type: str, target_id: int) -> None:
        """Идемпотентно: повтор — no-op (ON CONFLICT DO NOTHING)."""
        await self._session.execute(
            pg_insert(UserFavorite)
            .values(user_id=user_id, target_type=target_type, target_id=target_id)
            .on_conflict_do_nothing(constraint="uq_user_favorites_user_target"),
        )

    async def remove(self, user_id: int, target_type: str, target_id: int) -> None:
        await self._session.execute(
            delete(UserFavorite).where(
                UserFavorite.user_id == user_id,
                UserFavorite.target_type == target_type,
                UserFavorite.target_id == target_id,
            ),
        )
