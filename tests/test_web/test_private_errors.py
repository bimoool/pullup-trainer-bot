"""Unexpected web errors must not escape into server logs with private values."""

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.web.main import app


@pytest.mark.parametrize("database_error", [False, True])
async def test_unexpected_web_error_keeps_private_details_out_of_response_and_logs(caplog, database_error):
    private_value = "synthetic-private-web-note"

    async def broken():
        if database_error:
            from sqlalchemy.exc import DBAPIError
            raise DBAPIError("select synthetic_private_sql", {"note": private_value}, RuntimeError(private_value))
        raise RuntimeError(private_value) from ValueError(private_value)

    route = APIRoute("/__private_test_error", broken)
    app.router.routes.insert(0, route)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/__private_test_error")
    finally:
        app.router.routes.remove(route)
    assert response.status_code == 500
    assert private_value not in response.text
    assert private_value not in caplog.text
    assert "synthetic_private_sql" not in caplog.text
    assert ("DBAPIError" if database_error else "RuntimeError") in caplog.text
    assert "test_private_errors.py:" in caplog.text
    assert not any(record.exc_info for record in caplog.records)


async def test_handled_http_error_preserves_the_intended_status_and_detail():
    async def rejected():
        raise HTTPException(409, "expected conflict")

    route = APIRoute("/__private_test_conflict", rejected)
    app.router.routes.insert(0, route)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/__private_test_conflict")
    finally:
        app.router.routes.remove(route)
    assert response.status_code == 409
    assert response.json() == {"detail": "expected conflict"}


async def test_stream_failure_closes_response_with_only_a_sanitized_exception(caplog):
    import traceback

    from app.web.private_errors import PrivateErrorMiddleware, SanitizedResponseError

    private_value = "synthetic-private-stream-note"

    async def stream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        raise RuntimeError(private_value)

    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    with pytest.raises(SanitizedResponseError) as error:
        await PrivateErrorMiddleware(stream)({"type": "http"}, receive, send)
    assert private_value not in "".join(traceback.format_exception(error.value))
    assert private_value not in caplog.text
    assert "RuntimeError" in caplog.text
    assert [m["type"] for m in sent].count("http.response.start") == 1
    assert sent[-1]["more_body"] is True
