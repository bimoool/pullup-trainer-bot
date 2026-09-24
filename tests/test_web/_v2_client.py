"""HTTP-хелперы, общие для tests/test_web/test_v2_*.py (issue #165, волна 3)
— тот же приём подмены зависимостей, что test_equipment_band_items.py и
остальные test_web-файлы уже используют по отдельности, вынесенный сюда,
чтобы не дублировать в 5+ новых файлах. Имя с подчёркиванием — pytest не
собирает этот модуль как тестовый."""

from dataclasses import dataclass

from httpx import ASGITransport, AsyncClient

from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app


@dataclass
class _FakeWebAppUser:
    id: int
    first_name: str


@dataclass
class _FakeInitData:
    user: _FakeWebAppUser


def _override_dependencies(session, telegram_id: int) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def v2_get(session, telegram_id: int, path: str):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


async def v2_post(session, telegram_id: int, path: str, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(path, json=payload)
    finally:
        app.dependency_overrides.clear()


async def v2_patch(session, telegram_id: int, path: str, payload: dict):
    """Phase C2 (issue #188) — тот же паттерн, что v2_get/v2_post, для
    PATCH /workouts/{id}."""
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(path, json=payload)
    finally:
        app.dependency_overrides.clear()
