"""Разовая ретроактивная разблокировка ачивок, введённых ревизией
достижений: TEN_WORKOUTS_STREAK, MONTH_NO_GAPS, MAX_REPS_PLUS_TEN и пороги
объёма VOLUME_100/1000/10000/100000.

Условие для этих ачивок могло быть выполнено ЗАДНИМ ЧИСЛОМ уже
существующими пользователями — например, серия из 10+ тренировок подряд
без единого нового события. unlock_achievement идемпотентен, поэтому
достаточно прогнать те же проверки, что срабатывают после обычной записи
тренировки (app.services.achievement_checks), по каждому пользователю —
уже разблокированные коды просто не начислят монеты повторно.

EQUIPMENT_CHANGED/SET_COMPLETED/FIRST_WEIGHTED_PULLUP сюда не входят:
они требуют конкретного СОБЫТИЯ (переход снаряда/закрытие сета/первая
тренировка с отягощением на именно ЭТОЙ тренировке), не выводятся из
статичного состояния истории — заново их для прошлых тренировок не
восстановить, это не баг ретроактивности, а другая природа проверки.

Использование (внутри контейнера app):
    python scripts/backfill_achievements.py
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.repositories.users import UserRepository
from app.services.achievement_checks import unlock_history_achievements, unlock_volume_milestones


async def backfill_all_users(session: AsyncSession, *, now: datetime) -> int:
    """Основная логика, отделена от main() ради тестируемости на тестовой
    БД (main() привязан к боевому async_session_factory). Не коммитит —
    вызывающий код решает, когда (main() коммитит один раз в конце)."""
    users = await UserRepository(session).list_all()
    for user in users:
        await unlock_history_achievements(session, user.id, now=now)
        await unlock_volume_milestones(session, user.id)
    return len(users)


async def main() -> None:
    async with async_session_factory() as session:
        checked = await backfill_all_users(session, now=datetime.now(UTC))
        await session.commit()
        print(f"готово: проверено {checked} пользователей")


if __name__ == "__main__":
    asyncio.run(main())
