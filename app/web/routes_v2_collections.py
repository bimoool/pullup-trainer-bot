"""/api/v2/collections — редакционные подборки (CRIMPD, #271). Только чтение: подборки
создаёт сид/админ-скрипт. Показываются опубликованные подборки с ≥1 видимым элементом;
скрытое/приватное содержимое отфильтровано (PROJECT_SPEC §5), неизвестная или
неопубликованная подборка — 404."""

from fastapi import APIRouter, Depends, HTTPException, status
from init_data_py import InitData
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.collections import CollectionRepository, VisibleCollection
from app.db.repositories.users import UserRepository
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.schemas_v2_collections import (
    CollectionDetailResponse,
    CollectionItemResponse,
    CollectionListResponse,
    CollectionSummaryResponse,
)

router_v2_collections = APIRouter(prefix="/api/v2/collections")


def _summary_fields(visible: VisibleCollection) -> dict:
    collection = visible.collection
    return {
        "id": collection.id,
        "title": collection.title,
        "description": collection.description,
        "author": collection.author_label,
        "items_count": len(visible.items),
        "programs_count": sum(1 for item in visible.items if item.item_type == "program"),
        "exercises_count": sum(1 for item in visible.items if item.item_type == "exercise"),
    }


async def _require_user(session: AsyncSession, init_data: InitData) -> None:
    if await UserRepository(session).get_by_telegram_id(init_data.user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")


@router_v2_collections.get("", response_model=CollectionListResponse)
async def list_collections(
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> CollectionListResponse:
    await _require_user(session, init_data)
    visible = await CollectionRepository(session).list_visible()
    return CollectionListResponse(collections=[CollectionSummaryResponse(**_summary_fields(v)) for v in visible])


@router_v2_collections.get("/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection(
    collection_id: int,
    init_data: InitData = Depends(get_validated_init_data),
    session: AsyncSession = Depends(get_session),
) -> CollectionDetailResponse:
    await _require_user(session, init_data)
    visible = await CollectionRepository(session).get_visible(collection_id)
    if visible is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    return CollectionDetailResponse(
        **_summary_fields(visible),
        items=[
            CollectionItemResponse(
                item_type=item.item_type, target_id=item.target_id, title=item.title, subtitle=item.subtitle,
            )
            for item in visible.items
        ],
    )
