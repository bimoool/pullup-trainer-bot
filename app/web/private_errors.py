"""Prevent arbitrary exception details reaching Uvicorn's error logger."""

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.diagnostics import exception_diagnostic, safe_exception_trace

logger = logging.getLogger(__name__)


class SanitizedResponseError(RuntimeError):
    """Response already started; close it without exposing the original error."""


class PrivateErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exception:
            diagnostic = safe_exception_trace(exception)
            logger.exception("Unhandled web exception; %s", diagnostic, exc_info=False)
            if response_started:
                # Uvicorn must still see the failure and close the connection.
                # Suppress the original context, which may contain request data.
                raise SanitizedResponseError(exception_diagnostic(exception)) from None
            response = JSONResponse(
                status_code=500,
                content={"detail": "Не удалось выполнить запрос. Попробуйте ещё раз."},
            )
            await response(scope, receive, send)
