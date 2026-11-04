"""Database error diagnostics must not copy bound profile data into logs/alerts."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import engine


async def test_database_error_diagnostics_hide_bound_personal_data(test_dsn, caplog):
    # A real PostgreSQL error whose driver message does not itself echo the input.
    # The marker stands for a Telegram ID; no production data is used or written.
    private_value = 987654321234567
    # Reuse the runtime privacy policy, but never connect to runtime DATABASE_URL:
    # this test always goes through the repository's dedicated test DB fixture.
    test_engine = create_async_engine(test_dsn, hide_parameters=engine.sync_engine.hide_parameters)
    try:
        async with test_engine.connect() as connection:
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text("SELECT CAST(:private_value AS BIGINT) / 0"),
                    {"private_value": private_value},
                )
    finally:
        await test_engine.dispose()

    with caplog.at_level(logging.ERROR):
        logging.getLogger(__name__).error("database operation failed", exc_info=error.value)

    assert str(private_value) not in str(error.value)
    assert str(private_value) not in repr(error.value)
    assert str(private_value) not in caplog.text
    # Keep actionable diagnostics rather than swallowing the underlying error.
    assert "division by zero" in caplog.text
    assert "SQL parameters hidden" in caplog.text
