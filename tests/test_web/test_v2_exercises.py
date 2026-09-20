"""Тесты GET /api/v2/exercises (Checkpoint 3A, issue #196) — минимальная
Exercise Library без UI.

Required tests (из issue):
- GET /exercises возвращает существующие Exercise
- Планка присутствует
- Отжимания присутствуют
- Планка.metric_type == time
- Отжимания.metric_type == reps
- повторный seed не создаёт дублей
- endpoint не требует admin-доступа
"""

import pytest
from httpx import AsyncClient

from app.db.models_program import Exercise
from app.domain.multi_program import MetricType
from scripts.seed_exercise_library import seed_exercise_library


@pytest.mark.asyncio
async def test_list_exercises_returns_existing_exercises(test_client: AsyncClient, authed_headers: dict):
    """GET /exercises возвращает существующие Exercise."""
    response = await test_client.get("/api/v2/exercises", headers=authed_headers)
    assert response.status_code == 200
    data = response.json()
    assert "exercises" in data
    assert isinstance(data["exercises"], list)


@pytest.mark.asyncio
async def test_plank_present_with_time_metric(
    test_client: AsyncClient, authed_headers: dict, session_maker,
):
    """Планка присутствует + metric_type == time."""
    async with session_maker() as session:
        await seed_exercise_library(session)

    response = await test_client.get("/api/v2/exercises", headers=authed_headers)
    assert response.status_code == 200
    exercises = response.json()["exercises"]

    plank = next((ex for ex in exercises if ex["name"] == "Планка"), None)
    assert plank is not None, "Планка должна присутствовать"
    assert plank["metric_type"] == "time", "Планка должна иметь metric_type=time"
    assert plank["category"] == "Общая физическая подготовка"
    assert plank["subcategory"] is None


@pytest.mark.asyncio
async def test_pushups_present_with_reps_metric(
    test_client: AsyncClient, authed_headers: dict, session_maker,
):
    """Отжимания присутствуют + metric_type == reps."""
    async with session_maker() as session:
        await seed_exercise_library(session)

    response = await test_client.get("/api/v2/exercises", headers=authed_headers)
    assert response.status_code == 200
    exercises = response.json()["exercises"]

    pushups = next((ex for ex in exercises if ex["name"] == "Отжимания"), None)
    assert pushups is not None, "Отжимания должны присутствовать"
    assert pushups["metric_type"] == "reps", "Отжимания должны иметь metric_type=reps"
    assert pushups["category"] == "Общая физическая подготовка"
    assert pushups["subcategory"] is None


@pytest.mark.asyncio
async def test_repeated_seed_does_not_create_duplicates(session_maker):
    """Повторный seed не создаёт дубликаты — идемпотентность."""
    async with session_maker() as session:
        result1 = await seed_exercise_library(session)

    async with session_maker() as session:
        result2 = await seed_exercise_library(session)

    # Одинаковые id означают, что вторая попытка нашла уже существующие,
    # а не создала новые
    assert result1["Планка"] == result2["Планка"]
    assert result1["Отжимания"] == result2["Отжимания"]

    # Проверка прямым подсчётом в БД
    async with session_maker() as session:
        from sqlalchemy import func, select

        count_plank = await session.execute(
            select(func.count()).select_from(Exercise).where(Exercise.name == "Планка"),
        )
        assert count_plank.scalar_one() == 1, "Должна быть ровно одна Планка"

        count_pushups = await session.execute(
            select(func.count()).select_from(Exercise).where(Exercise.name == "Отжимания"),
        )
        assert count_pushups.scalar_one() == 1, "Должны быть ровно одни Отжимания"


@pytest.mark.asyncio
async def test_endpoint_does_not_require_admin_access(
    test_client: AsyncClient, authed_headers: dict, session_maker,
):
    """Endpoint не требует admin-доступа — обычный пользователь может
    пользоваться библиотекой."""
    # authed_headers — это обычный НЕ-админ пользователь (из conftest.py)
    async with session_maker() as session:
        await seed_exercise_library(session)

    response = await test_client.get("/api/v2/exercises", headers=authed_headers)
    assert response.status_code == 200, "Обычный пользователь должен иметь доступ"
    exercises = response.json()["exercises"]
    assert len(exercises) >= 2, "Должны быть доступны хотя бы 2 упражнения"


@pytest.mark.asyncio
async def test_exercise_response_fields_match_model(
    test_client: AsyncClient, authed_headers: dict, session_maker,
):
    """Response содержит только поля, реально существующие в Exercise model
    (не equipment/difficulty/duration/muscles)."""
    async with session_maker() as session:
        await seed_exercise_library(session)

    response = await test_client.get("/api/v2/exercises", headers=authed_headers)
    assert response.status_code == 200
    exercises = response.json()["exercises"]
    assert len(exercises) >= 1

    exercise = exercises[0]
    # Обязательные поля
    assert "id" in exercise
    assert "name" in exercise
    assert "metric_type" in exercise
    assert "category" in exercise
    assert "subcategory" in exercise

    # Недопустимые поля (не существуют в Exercise model волны 1)
    assert "equipment" not in exercise
    assert "difficulty" not in exercise
    assert "duration" not in exercise
    assert "muscles" not in exercise
