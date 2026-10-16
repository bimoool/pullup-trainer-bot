"""Коммит сессии БД — ДО отправки ответа (CI 16.10, run 38863710119).

``get_session`` коммитит в коде после ``yield``. В FastAPI по умолчанию (scope «request») этот код выполняется уже
ПОСЛЕ отправки ответа: клиент получал 200 на POST /api/v2/sessions/live раньше коммита, следующим запросом
(GET …/live/active) не видел свою сессию, и Live-экран завершал только что начатую тренировку. Исправление —
``Depends(get_session, scope="function")`` во всех роутах.
"""

from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app
from tests.test_web._v2_client import _FakeInitData, _FakeWebAppUser


def _session_dependants(dependant):
    for sub in dependant.dependencies:
        if sub.call is get_session:
            yield sub
        yield from _session_dependants(sub)


def _api_routes(routes):
    """FastAPI ≥ 0.13x держит подключённые роутеры обёртками (_IncludedRouter.original_router), а не плоским списком."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from _api_routes(route.routes)


def test_every_route_commits_before_the_response_is_sent():
    pairs = [(route, dep) for route in _api_routes(app.routes) for dep in _session_dependants(route.dependant)]
    assert len(pairs) > 50, "обход роутов не нашёл зависимостей сессии — проверка была бы пустой"
    late = [f"{','.join(sorted(route.methods))} {route.path}" for route, dep in pairs if dep.scope != "function"]
    assert late == [], f"сессия БД коммитится после отправки ответа: {late}"


async def test_commit_finishes_before_response_start(session, user):
    """Поведение, а не только объявление: на настоящем роуте (GET /api/v2/plan) выход из зависимости сессии
    (где коммит) случается раньше, чем ASGI-сервер получает начало ответа."""
    order: list[str] = []

    async def recording_session():
        yield session
        order.append("commit")

    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=user.telegram_id, first_name="Тест"))
    )
    app.dependency_overrides[get_session] = recording_session

    async def recording_app(scope, receive, send):
        async def tracked_send(message):
            if message["type"] == "http.response.start":
                order.append("response")
            await send(message)
        await app(scope, receive, tracked_send)

    try:
        async with AsyncClient(transport=ASGITransport(app=recording_app), base_url="http://test") as client:
            response = await client.get("/api/v2/plan")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert order[:2] == ["commit", "response"], order
