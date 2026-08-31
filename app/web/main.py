from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.rules import TrainingReadiness, check_training_readiness
from app.web.auth import InitData, get_init_data
from app.web.schemas import HelloResponse

_READINESS_LABELS = {
    TrainingReadiness.READY: "Можно тренироваться",
    TrainingReadiness.TOO_EARLY: "Ещё рано, нужен отдых",
    TrainingReadiness.GAP_ROLLBACK: "Давно не было тренировки — цель будет снижена",
    TrainingReadiness.GAP_RETEST_REQUIRED: "Долгий перерыв — нужен новый замер",
}

# Собранный webapp-frontend (см. Dockerfile.web) — сайд-каром рядом с app/,
# не внутри пакета. В dev-окружении без сборки фронтенда каталога нет,
# static-раздача просто не подключается (см. низ файла), но /api/* работает.
STATIC_DIR = Path(__file__).resolve().parents[2] / "webapp-frontend" / "dist"

app = FastAPI(title="pullup-trainer-bot mini app")


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/hello", response_model=HelloResponse)
async def hello(
    init_data: InitData = Depends(get_init_data),
    session: AsyncSession = Depends(get_session),
) -> HelloResponse:
    """Единственный содержательный эндпойнт Этапа 0 — доказывает цепочку
    целиком: initData → тот же UserRepository, что использует бот → тот же
    app.domain.rules.check_training_readiness, что и хендлер тренировки в
    боте (app/bot/handlers/workout.py). Ничего сверх этого пока не строим
    (см. CLAUDE.md, раздел "Mini App: Этап 0")."""
    users = UserRepository(session)
    user = await users.get_by_telegram_id(init_data.telegram_id)

    if user is None:
        return HelloResponse(
            greeting=f"Привет, {init_data.first_name}! Похоже, ты ещё не начинал(а) в боте — напиши /start.",
            is_registered=False,
            readiness=None,
        )

    workouts = WorkoutRepository(session)
    history = await workouts.list_for_user(user.id)
    readiness_label = None
    if history:
        readiness = check_training_readiness(history[-1].performed_at.date(), datetime.now(UTC).date())
        readiness_label = _READINESS_LABELS[readiness.status]

    return HelloResponse(
        greeting=f"Привет, {init_data.first_name}!",
        is_registered=True,
        readiness=readiness_label,
    )


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
