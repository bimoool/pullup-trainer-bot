import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings
from app.db import (
    models,  # noqa: F401 — регистрирует таблицы в Base.metadata для autogenerate
    models_program,  # noqa: F401 — то же самое для многокурсовой схемы (feature/multi-program)
)
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False — иначе fileConfig() (по умолчанию True)
    # молча отключает (logger.disabled = True) все уже созданные к этому
    # моменту логгеры, не перечисленные в alembic.ini — включая
    # logging.getLogger(__name__) любого app.*-модуля, импортированного до
    # прогона миграций (у pytest это происходит на сборе тестов, раньше
    # session-scoped фикстуры, что и запускает миграции). Найдено на
    # caplog-тестах app/workers/weekly_digest.py: caplog.records оставался
    # пустым даже для прямого синхронного logger.warning() в теле теста —
    # не сбой конкретного теста, а глобальное отключение логов для всего
    # процесса pytest после первого прогона миграций.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Приоритет — URL, явно переданный через Alembic Config (так тесты в
# tests/conftest.py указывают на pullup_test); если его нет — обычный запуск
# из командной строки берёт DATABASE_URL из .env через Settings.
database_url = config.get_main_option("sqlalchemy.url") or settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable: AsyncEngine = create_async_engine(database_url)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
