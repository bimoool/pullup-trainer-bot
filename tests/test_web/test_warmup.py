"""GET /api/warmup (issue #124, PR 1) — первый перенесённый бот-only кусок
Mini App: тот же texts.WARMUP_FULL, что видит пользователь бота
(app/bot/handlers/workout.py::handle_warmup_show), без initData — тот же
уровень доступа, что у /api/faq/band-help (см. докстринг эндпойнта)."""

from httpx import ASGITransport, AsyncClient

from app.bot import texts
from app.web.main import app


async def test_warmup_returns_bot_text_without_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/warmup")

    assert response.status_code == 200
    assert response.json() == {"text_html": texts.WARMUP_FULL}
