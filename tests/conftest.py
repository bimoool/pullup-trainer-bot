import asyncio
import os
import subprocess
import time
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import User
from app.db.repositories.users import UserRepository

REPO_ROOT = Path(__file__).resolve().parents[1]

TABLES = (
    "blocks", "workouts", "workout_sets", "baselines", "coins",
    "achievements", "subscriptions", "events", "users",
)


def _discover_test_dsn() -> str:
    """Реальный Postgres из docker-compose, не мок. Поднимает db-сервис (если
    ещё не поднят), ждёт healthy, создаёт при необходимости базу pullup_test
    (initdb-скрипт делает это только на свежем volume — на уже существующем
    volume без нашей правки её может не быть) и возвращает DSN."""
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override

    subprocess.run(
        ["docker", "compose", "up", "-d", "db"], cwd=REPO_ROOT, check=True, capture_output=True,
    )
    for _ in range(30):
        health = subprocess.run(
            ["docker", "compose", "ps", "db", "--format", "{{.Health}}"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if health == "healthy":
            break
        time.sleep(1)
    else:
        raise RuntimeError("db service did not become healthy in time")

    port_output = subprocess.run(
        ["docker", "compose", "port", "db", "5432"], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    port = port_output.rsplit(":", 1)[1]
    return f"postgresql+asyncpg://pullup:pullup@localhost:{port}/pullup_test"


async def _ensure_database_exists(dsn: str) -> None:
    admin_dsn = dsn.rsplit("/", 1)[0] + "/pullup"
    admin_engine = create_async_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = 'pullup_test'"))
            if not exists:
                await conn.execute(text("CREATE DATABASE pullup_test OWNER pullup"))
    finally:
        await admin_engine.dispose()


@pytest.fixture(scope="session")
def test_dsn() -> str:
    """Синхронная фикстура намеренно: alembic.command.upgrade сам вызывает
    asyncio.run() внутри (через env.py) — если бы это шло из async-фикстуры,
    она бы уже сидела в своём event loop, и вложенный asyncio.run() упал бы
    с RuntimeError. Здесь, до старта event loop теста, конфликта нет."""
    dsn = _discover_test_dsn()
    asyncio.run(_ensure_database_exists(dsn))

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(alembic_cfg, "head")
    return dsn


@pytest_asyncio.fixture
async def session(test_dsn):
    # Отдельный engine (=отдельный пул соединений) на каждый тест — дороже,
    # чем один на сессию, но исключает контакт между тестами через пул:
    # с общим движком asyncpg-соединения периодически ловили "another
    # operation is in progress" / "manually started transaction" при
    # переиспользовании соединения между TRUNCATE и следующей сессией.
    test_engine = create_async_engine(test_dsn)
    try:
        async with test_engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE TABLE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))

        session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db_session:
            yield db_session
    finally:
        await test_engine.dispose()


@pytest_asyncio.fixture
async def user(session) -> User:
    return await UserRepository(session).create(telegram_id=1001, username="tester")
