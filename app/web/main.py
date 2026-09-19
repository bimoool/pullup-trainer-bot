from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web.routes import router

# Dockerfile.web собирает webapp-frontend/ в статику и кладёт её сюда —
# тот же процесс FastAPI отдаёт и /api/*, и статику одним origin'ом, без
# CORS (см. docs/mini-app.md, Mini App: Этап 0). Путь совпадает с COPY в
# Dockerfile.web.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "webapp-frontend" / "dist"

app = FastAPI(title="pullup-trainer-bot mini app")
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Без initData/БД намеренно — только "процесс жив", для healthcheck
    в docker-compose.yml. /api/hello сам по себе не годится: требует
    подписанный initData, 401/422 без него неотличимы от процесса,
    который не поднялся."""
    return {"status": "ok"}


if FRONTEND_DIST.is_dir():
    # html=True — неизвестные пути (например, /workout при обновлении
    # страницы в React Router) отдают index.html, а не 404: клиентский
    # роутинг сам разберётся, какой экран показать.
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
