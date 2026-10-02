"""CSV-экспорт истории (Crimpd "Export Log Data"): GET /api/v2/export/sessions.csv
(заголовок X-Telegram-Init-Data ИЛИ короткоживущий подписанный ?token=) и
POST /api/v2/export/link (выдаёт такую ссылку для downloadFile/window.open)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from init_data_py import InitData
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.services.history_export import (
    LINK_TTL_SECONDS,
    build_rows,
    render_csv,
    sign_link,
    verify_link,
)
from app.web.auth import get_validated_init_data
from app.web.db import get_session

router_v2_export = APIRouter(prefix="/api/v2/export")


class ExportLinkResponse(BaseModel):
    url: str
    expires_in: int


@router_v2_export.post("/link", response_model=ExportLinkResponse)
async def create_export_link(
    init_data: InitData = Depends(get_validated_init_data), session: AsyncSession = Depends(get_session),
) -> ExportLinkResponse:
    user = await UserRepository(session).get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    token = sign_link(settings.bot_token, user.id)
    return ExportLinkResponse(url=f"/api/v2/export/sessions.csv?token={token}", expires_in=LINK_TTL_SECONDS)


def get_optional_init_data(x_telegram_init_data: str | None = Header(None)) -> InitData | None:
    """initData из заголовка, если он есть (иначе — вход по подписанной ссылке)."""
    return None if x_telegram_init_data is None else get_validated_init_data(x_telegram_init_data)


async def _resolve_user(session: AsyncSession, token: str | None, init_data: InitData | None) -> User:
    users = UserRepository(session)
    if token is not None:
        user_id = verify_link(settings.bot_token, token)
        user = await users.get_by_id(user_id) if user_id is not None else None
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired export link")
        return user
    if init_data is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    user = await users.get_by_telegram_id(init_data.user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router_v2_export.get("/sessions.csv")
async def export_sessions_csv(
    token: str | None = Query(None),
    init_data: InitData | None = Depends(get_optional_init_data),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    user = await _resolve_user(session, token, init_data)
    rows = await build_rows(session, user_id=user.id, timezone=user.timezone)
    filename = f"training-history-{datetime.now(UTC).date().isoformat()}.csv"
    return StreamingResponse(
        render_csv(rows), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
