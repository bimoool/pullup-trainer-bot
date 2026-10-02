from typing import Literal

from pydantic import BaseModel


class CollectionItemResponse(BaseModel):
    """Элемент подборки: программа каталога или system-упражнение (title — их имя)."""

    item_type: Literal["program", "exercise"]
    target_id: int
    title: str
    subtitle: str | None = None


class CollectionSummaryResponse(BaseModel):
    id: int
    title: str
    description: str | None
    author: str
    items_count: int
    programs_count: int
    exercises_count: int


class CollectionListResponse(BaseModel):
    collections: list[CollectionSummaryResponse]


class CollectionDetailResponse(CollectionSummaryResponse):
    items: list[CollectionItemResponse]
