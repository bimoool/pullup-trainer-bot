"""CacheControlStaticFiles (issue #27) — index.html не должен кэшироваться
(Telegram Mini App клиенты, особенно мобильные, агрессивно кэшируют
index.html без Cache-Control, и задеплоенные фиксы не доходят до
пользователя), а хешированные Vite-бандлы в assets/ наоборот можно и нужно
кэшировать надолго — независимо от собранного webapp-frontend/dist (тест
строит свою временную директорию, не завязан на реальную сборку)."""

from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.web.static import CacheControlStaticFiles


def _build_app(dist_dir: Path) -> FastAPI:
    app = FastAPI()
    app.mount("/", CacheControlStaticFiles(directory=dist_dir, html=True), name="frontend")
    return app


async def test_index_html_is_never_cached(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html>root</html>")

    async with AsyncClient(transport=ASGITransport(app=_build_app(tmp_path)), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


async def test_hashed_asset_is_cached_aggressively(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html>root</html>")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "index-abc123.js").write_text("console.log('hi')")

    async with AsyncClient(transport=ASGITransport(app=_build_app(tmp_path)), base_url="http://test") as client:
        response = await client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
